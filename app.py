import base64
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

from cccd import decode_so_cccd, kiem_tra_khop, parse_cccd
from qr_html import QR_HTML
from scanner import decode_image, is_cccd

st.set_page_config(page_title="Quét QR CCCD", page_icon="🪪", layout="centered")

def _make_component():
    """Ghi HTML nhúng sẵn ra thư mục tạm rồi khai báo component. Lỗi thì trả None."""
    try:
        d = Path(tempfile.gettempdir()) / "cccd_qr_component"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(QR_HTML, encoding="utf-8")
        return components.declare_component("qr_live", path=str(d))
    except Exception:
        return None


qr_live = _make_component()  # camera độ phân giải cao chạy trong trình duyệt

MIN_SIDE_OK = 1000  # cạnh dài tối thiểu để đọc được QR dày của CCCD


def pil_to_bgr(pil: Image.Image):
    pil = ImageOps.exif_transpose(pil).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def data_url_to_bgr(data_url: str):
    b = base64.b64decode(data_url.split(",", 1)[1])
    arr = np.frombuffer(b, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def set_result(raw: str, method: str):
    st.session_state.raw = raw
    st.session_state.method = method
    st.rerun()


def scan_bgr(bgr):
    with st.spinner("Đang quét (ảnh mờ có thể mất vài giây)..."):
        r = decode_image(bgr)
    if r["raw"] and r["ok"]:
        set_result(r["raw"], r["method"])
    elif r["raw"]:
        st.warning("Có mã QR nhưng không phải QR của CCCD.")
        st.code(r["raw"])
    else:
        st.error("Không đọc được mã QR.")
        longest = max(r["w"], r["h"])
        if longest < MIN_SIDE_OK:
            st.info(
                f"Ảnh chỉ {r['w']}×{r['h']} px, **quá nhỏ**: mã QR của CCCD rất dày nên cần "
                f"ảnh có cạnh dài từ {MIN_SIDE_OK} px trở lên (điện thoại thường 3000–4000 px). "
                "Nếu ảnh nhận qua Zalo: nhờ người gửi bật chế độ **ảnh HD / ảnh gốc** hoặc gửi "
                "**dạng file (tài liệu)**, hoặc quét trực tiếp thẻ thật ở tab **Quét trực tiếp**."
            )
        else:
            nhan = "rất mờ" if r["sharp"] < 30 else ("hơi mờ" if r["sharp"] < 100 else "khá nét")
            st.info(
                f"Ảnh {r['w']}×{r['h']} px, độ nét {r['sharp']:.0f} ({nhan}). "
                "Hãy chụp gần hơn để mã QR chiếm khoảng 1/3 khung hình, đủ sáng, tránh chói."
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

for k, v0 in (("raw", None), ("method", None), ("qk", 0), ("last_t", None)):
    st.session_state.setdefault(k, v0)

if st.session_state.raw is None:
    tab_live, tab_up = st.tabs(["⚡ Quét trực tiếp (khuyên dùng)", "📁 Chụp / tải ảnh"])

    with tab_live:
        st.write(
            "Bấm **Bật camera**, đưa **mặt sau CCCD (có mã QR)** vào khung. "
            "Tự nhận ngay, không cần bấm chụp. Camera chạy ở độ phân giải cao nên đọc được mã QR dày."
        )
        val = qr_live(key=f"qr_live_{st.session_state.qk}", default=None) if qr_live else None
        if qr_live is None:
            st.warning("Không khởi tạo được camera trực tiếp. Hãy dùng tab **Chụp / tải ảnh**.")
        if val and val.get("t") != st.session_state.last_t:
            st.session_state.last_t = val["t"]
            if val.get("type") == "text":
                if is_cccd(val["text"]):
                    set_result(val["text"], f"trình duyệt ({val.get('w')}×{val.get('h')})")
                else:
                    st.warning("Có mã QR nhưng không phải QR của CCCD.")
            elif val.get("type") == "image":
                st.caption(f"Ảnh nhận được: {val.get('w')}×{val.get('h')} px")
                scan_bgr(data_url_to_bgr(val["data"]))

    with tab_up:
        st.write(
            "Trên điện thoại: bấm chọn file rồi chọn **Chụp ảnh** để dùng camera gốc "
            "(ảnh lớn, tự lấy nét). Đừng dùng ảnh đã gửi qua Zalo/Messenger vì bị nén nhỏ."
        )
        f = st.file_uploader("Ảnh mặt sau CCCD (có mã QR)", type=["jpg", "jpeg", "png", "webp"])
        if f:
            img = Image.open(f)
            st.image(img, caption=f"Ảnh đầu vào ({img.width}×{img.height} px)", width=400)
            scan_bgr(pil_to_bgr(img))
else:
    show_result(st.session_state.raw)
    if st.session_state.get("method"):
        st.caption(f"Đọc bằng: {st.session_state.method}")
    if st.button("🔄 Quét thẻ khác"):
        st.session_state.raw = None
        st.session_state.last_t = None
        st.session_state.qk += 1
        st.rerun()
