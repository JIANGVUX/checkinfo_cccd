"""Phân tích dữ liệu QR CCCD và giải mã số CCCD."""
from datetime import datetime

MA_TINH = {
    "001": "Hà Nội", "002": "Hà Giang", "004": "Cao Bằng", "006": "Bắc Kạn",
    "008": "Tuyên Quang", "010": "Lào Cai", "011": "Điện Biên", "012": "Lai Châu",
    "014": "Sơn La", "015": "Yên Bái", "017": "Hòa Bình", "019": "Thái Nguyên",
    "020": "Lạng Sơn", "022": "Quảng Ninh", "024": "Bắc Giang", "025": "Phú Thọ",
    "026": "Vĩnh Phúc", "027": "Bắc Ninh", "030": "Hải Dương", "031": "Hải Phòng",
    "033": "Hưng Yên", "034": "Thái Bình", "035": "Hà Nam", "036": "Nam Định",
    "037": "Ninh Bình", "038": "Thanh Hóa", "040": "Nghệ An", "042": "Hà Tĩnh",
    "044": "Quảng Bình", "045": "Quảng Trị", "046": "Thừa Thiên Huế", "048": "Đà Nẵng",
    "049": "Quảng Nam", "051": "Quảng Ngãi", "052": "Bình Định", "054": "Phú Yên",
    "056": "Khánh Hòa", "058": "Ninh Thuận", "060": "Bình Thuận", "062": "Kon Tum",
    "064": "Gia Lai", "066": "Đắk Lắk", "067": "Đắk Nông", "068": "Lâm Đồng",
    "070": "Bình Phước", "072": "Tây Ninh", "074": "Bình Dương", "075": "Đồng Nai",
    "077": "Bà Rịa - Vũng Tàu", "079": "TP. Hồ Chí Minh", "080": "Long An",
    "082": "Tiền Giang", "083": "Bến Tre", "084": "Trà Vinh", "086": "Vĩnh Long",
    "087": "Đồng Tháp", "089": "An Giang", "091": "Kiên Giang", "092": "Cần Thơ",
    "093": "Hậu Giang", "094": "Sóc Trăng", "095": "Bạc Liêu", "096": "Cà Mau",
}


def fmt_date(s: str) -> str:
    s = (s or "").strip()
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%d%m%Y").strftime("%d/%m/%Y")
        except ValueError:
            pass
    return s


def parse_cccd(raw: str) -> dict:
    p = [x.strip() for x in raw.strip().split("|")]
    p += [""] * (7 - len(p))
    return {
        "Số CCCD": p[0],
        "Số CMND cũ": p[1] or "(không có)",
        "Họ và tên": p[2],
        "Ngày sinh": fmt_date(p[3]),
        "Giới tính": p[4],
        "Nơi thường trú": p[5],
        "Ngày cấp": fmt_date(p[6]),
    }


def decode_so_cccd(so: str) -> dict:
    if not (len(so) == 12 and so.isdigit()):
        return {}
    gt_code = int(so[3])
    the_ky = 1900 + (gt_code // 2) * 100
    return {
        "Nơi đăng ký khai sinh (mã tỉnh)": f"{MA_TINH.get(so[:3], 'Không rõ')} ({so[:3]})",
        "Giới tính theo số CCCD": "Nam" if gt_code % 2 == 0 else "Nữ",
        "Năm sinh theo số CCCD": the_ky + int(so[4:6]),
        "Dãy số ngẫu nhiên": so[6:],
    }


def kiem_tra_khop(info: dict, so_info: dict) -> list:
    if not so_info:
        return [("⚠️", "Số CCCD không đủ 12 chữ số (có thể là CMND 9 số).")]
    notes = []
    if so_info["Giới tính theo số CCCD"] != info["Giới tính"]:
        notes.append(("❌", "Giới tính trong QR không khớp với số CCCD."))
    else:
        notes.append(("✅", "Giới tính khớp với số CCCD."))
    nam = info["Ngày sinh"][-4:]
    if nam.isdigit() and int(nam) != so_info["Năm sinh theo số CCCD"]:
        notes.append(("❌", "Năm sinh trong QR không khớp với số CCCD."))
    else:
        notes.append(("✅", "Năm sinh khớp với số CCCD."))
    return notes
