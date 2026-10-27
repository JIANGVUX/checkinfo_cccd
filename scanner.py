"""Đọc QR CCCD: nhanh, chính xác, nhạy."""
import cv2
import numpy as np

try:
    import zxingcpp
except Exception:  # pragma: no cover
    zxingcpp = None

try:
    from pyzbar.pyzbar import decode as zbar_decode, ZBarSymbol
except Exception:  # pragma: no cover
    zbar_decode = None
    ZBarSymbol = None

MAX_SIDE = 1600  # ảnh lớn hơn sẽ được thu nhỏ để quét nhanh hơn


def is_cccd(raw: str) -> bool:
    """QR CCCD: Số CCCD|CMND cũ|Họ tên|Ngày sinh|Giới tính|Địa chỉ|Ngày cấp"""
    if not raw:
        return False
    p = raw.split("|")
    so = p[0].strip()
    return len(p) >= 6 and so.isdigit() and len(so) in (9, 12)


def _zx(img):
    if zxingcpp is None:
        return []
    try:
        res = zxingcpp.read_barcodes(
            img,
            formats=zxingcpp.BarcodeFormat.QRCode,
            try_rotate=True,
            try_downscale=True,
        )
    except TypeError:
        try:
            res = zxingcpp.read_barcodes(img)
        except Exception:
            return []
    except Exception:
        return []
    return [r.text for r in res if r.text]


def _zb(img):
    if zbar_decode is None:
        return []
    try:
        res = zbar_decode(img, symbols=[ZBarSymbol.QRCODE])
    except Exception:
        return []
    return [r.data.decode("utf-8", errors="ignore") for r in res]


def _candidates(img):
    for fn in (_zx, _zb):
        for text in fn(img):
            yield text


def _to_gray(bgr):
    if bgr.ndim == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _limit_size(img):
    h, w = img.shape[:2]
    m = max(h, w)
    if m > MAX_SIDE:
        s = MAX_SIDE / m
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return img


def fast_decode(bgr):
    """Dùng cho video: chỉ 1 lần thử trên ảnh xám, rất nhanh."""
    gray = _limit_size(_to_gray(bgr))
    for text in _candidates(gray):
        if is_cccd(text):
            return text
    return None


def _variants(gray):
    """Sinh dần các biến thể ảnh, từ rẻ đến tốn công."""
    yield gray

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    yield eq

    h, w = gray.shape[:2]
    if max(h, w) < 1000:
        yield cv2.resize(eq, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    yield cv2.addWeighted(gray, 1.8, blur, -0.8, 0)  # làm nét

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu

    yield cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )

    if max(h, w) > 800:
        yield cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

    # Cắt vùng giữa (QR thường nằm gần giữa ảnh khi chụp)
    y0, y1 = int(h * 0.15), int(h * 0.85)
    x0, x1 = int(w * 0.15), int(w * 0.85)
    yield gray[y0:y1, x0:x1]


def decode_image(bgr):
    """Trả về (raw, hop_le). hop_le=True nếu đúng định dạng CCCD."""
    gray = _limit_size(_to_gray(np.ascontiguousarray(bgr)))
    fallback = None
    for v in _variants(gray):
        for text in _candidates(v):
            if is_cccd(text):
                return text, True
            if fallback is None:
                fallback = text
    return fallback, False
