"""Khung thông số chuột (docs/04 §5.2) và bộ trích xuất theo luật (docs/04 §7)."""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel

from app.domain.dto import NonEmptyStr
from app.normalize.specs.parsing import (
    build_specs,
    clean,
    has_word,
    label_values,
    parse_grams_all,
    peripheral_connection,
)
from app.normalize.specs.types import MouseShape, PeripheralConnection, PositiveInt
from app.normalize.text import fold

# Danh sách rỗng coi như thiếu.
REQUIRED_FIELDS: Final = ("connection",)


class MouseSpecs(BaseModel):
    connection: list[PeripheralConnection] | None = None
    dpi_max: PositiveInt | None = None
    sensor: NonEmptyStr | None = None
    buttons: PositiveInt | None = None
    weight_g: PositiveInt | None = None
    rgb: bool | None = None
    shape: MouseShape | None = None


# ---- bộ trích xuất theo luật ----
_CONNECTION_LABELS: Final = ("ket noi", "chuan chuot", "chuan giao tiep", "giao tiep")
_DPI_LABELS: Final = ("do phan giai", "dpi", "cpi")
_SENSOR_LABELS: Final = ("cam bien", "sensor")
_BUTTON_LABELS: Final = ("so nut", "nut bam", "button")
_MAX_BUTTONS: Final = 99
_WEIGHT_LABELS: Final = ("trong luong", "can nang", "weight")
_LIGHT_LABELS: Final = ("den", "led", "rgb")

_DPI = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d{3,6})\s?(?:dpi|cpi)\b", re.IGNORECASE
)  # "25,600 DPI" / "12.000 DPI" có dấu phân tách hàng nghìn
_ERGONOMIC: Final = ("cong thai hoc", "ergonomic", "vertical")
_AMBIDEXTROUS: Final = ("doi xung", "ambidextrous", "symmetric")
_WEIGHT_RANGE_G: Final = range(
    20, 301
)  # ngoài khoảng này là đọc nhầm (không phải khối lượng chuột)


def _max_dpi(*texts: str) -> int | None:
    values = [int(re.sub(r"[.,]", "", match[1])) for text in texts for match in _DPI.finditer(text)]
    return max(values) if values else None


# "50G" viết hoa dính số là gia tốc cảm biến (hoặc "2.4G"), không phải gam: chỉ dùng làm phương án
# cuối khi tiêu đề không có khối lượng nào khác ("Chuột X 63G").
_G_FORCE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?G\b")


def _weight_g(title: str, raw_specs: Mapping[str, str]) -> int | None:
    candidates = [*label_values(raw_specs, _WEIGHT_LABELS), _G_FORCE.sub(" ", title), title]
    # Mọi khớp của từng chuỗi, không chỉ khớp đầu: "2.4G" (đọc thành 2 g) không che "99g" đứng sau.
    return next(
        (g for text in candidates for g in parse_grams_all(text) if g in _WEIGHT_RANGE_G), None
    )


def _buttons(raw_specs: Mapping[str, str]) -> int | None:
    for value in label_values(raw_specs, _BUTTON_LABELS):
        if match := re.search(r"\d+", value):
            return int(match[0]) if 1 <= int(match[0]) <= _MAX_BUTTONS else None  # 99999 là rác
    return None


def extract_mouse(title: str, raw_specs: Mapping[str, str]) -> MouseSpecs:
    """Thông số chuột đọc được từ tiêu đề và bảng thông số thô.

    Kết nối chỉ được điền khi tiêu đề/nhãn viết rõ ("không dây", "2.4G", "Bluetooth", "có dây"…);
    tên mẫu trơn như "Logitech G102" không đủ căn cứ nên để trống.
    """
    title = clean(title)
    folded_title = fold(title)
    connection_labels = list(label_values(raw_specs, _CONNECTION_LABELS))
    light = " ".join(label_values(raw_specs, _LIGHT_LABELS))
    sensor = next(label_values(raw_specs, _SENSOR_LABELS), None)

    shape: MouseShape | None = None
    if any(word in folded_title for word in _ERGONOMIC):
        shape = MouseShape.ergo_right
    elif any(word in folded_title for word in _AMBIDEXTROUS):
        shape = MouseShape.ambidextrous

    return build_specs(
        MouseSpecs,
        {
            "connection": peripheral_connection(title, *connection_labels),
            "dpi_max": _max_dpi(title, *label_values(raw_specs, _DPI_LABELS)),
            "sensor": sensor[:80] if sensor else None,
            "buttons": _buttons(raw_specs),
            "weight_g": _weight_g(title, raw_specs),
            "rgb": True if has_word(fold(f"{title} {light}"), "rgb") else None,
            "shape": shape,
        },
    )
