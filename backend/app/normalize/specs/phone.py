"""Khung thông số điện thoại (docs/04 §5.5) và bộ trích xuất theo luật (docs/04 §7).

Mỗi biến thể dung lượng là một `Product` riêng nên `ram_gb`/`storage_gb` là số đơn.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import BaseModel

from app.domain.dto import NonEmptyStr
from app.normalize.specs.parsing import (
    build_specs,
    capacities_gb,
    clean,
    label_values,
    parse_inches,
)
from app.normalize.specs.types import PositiveFloat, PositiveInt
from app.normalize.text import fold

REQUIRED_FIELDS: Final = ("ram_gb", "storage_gb")


class PhoneSpecs(BaseModel):
    chipset: NonEmptyStr | None = None
    ram_gb: PositiveInt | None = None
    storage_gb: PositiveInt | None = None
    screen_in: PositiveFloat | None = None
    battery_mah: PositiveInt | None = None
    os: NonEmptyStr | None = None


# ---- bộ trích xuất theo luật ----
_RAM_LABELS: Final = ("dung luong ram", "ram")
_STORAGE_LABELS: Final = ("bo nho trong", "dung luong luu tru", "rom")
_SCREEN_LABELS: Final = ("kich thuoc man hinh", "man hinh")
_BATTERY_LABELS: Final = ("dung luong pin", "pin")
_CHIPSET_LABELS: Final = ("chip xu ly", "chipset", "vi xu ly")
_OS_LABELS: Final = ("he dieu hanh",)

# RAM điện thoại tới 24 GB. Một dung lượng đơn từ 32 GB trở lên là bộ nhớ trong; dưới mức đó
# không đủ để nói là RAM hay bộ nhớ trong nên để trống.
_MAX_RAM_GB: Final = 24
_MIN_SINGLE_STORAGE_GB: Final = 32
_PAIR: Final = 2
# Nhãn nói về bộ nhớ mở rộng ("Thẻ nhớ ngoài", "Lưu trữ mở rộng") không phải bộ nhớ trong.
_EXPANSION_LABEL = re.compile(r"mo rong|the nho|\bsd\b|micro ?sd")
_MIN_STORAGE_GB: Final = 4
_MAX_STORAGE_GB: Final = 4000
_MIN_SCREEN_IN: Final = 2.0
_MAX_SCREEN_IN: Final = 12.0
_MIN_BATTERY_MAH: Final = 500
_MAX_BATTERY_MAH: Final = 30000
_MAX_TEXT: Final = 80

_BARE_NUMBER = re.compile(r"^(\d{1,2}(?:[.,]\d{1,2})?)$")
# "5.000 mAh", "5,000mAh", "6000 mAh" (dấu ngăn nghìn là "." hoặc ",").
_BATTERY = re.compile(r"(?<![\d.,])(\d{1,2}[.,]\d{3}|\d{3,5})\s?mah\b", re.IGNORECASE)


def _memory_from_title(title: str) -> tuple[int | None, int | None]:
    """(RAM, bộ nhớ trong) từ các dung lượng GB/TB trong tiêu đề.

    Hai dung lượng tăng dần ("8GB/128GB", "(4GB, 64GB)") là RAM rồi bộ nhớ trong. Một dung lượng
    từ 32 GB trở lên là bộ nhớ trong ("iPhone 16 128GB"); dưới 32 GB hoặc từ ba dung lượng trở lên
    ("8GB (+8GB mở rộng)/256GB") không đủ căn cứ nên để trống.
    """
    found = capacities_gb(title)
    if len(found) == 1 and _MIN_SINGLE_STORAGE_GB <= found[0] <= _MAX_STORAGE_GB:
        return None, found[0]
    if len(found) == _PAIR and found[0] < found[1] and found[0] <= _MAX_RAM_GB:
        return (found[0], found[1]) if found[1] <= _MAX_STORAGE_GB else (None, None)
    return None, None


def _labelled_capacity(
    raw_specs: Mapping[str, str], aliases: Sequence[str], low: int, high: int
) -> int | None:
    """Dung lượng của nhãn khi nhãn chỉ ghi đúng một dung lượng ("128 GB"); danh sách các tùy
    chọn ("128GB, 256GB") là của cả dòng máy nên không dùng."""
    own = {
        label: value
        for label, value in raw_specs.items()
        if not (isinstance(label, str) and _EXPANSION_LABEL.search(fold(label)))
    }
    for value in label_values(own, aliases):
        found = capacities_gb(value)
        if len(found) == 1 and low <= found[0] <= high:
            return found[0]
    return None


def _screen_in(title: str, raw_specs: Mapping[str, str]) -> float | None:
    candidates = [*label_values(raw_specs, _SCREEN_LABELS), title]
    for text in candidates:
        size = parse_inches(text)
        if size is None and text is not title and (bare := _BARE_NUMBER.match(text)) is not None:
            size = float(bare[1].replace(",", "."))
        if size is not None and _MIN_SCREEN_IN <= size <= _MAX_SCREEN_IN:
            return size
    return None


def _battery_mah(title: str, raw_specs: Mapping[str, str]) -> int | None:
    for text in [*label_values(raw_specs, _BATTERY_LABELS), title]:
        if match := _BATTERY.search(text):
            value = int(re.sub(r"[.,]", "", match[1]))
            if _MIN_BATTERY_MAH <= value <= _MAX_BATTERY_MAH:
                return value
    return None


def _labelled_text(raw_specs: Mapping[str, str], aliases: Sequence[str]) -> str | None:
    for value in label_values(raw_specs, aliases):
        if len(value) <= _MAX_TEXT:
            return value
    return None


def extract_phone(title: str, raw_specs: Mapping[str, str]) -> PhoneSpecs:
    """Thông số điện thoại đọc được từ tiêu đề và bảng thông số thô.

    `ram_gb`/`storage_gb` ưu tiên tiêu đề (đúng biến thể của offer), bảng thông số chỉ bổ sung khi
    tiêu đề không nói rõ (iPhone không ghi RAM trong tên). Chip và hệ điều hành chỉ lấy từ bảng
    thông số, không đoán theo hãng; thiếu thì để trống.
    """
    title = clean(title)
    ram, storage = _memory_from_title(title)
    if ram is None:
        ram = _labelled_capacity(raw_specs, _RAM_LABELS, 1, _MAX_RAM_GB)
    if storage is None:
        storage = _labelled_capacity(raw_specs, _STORAGE_LABELS, _MIN_STORAGE_GB, _MAX_STORAGE_GB)
    return build_specs(
        PhoneSpecs,
        {
            "chipset": _labelled_text(raw_specs, _CHIPSET_LABELS),
            "ram_gb": ram,
            "storage_gb": storage,
            "screen_in": _screen_in(title, raw_specs),
            "battery_mah": _battery_mah(title, raw_specs),
            "os": _labelled_text(raw_specs, _OS_LABELS),
        },
    )
