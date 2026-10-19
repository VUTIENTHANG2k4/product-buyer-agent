"""Chuẩn hóa giá hiển thị trên trang bán lẻ về số nguyên VND (docs/04 §7)."""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

MIN_PRICE_VND = 10_000
MAX_PRICE_VND = 500_000_000
_MAX_DIGITS = 15  # dài hơn chắc chắn ngoài miền; tránh giới hạn 4300 chữ số của int()
_MASKED_MARKERS = ("*", "?")
_NEGATIVE_SIGNS = "-−–—"  # '-', '−', '–', '—'
# Một số: các nhóm chữ số nối bằng ".", ",", khoảng trắng (kể cả NBSP): "27.490.000", "9 990 000".
_NUMBER = re.compile(r"\d+(?:[.,\u00a0\u202f ]\d+)*")
_NON_DIGITS = re.compile(r"\D+")
# Số thập phân kiểu "27.490.000,50" / "27,490,000.50": phần lẻ dưới 1 đồng không có nghĩa với VND.
_FRACTION = re.compile(r"[.,]\d{1,2}$")
_THOUSANDS = re.compile(r"^\d{1,3}([.,\u00a0\u202f ]\d{3})*$")


def parse_price(raw: str | int | None) -> int | None:
    """`27.490.000₫` → `27490000`; giá bị che, không đọc được hoặc không rõ ràng → `None`.

    Chỉ lấy số đầu tiên trong chuỗi: huy hiệu đi kèm ("-5%", "Trả góp 0%", "3 cái") bị bỏ qua.
    Trả `None` khi: số đứng sau dấu âm (số tiền giảm), có nhiều số trông như giá (khoảng giá
    "A - B", giá cũ + giá mới) vì không biết số nào là giá bán, hoặc ngoài miền
    [10.000; 500.000.000] (kể cả 0 và "Liên hệ"); trường hợp cuối có log `WARNING`.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return _in_range(raw, str(raw))
    text = unicodedata.normalize("NFKC", raw).strip()  # toàn chiều rộng, NBSP → dạng thường
    if not text or any(marker in text for marker in _MASKED_MARKERS):
        return None
    matches = list(_NUMBER.finditer(text))
    if not matches:
        return None
    first = matches[0]
    if first.start() > 0 and text[first.start() - 1] in _NEGATIVE_SIGNS:
        return None
    values = [_read_number(match.group()) for match in matches]
    if any(value is not None and value >= MIN_PRICE_VND for value in values[1:]):
        return None  # hai giá trong một chuỗi: không đoán
    if values[0] is None:
        logger.warning("Giá ngoài miền hợp lý, bỏ qua: %r", text[:60])
        return None
    return _in_range(values[0], text)


def _read_number(token: str) -> int | None:
    """Giá trị số nguyên của một cụm số; `None` nếu quá dài."""
    number = token
    if re.search(r"[.,]", token) and not _THOUSANDS.match(token):
        number = _FRACTION.sub("", token)
    digits = _NON_DIGITS.sub("", number)
    if not digits or len(digits) > _MAX_DIGITS:
        return None
    return int(digits)


def _in_range(value: int, original: str) -> int | None:
    if MIN_PRICE_VND <= value <= MAX_PRICE_VND:
        return value
    logger.warning("Giá ngoài miền hợp lý, bỏ qua: %r", original[:60])
    return None
