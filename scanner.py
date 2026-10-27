"""Đọc QR CCCD: chịu mờ, nhanh, chính xác.

Chiến lược: thử từ rẻ đến tốn công, dừng ngay khi đọc được.
Bộ đọc: zxing-cpp -> WeChat (OpenCV contrib, chịu mờ tốt) -> pyzbar -> OpenCV chuẩn.
Xử lý ảnh: gốc -> thu nhỏ -> tăng tương phản -> làm nét -> phóng to
           -> nhị phân hóa -> khử mờ Wiener -> cắt giữa.
"""
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

try:
    import zxingcpp
except Exception:
    zxingcpp = None

try:
    from pyzbar.pyzbar import decode as zbar_decode, ZBarSymbol
except Exception:
    zbar_decode = None
    ZBarSymbol = None

MAX_SIDE = 1600
_wechat = None
WECHAT_SR = False  # True nếu đã nạp được mô hình siêu phân giải
_std = cv2.QRCodeDetector()


_MODEL_URL = "https://raw.githubusercontent.com/WeChatCV/opencv_3rdparty/wechat_qrcode/"
_MODEL_FILES = ("detect.prototxt", "detect.caffemodel", "sr.prototxt", "sr.caffemodel")
_MODEL_DIR = Path(__file__).parent / "models"


def _ensure_models():
    """Tải (1 lần) mô hình siêu phân giải của WeChat. Lỗi mạng thì bỏ qua."""
    try:
        _MODEL_DIR.mkdir(exist_ok=True)
        for name in _MODEL_FILES:
            p = _MODEL_DIR / name
            if not p.exists() or p.stat().st_size == 0:
                urllib.request.urlretrieve(_MODEL_URL + name, p)
        return [str(_MODEL_DIR / n) for n in _MODEL_FILES]
    except Exception:
        return None


def _get_wechat():
    global _wechat, WECHAT_SR
    if _wechat is None:
        cls = getattr(cv2, "wechat_qrcode_WeChatQRCode", None)
        if not cls:
            _wechat = False
        else:
            _wechat = None
            files = _ensure_models()
            if files:
                try:
                    _wechat = cls(*files)
                    WECHAT_SR = True
                except Exception:
                    _wechat = None
            if _wechat is None:
                _wechat = cls()
    return _wechat


def is_cccd(raw: str) -> bool:
    """QR CCCD: Số CCCD|CMND cũ|Họ tên|Ngày sinh|Giới tính|Địa chỉ|Ngày cấp"""
    if not raw:
        return False
    p = raw.split("|")
    so = p[0].strip()
    return len(p) >= 5 and so.isdigit() and len(so) in (9, 12)


# ---------- Các bộ đọc ----------
def _zx(img):
    if zxingcpp is None:
        return []
    try:
        res = zxingcpp.read_barcodes(
            img, formats=zxingcpp.BarcodeFormat.QRCode,
            try_rotate=True, try_downscale=True,
        )
    except TypeError:
        try:
            res = zxingcpp.read_barcodes(img)
        except Exception:
            return []
    except Exception:
        return []
    return [r.text for r in res if r.text]


def _wc(img):
    w = _get_wechat()
    if not w:
        return []
    try:
        texts, _ = w.detectAndDecode(img)
        return [t for t in texts if t]
    except Exception:
        return []


def _zb(img):
    if zbar_decode is None:
        return []
    try:
        res = zbar_decode(img, symbols=[ZBarSymbol.QRCODE])
    except Exception:
        return []
    return [r.data.decode("utf-8", errors="ignore") for r in res]


def _cv(img):
    try:
        t, _, _ = _std.detectAndDecode(img)
        return [t] if t else []
    except Exception:
        return []


DECODERS = (("zxing", _zx), ("wechat", _wc), ("zbar", _zb), ("opencv", _cv))


def _candidates(img, fast=False):
    decs = DECODERS[:2] if fast else DECODERS
    for name, fn in decs:
        for text in fn(img):
            yield name, text


# ---------- Xử lý ảnh ----------
def _to_gray(bgr):
    return bgr if bgr.ndim == 2 else cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _limit_size(img, max_side=MAX_SIDE):
    h, w = img.shape[:2]
    m = max(h, w)
    if m > max_side:
        img = cv2.resize(img, None, fx=max_side / m, fy=max_side / m,
                         interpolation=cv2.INTER_AREA)
    return img


