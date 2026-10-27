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
    def __init__(self):
        self.lock = threading.Lock()
        self.result = None
        self.n = 0

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        self.n += 1
        if self.result is None and self.n % 3 == 0:  # quét mỗi 3 khung hình
            raw = fast_decode(img)
            if raw:
                with self.lock:
                    self.result = raw
        if self.result is not None:
            h, w = img.shape[:2]
            cv2.rectangle(img, (4, 4), (w - 4, h - 4), (0, 200, 0), 8)
        return av.VideoFrame.from_ndarray(img, format="bgr24")


def pil_to_bgr(pil: Image.Image):
    pil = ImageOps.exif_transpose(pil).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


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
                    "width": {"ideal": 1280},
                    "height": {"ideal": 720},
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
    shot = st.camera_input("Đưa mã QR vào giữa khung, giữ nét rồi chụp")
    if shot:
        with st.spinner("Đang quét..."):
            raw, ok = decode_image(pil_to_bgr(Image.open(shot)))
        if raw and ok:
            st.session_state.raw = raw
            st.rerun()
        elif raw:
            st.warning("Có mã QR nhưng không phải QR của CCCD.")
            st.code(raw)
        else:
            st.error("Không đọc được. Hãy chụp gần hơn, đủ sáng, tránh chói và mờ.")

# --- Tab 3: tải ảnh ---
with tab_up:
    f = st.file_uploader("Chọn ảnh mặt sau CCCD (có mã QR)", type=["jpg", "jpeg", "png", "webp"])
    if f:
        img = Image.open(f)
        st.image(img, caption="Ảnh đầu vào", width=400)
        with st.spinner("Đang quét..."):
            raw, ok = decode_image(pil_to_bgr(img))
        if raw and ok:
            st.session_state.raw = raw
            st.rerun()
        elif raw:
            st.warning("Có mã QR nhưng không phải QR của CCCD.")
            st.code(raw)
        else:
            st.error("Không đọc được. Hãy dùng ảnh rõ nét, đủ sáng.")

# --- Kết quả ---
if st.session_state.raw:
    st.divider()
    show_result(st.session_state.raw)
