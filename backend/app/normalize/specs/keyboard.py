"""Khung thông số bàn phím (docs/04 §5.3) và bộ trích xuất theo luật (docs/04 §7)."""

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
    peripheral_connection,
)
from app.normalize.specs.types import (
    Backlight,
    FormFactor,
    PeripheralConnection,
    SwitchType,
)
from app.normalize.text import fold

# Danh sách rỗng (connection) coi như thiếu.
REQUIRED_FIELDS: Final = ("connection", "switch_type")


class KeyboardSpecs(BaseModel):
    connection: list[PeripheralConnection] | None = None
    switch_type: SwitchType | None = None
    switch_name: NonEmptyStr | None = None
    form_factor: FormFactor | None = None
    hot_swap: bool | None = None
    backlight: Backlight | None = None


# ---- bộ trích xuất theo luật ----
_CONNECTION_LABELS: Final = ("ket noi", "chuan giao tiep", "giao tiep")
_SWITCH_LABELS: Final = ("loai switch", "switch")
_LIGHT_LABELS: Final = ("den nen", "den led", "led")

_MAGNETIC = re.compile(r"hall[\s-]?effect|\btmr\b|magnetic|tu tinh")
_OPTICAL = re.compile(r"optical|\bquang\b")
_MEMBRANE = re.compile(r"membrane|gia co\b")
_MECHANICAL = re.compile(r"\bban phim co\b|mechanical|\bswitch\b|\b(?:tactile|linear|clicky)\b")
# "HE" (Hall Effect) chỉ nhận khi viết hoa nguyên từ trong tiêu đề gốc: "he" chữ thường quá chung.
_HE_WORD = re.compile(r"\bHE\b")
_SWITCH_NAME = re.compile(r"((?:[A-Za-z0-9]+\s+)?[A-Za-z0-9]+)\s+switch\b", re.IGNORECASE)
_NOT_SWITCH_NAME = frozenset(
    [
        "black",
        "white",
        "grey",
        "gray",
        "pink",
        "red",
        "blue",
        "green",
        "yellow",
        "purple",
        "orange",
        "silver",
        "magenta",
        "graphite",
        "cream",
        "gold",
        "den",
        "trang",
        "xam",
        "hong",
        "xanh",
        "vang",
        "tim",
        "bac",
        "mode",
        "3",
        "gaming",
        "wireless",
        "lightspeed",
        "bluetooth",
    ]
)
_FORM_TOKEN = re.compile(r"^(?:[a-z]{1,2})?(\d{2,3})%?$")
_FORM_BY_KEYS: Final = {
    "75": FormFactor.ff_75,
    "65": FormFactor.ff_65,
    "60": FormFactor.ff_60,
    "87": FormFactor.tkl,
    "98": FormFactor.other,
    "96": FormFactor.other,
    "100": FormFactor.full,
    "104": FormFactor.full,
    "108": FormFactor.full,
}


def _switch_type(title: str, folded: str) -> SwitchType | None:
    if _HE_WORD.search(title) or _MAGNETIC.search(folded):
        return SwitchType.magnetic
    if _OPTICAL.search(folded):
        return SwitchType.optical
    if _MEMBRANE.search(folded):
        return SwitchType.membrane
    if _MECHANICAL.search(folded):
        return SwitchType.mechanical
    return None


def _switch_name(text: str) -> str | None:
    """Tên switch ("Milk White", "Pegasus") là tối đa hai từ đứng trước chữ "switch"."""
    match = _SWITCH_NAME.search(text)
    if match is None:
        return None
    words = match[1].split()
    while words and fold(words[0]) in _NOT_SWITCH_NAME:
        words.pop(0)
    return " ".join(words) or None


def _form_factor(folded: str) -> FormFactor | None:
    if has_word(folded, "tkl"):
        return FormFactor.tkl
    if has_word(folded, "fullsize", "full size", "full-size"):
        return FormFactor.full
    for token in re.findall(r"[a-z0-9]+%?", folded):
        match = _FORM_TOKEN.match(token)
        if match and match[1] in _FORM_BY_KEYS:
            return _FORM_BY_KEYS[match[1]]
    return None


def _backlight(title_folded: str, raw_specs: Mapping[str, str]) -> Backlight | None:
    values = [fold(value) for value in label_values(raw_specs, _LIGHT_LABELS)]
    if has_word(title_folded, "rgb") or any(has_word(value, "rgb") for value in values):
        return Backlight.rgb
    for value in values:
        if value.startswith("khong") or value in {"no", "none"}:
            return Backlight.none
    return Backlight.single if values else None


def extract_keyboard(title: str, raw_specs: Mapping[str, str]) -> KeyboardSpecs:
    """Thông số bàn phím đọc được từ tiêu đề và bảng thông số thô.

    Kết nối và loại switch chỉ được điền khi viết rõ ("bàn phím cơ", "Tactile switch"…).
    `form_factor` đọc từ mã bố cục trong tên ("F75", "TKL", "65%"); bố cục 96/98 phím là `other`.
    """
    title = clean(title)
    folded = fold(title)
    connection_labels = list(label_values(raw_specs, _CONNECTION_LABELS))
    switch_labels = list(label_values(raw_specs, _SWITCH_LABELS))
    switch_text = " ".join([title, *switch_labels])

    return build_specs(
        KeyboardSpecs,
        {
            "connection": peripheral_connection(title, *connection_labels),
            "switch_type": _switch_type(title, fold(switch_text)),
            "switch_name": _switch_name(title) or _switch_name(" ".join(switch_labels)),
            "form_factor": _form_factor(folded),
            "hot_swap": True if re.search(r"hot[\s-]?swap", folded) else None,
            "backlight": _backlight(folded, raw_specs),
        },
    )
