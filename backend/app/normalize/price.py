"""Chuẩn hóa giá hiển thị trên trang bán lẻ về số nguyên VND (docs/04 §7)."""

import logging
import re

logger = logging.getLogger(__name__)

MIN_PRICE_VND = 10_000
MAX_PRICE_VND = 500_000_000
_MASKED_MARKERS = ("*", "?")
_NON_DIGITS = re.compile(r"\D+")
# Số thập phân kiểu "27.490.000,50" / "27,490,000.50": phần lẻ dưới 1 đồng không có nghĩa với VND.
_FRACTION = re.compile(r"[.,]\d{1,2}$")
_THOUSANDS = re.compile(r"^\d{1,3}([.,\s]\d{3})*$")


def parse_price(raw: str | int | None) -> int | None:
    """`27.490.000₫` → `27490000`; giá bị che, không đọc được hoặc ngoài miền hợp lý → `None`.

    Ngoài miền [10.000, 500.000.000] (kể cả 0 và "Liên hệ") trả `None` kèm log `WARNING` khi có
    chữ số, để pipeline bỏ qua mục thay vì lưu giá sai.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return _in_range(raw, str(raw))
    text = raw.strip()
    if not text or any(marker in text for marker in _MASKED_MARKERS):
        return None
    number = text
    if "," in text or "." in text:
        # Chỉ coi dấu phân cách là nghìn khi cả chuỗi (sau khi bỏ đơn vị) đúng dạng nhóm 3 chữ số.
        core = re.sub(r"[^\d.,\s]", "", text).strip()
        if not _THOUSANDS.match(core):
            number = _FRACTION.sub("", core)
    digits = _NON_DIGITS.sub("", number)
    if not digits:
        return None
    return _in_range(int(digits), text)


def _in_range(value: int, original: str) -> int | None:
    if MIN_PRICE_VND <= value <= MAX_PRICE_VND:
        return value
    logger.warning("Giá ngoài miền hợp lý, bỏ qua: %r", original[:60])
    return None