def sharpness(gray) -> float:
    """Phương sai Laplacian: càng cao càng nét."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _unsharp(gray, amount=1.5, sigma=3):
    blur = cv2.GaussianBlur(gray, (0, 0), sigma)
    return cv2.addWeighted(gray, 1 + amount, blur, -amount, 0)


def _wiener(gray, sigma, K=0.01):
    """Khử mờ (giả định mờ kiểu Gaussian)."""
    g = gray.astype(np.float32) / 255.0
    h, w = g.shape
    ks = int(sigma * 6) | 1
    if ks >= min(h, w):
        return gray
    k = cv2.getGaussianKernel(ks, sigma)
    psf = k @ k.T
    P = np.zeros((h, w), np.float32)
    P[:ks, :ks] = psf
    P = np.roll(P, (-(ks // 2), -(ks // 2)), (0, 1))
    H = np.fft.fft2(P)
    F = np.conj(H) / (np.abs(H) ** 2 + K) * np.fft.fft2(g)
    f = np.real(np.fft.ifft2(F))
    return np.clip(f * 255, 0, 255).astype(np.uint8)


def _stages(gray):
    h, w = gray.shape[:2]
    m = max(h, w)
    yield "gốc", gray

    # Ảnh lớn bị mờ: thu nhỏ làm vết mờ nhỏ lại theo điểm ảnh
    if m > 1100:
        yield "thu nhỏ 0.6", cv2.resize(gray, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
    if m > 1500:
        yield "thu nhỏ 0.4", cv2.resize(gray, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA)

    eq = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    yield "tăng tương phản", eq

    sh = _unsharp(gray)
    yield "làm nét", sh

    # Ảnh nhỏ/bị nén (kiểu Zalo): phóng to rồi mới làm nét -> đọc được cả QR ~1.5px/ô
    for f in (2, 3, 4):
        if m * f <= 3200:
            up = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_LANCZOS4)
            yield f"phóng to {f}x + làm nét", _unsharp(up, 1.5, f * 1.2)
            if f == 2:
                yield "phóng to 2x", up

    _, otsu = cv2.threshold(sh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "nhị phân Otsu", otsu
    yield "nhị phân thích ứng", cv2.adaptiveThreshold(
        sh, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)

    # Khử mờ trên ảnh vừa phải để nhanh
    base = _limit_size(gray, 1100)
    for sigma in (1.5, 2.5, 3.5, 5.0):
        d = _wiener(base, sigma)
        yield f"khử mờ σ={sigma}", d
        yield f"khử mờ σ={sigma} + làm nét", _unsharp(d, 1.0, 2)

    y0, y1, x0, x1 = int(h * .15), int(h * .85), int(w * .15), int(w * .85)
    crop = gray[y0:y1, x0:x1]
    yield "cắt vùng giữa", crop
    yield "cắt giữa + phóng to", cv2.resize(_unsharp(crop), None, fx=2, fy=2,
                                              interpolation=cv2.INTER_CUBIC)


# ---------- API ----------
def fast_decode(bgr):
    """Dùng cho video: vài bước rẻ nhất."""
    gray = _limit_size(_to_gray(bgr))
    for img in (gray, _unsharp(gray)):
        for _, text in _candidates(img, fast=True):
            if is_cccd(text):
                return text
    return None


def decode_image(bgr, budget: float = 8.0) -> dict:
    """Quét ảnh tĩnh. Trả về dict: raw, ok, method, w, h, sharp."""
    gray = _limit_size(_to_gray(np.ascontiguousarray(bgr)))
    out = {"raw": None, "ok": False, "method": None,
           "w": bgr.shape[1], "h": bgr.shape[0], "sharp": sharpness(gray)}
    t0 = time.time()
    for stage, img in _stages(gray):
        for dec, text in _candidates(img):
            if is_cccd(text):
                out.update(raw=text, ok=True, method=f"{dec} · {stage}")
                return out
            if out["raw"] is None:
                out.update(raw=text, method=f"{dec} · {stage}")
        if time.time() - t0 > budget:
            break
    return out
