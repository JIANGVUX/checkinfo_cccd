import threading
import time

import av
import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from streamlit_webrtc import VideoProcessorBase, WebRtcMode, webrtc_streamer

from cccd import decode_so_cccd, kiem_tra_khop, parse_cccd
from scanner import decode_image, fast_decode

st.set_page_config(page_title="Quét QR CCCD", page_icon="🪪", layout="centered")

RTC_CONFIG = {
    "iceServers": [
        {"urls": ["stun:stun.l.google.com:19302"]},
        {"urls": ["stun:stun1.l.google.com:19302"]},
    ]
}


# ---------- Quét video trực tiếp ----------
class QRProcessor(VideoProcessorBase):
    """Khung hình hiển thị mượt; việc quét chạy ở luồng nền trên khung mới nhất."""

    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None
        self.result = None
        self._stop = False
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        last = None
        while not self._stop and self.result is None:
            with self.lock:
                frame = self.latest
            if frame is None or frame is last:
                time.sleep(0.02)
                continue
            last = frame
            raw = fast_decode(frame)
            if raw:
                self.result = raw

    def on_ended(self):
        self._stop = True

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        with self.lock:
            self.latest = img.copy()
        if self.result is not None:
            h, w = img.shape[:2]
            cv2.rectangle(img, (4, 4), (w - 4, h - 4), (0, 200, 0), 8)
        return av.VideoFrame.from_ndarray(img, format="bgr24")


def pil_to_bgr(pil: Image.Image):
    pil = ImageOps.exif_transpose(pil).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def handle_scan(img_pil):
    with st.spinner("Đang quét (ảnh mờ có thể mất vài giây)..."):
        r = decode_image(pil_to_bgr(img_pil))
    if r["raw"] and r["ok"]:
        st.session_state.raw = r["raw"]
        st.session_state.method = r["method"]
        st.rerun()
    elif r["raw"]:
        st.warning("Có mã QR nhưng không phải QR của CCCD.")
        st.code(r["raw"])
    else:
        st.error("Không đọc được mã QR.")
        nhan = "RẤT MỜ" if r["sharp"] < 30 else ("hơi mờ" if r["sharp"] < 100 else "khá nét")
        st.info(
            f"Ảnh {r['w']}×{r['h']} px, độ nét {r['sharp']:.0f} ({nhan}).\n\n"
            "Cách khắc phục: dùng ảnh gốc từ camera điện thoại (không qua Zalo/Messenger vì bị nén), "
            "chụp gần để mã QR chiếm ít nhất 1/3 khung hình, bật đèn, tránh chói, giữ tay vững."
        )


def show_result(raw: str):
    info = parse_cccd(raw)
    so_info = decode_so_cccd(info["Số CCCD"])

    st.success("Đã đọc được mã QR CCCD")
    st.subheader("Thông tin trong QR")
    st.table(pd.DataFrame(info.items(), columns=["Trường", "Giá trị"]).set_index("Trường"))

    if so_info:
        st.subheader("Thông tin giải mã từ số CCCD")
        st.table(pd.DataFrame(so_info.items(), columns=["Trường", "Giá trị"]).set_index("Trường"))

    st.subheader("Đối chiếu nội bộ")
    for icon, msg in kiem_tra_khop(info, so_info):
        st.write(f"{icon} {msg}")
    st.caption("Chỉ đối chiếu các trường trong QR với nhau, không xác thực với cơ sở dữ liệu quốc gia.")

    with st.expander("Dữ liệu thô của QR"):
        st.code(raw)

    st.download_button(
        "⬇️ Tải kết quả (CSV)",
        pd.DataFrame([{**info, **so_info}]).to_csv(index=False).encode("utf-8-sig"),
        file_name="cccd.csv",
        mime="text/csv",
    )


# ---------- Giao diện ----------
st.title("🪪 Quét QR CCCD")
st.caption("Đọc và hiển thị toàn bộ thông tin trong mã QR trên căn cước công dân.")

if "raw" not in st.session_state:
    st.session_state.raw = None
    st.session_state.method = None

tab_live, tab_cam, tab_up = st.tabs(["⚡ Quét trực tiếp", "📷 Chụp ảnh", "📁 Tải ảnh lên"])

# --- Tab 1: video trực tiếp ---
with tab_live:
    st.write("Bấm **START**, cho phép camera, rồi đưa mã QR vào khung. Tự động nhận, không cần chụp.")
    if st.session_state.raw is None:
        ctx = webrtc_streamer(
            key="live",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=QRProcessor,
            rtc_configuration=RTC_CONFIG,
            media_stream_constraints={
                "video": {
                    "facingMode": "environment",
                    "width": {"ideal": 1920},
                    "height": {"ideal": 1080},
                    "advanced": [{"focusMode": "continuous"}],
                },
                "audio": False,
            },
            async_processing=True,
        )
        # Chờ kết quả từ luồng video
        while ctx.state.playing:
            vp = ctx.video_processor
            if vp is not None and vp.result:
                st.session_state.raw = vp.result
                st.rerun()
            time.sleep(0.15)
    else:
        if st.button("🔄 Quét thẻ khác"):
            st.session_state.raw = None
            st.rerun()

# --- Tab 2: chụp ảnh ---
with tab_cam:
    st.caption("Trên điện thoại, tab **Tải ảnh lên** cho ảnh gốc độ phân giải cao hơn nút chụp này.")
    shot = st.camera_input("Đưa mã QR vào giữa khung, giữ nét rồi chụp")
    if shot:
        handle_scan(Image.open(shot))

# --- Tab 3: tải ảnh / chụp bằng camera gốc ---
with tab_up:
    st.write("Trên điện thoại, bấm chọn rồi chọn **Chụp ảnh**: dùng camera gốc, tự lấy nét, ảnh rất nét.")
    f = st.file_uploader("Ảnh mặt sau CCCD (có mã QR)", type=["jpg", "jpeg", "png", "webp"])
    if f:
        img = Image.open(f)
        st.image(img, caption="Ảnh đầu vào", width=400)
        handle_scan(img)

# --- Kết quả ---
if st.session_state.raw:
    st.divider()
    show_result(st.session_state.raw)
    if st.session_state.get("method"):
        st.caption(f"Đọc bằng: {st.session_state.method}")
    if st.button("🔄 Quét thẻ khác", key="reset_bottom"):
        st.session_state.raw = None
        st.rerun()
