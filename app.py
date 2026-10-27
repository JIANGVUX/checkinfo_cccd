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
from scanner import decode_image, diagnose, is_cccd, pad_quiet_zone

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


def show_diag(bgr):
    """Bảng chẩn đoán: cho thấy bộ quét 'nhìn' ảnh ra sao và vì sao có thể thất bại."""
    d = diagnose(bgr)
    with st.expander("🔎 Chẩn đoán chi tiết (xem ảnh mà bộ quét nhìn thấy)", expanded=True):
        st.image(d["view"], caption="Vùng quét sau khi phóng to + làm nét. Bạn có thấy rõ từng ô vuông nhỏ không?",
                 clamp=True)
        hints = []
        if not d["frame_found"]:
            hints.append("❌ Không tìm thấy 3 ô vuông định vị ở 3 góc của mã QR: vùng chọn có thể "
                         "chưa chứa đủ mã QR (bị cắt mất góc), mã bị che, hoặc quá nhòe.")
        else:
            hints.append("✅ Đã thấy khung mã QR nhưng không giải mã được: các ô bên trong bị nhòe, nhiễu hoặc chói.")
        if d["saturated"] > 0.05:
            hints.append(f"⚠️ {d['saturated'] * 100:.0f}% điểm ảnh bị cháy sáng (chói đèn/phản quang). "
                         "Phần cháy trắng đã mất dữ liệu. Hãy chụp lại, nghiêng thẻ nhẹ để tránh phản chiếu.")
        if d["contrast"] < 60:
            hints.append(f"⚠️ Tương phản thấp ({d['contrast']:.0f}/255): ảnh bị xám/nhạt, cần chụp đủ sáng hơn.")
        if d["sharp"] < 30:
            hints.append("⚠️ Ảnh rất mờ (nhòe do rung tay hoặc lấy nét sai).")
        for h in hints:
            st.write(h)
        st.caption(
            f"Kỹ thuật: zxing={'có' if d['zxing'] else 'KHÔNG'}, wechat={'có' if d['wechat'] else 'KHÔNG'}"
            f"{' (có siêu phân giải)' if d['wechat_sr'] else ''}, zbar={'có' if d['zbar'] else 'KHÔNG'}, "
            f"opencv {d['opencv']}"
        )


def scan_bgr(bgr, crop=False, orig_size=None):
    """crop=True: bgr là vùng người dùng đã chọn (sẽ được thêm viền trắng quanh)."""
    src = pad_quiet_zone(bgr) if crop else bgr
    with st.spinner("Đang quét (ảnh mờ có thể mất vài giây)..."):
        r = decode_image(src)
    if r["raw"] and r["ok"]:
        set_result(r["raw"], ("vùng chọn · " if crop else "") + r["method"])
    elif r["raw"]:
        st.warning("Có mã QR nhưng không phải QR của CCCD.")
        st.code(r["raw"])
    elif crop:
        w = bgr.shape[1]
        st.error("Không đọc được mã QR trong vùng đã chọn.")
        st.info(
            f"Vùng chọn rộng khoảng {w} px, ước tính ≈ {w / 61:.1f} px cho mỗi ô QR "
            "(cần tối thiểu khoảng 1,5 px). Nếu con số thấp thì ảnh gốc không đủ chi tiết, "
            "cần xin ảnh HD hoặc ảnh gốc. Nếu con số ổn thì nguyên nhân thường là chói, mờ nhòe "
            "hoặc vùng chọn chưa ôm đủ mã QR: xem bảng chẩn đoán bên dưới."
        )
        show_diag(src)
    else:
        st.error("Không đọc được mã QR.")
        longest = max(r["w"], r["h"])
        if longest < MIN_SIDE_OK:
            st.info(
                f"Ảnh chỉ {r['w']}×{r['h']} px, **quá nhỏ**: mã QR của CCCD rất dày nên cần "
                f"ảnh có cạnh dài từ {MIN_SIDE_OK} px trở lên (điện thoại thường 3000–4000 px). "
                "Hãy thử bật **Tự chọn vùng chứa mã QR** ở trên. Nếu ảnh nhận qua Zalo, nhờ người gửi "
                "bật chế độ **ảnh HD / ảnh gốc** hoặc gửi **dạng file (tài liệu)**."
            )
            show_diag(src)
        else:
            nhan = "rất mờ" if r["sharp"] < 30 else ("hơi mờ" if r["sharp"] < 100 else "khá nét")
            st.info(
                f"Ảnh {r['w']}×{r['h']} px, độ nét {r['sharp']:.0f} ({nhan}). "
                "Hãy thử **chọn vùng chứa mã QR**, hoặc chụp gần hơn, đủ sáng, tránh chói."
            )
            show_diag(src)


def pick_region(img: Image.Image, key: str) -> Image.Image:
    """Cho người dùng khoanh vùng mã QR. Trả về ảnh PIL đã cắt, giữ nguyên độ phân giải gốc."""
    W, H = img.size
    prev = img.copy()
    prev.thumbnail((1000, 1000))
    try:
        from streamlit_cropper import st_cropper

        st.caption("Kéo khung xanh (kéo góc/cạnh để đổi kích thước) cho ôm sát mã QR.")
        box = st_cropper(prev, realtime_update=True, box_color="#00E676",
                         return_type="box", key=f"cropper_{key}")
        sx, sy = W / prev.width, H / prev.height
        l, t = int(box["left"] * sx), int(box["top"] * sy)
        w, h = int(box["width"] * sx), int(box["height"] * sy)
        l, t = max(l, 0), max(t, 0)
        r, btm = min(l + w, W), min(t + h, H)
        if r - l >= 20 and btm - t >= 20:
            return img.crop((l, t, r, btm))
        return img
    except Exception:
        # Dự phòng: thanh trượt (không cần thư viện ngoài)
        st.caption("Kéo thanh trượt để chọn vùng chứa mã QR.")
        x = st.slider("Ngang (trái–phải), %", 0, 100, (0, 100), key=f"sx_{key}")
        y = st.slider("Dọc (trên–dưới), %", 0, 100, (0, 100), key=f"sy_{key}")
        if x[1] - x[0] < 3 or y[1] - y[0] < 3:
            return img
        return img.crop((int(W * x[0] / 100), int(H * y[0] / 100),
                         int(W * x[1] / 100), int(H * y[1] / 100)))


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
            "(ảnh lớn, tự lấy nét). Ảnh nhận qua Zalo thường bị nén nhỏ nên khó quét hơn."
        )
        f = st.file_uploader("Ảnh mặt sau CCCD (có mã QR)", type=["jpg", "jpeg", "png", "webp"])
        if f:
            img = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
            st.caption(f"Ảnh gốc: {img.width}×{img.height} px")
            use_crop = st.checkbox(
                "✂️ Tự chọn vùng chứa mã QR (khuyên dùng khi ảnh nhỏ, mờ hoặc nhiều chi tiết)",
                value=True,
            )
            if use_crop:
                region = pick_region(img, key=f"{f.name}_{f.size}")
                st.image(region, caption=f"Vùng sẽ quét: {region.width}×{region.height} px", width=300)
                if st.button("🔍 Quét vùng này", type="primary"):
                    scan_bgr(pil_to_bgr(region), crop=True)
            else:
                st.image(img, caption="Ảnh đầu vào", width=400)
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
