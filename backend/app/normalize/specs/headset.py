"""Khung thông số tai nghe (docs/04 §5.4) và bộ trích xuất theo luật (docs/04 §7)."""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel

from app.normalize.specs.parsing import (
    affirmed,
    build_specs,
    clean,
    label_values,
    negated_label,
    read_connectivity,
)
from app.normalize.specs.types import HeadsetConnection, HeadsetForm, PositiveInt
from app.normalize.text import fold

# Danh sách rỗng (connection) coi như thiếu.
REQUIRED_FIELDS: Final = ("form", "connection")


class HeadsetSpecs(BaseModel):
    form: HeadsetForm | None = None
    connection: list[HeadsetConnection] | None = None
    has_mic: bool | None = None
    anc: bool | None = None
    surround_7_1: bool | None = None
    driver_mm: PositiveInt | None = None


# ---- bộ trích xuất theo luật ----
_CONNECTION_LABELS: Final = ("ket noi", "giao tiep", "cong ket noi", "cong giao tiep")
_MIC_LABELS: Final = ("micro", "mic")
_DRIVER_LABELS: Final = ("driver", "duong kinh loa", "kich thuoc loa")

_TWS = re.compile(r"\btws\b|true[\s-]?wireless")
_IN_EAR = re.compile(r"\bearbuds?\b|in[\s-]?ear|nhet tai")
_OVER_EAR = re.compile(r"over[\s-]?ear|chup tai|headband")
_ON_EAR = re.compile(r"\bon[\s-]?ear\b")
_ANC = re.compile(r"\banc\b|chong on chu dong|noise[\s-]?cancel|active noise")
_SURROUND = re.compile(r"(?<![\d.])7[.,]1\b")
_TITLE_MIC = re.compile(r"\b(?:co|kem|with)\s+mic(?:ro|rophone)?\b")
_DRIVER = re.compile(r"(?<![\d.])(\d{2})\s?mm\b")
_TITLE_DRIVER = re.compile(r"driver\s*(\d{2})\s?mm|(\d{2})\s?mm\s*driver")


def _form(folded: str) -> HeadsetForm | None:
    if _TWS.search(folded):
        return HeadsetForm.tws
    if _IN_EAR.search(folded):
        return HeadsetForm.in_ear
    if _OVER_EAR.search(folded):
        return HeadsetForm.over_ear
    if _ON_EAR.search(folded):
        return HeadsetForm.on_ear
    return None


_USB_C: Final = re.compile(r"\busb[\s-]*c\b(?!\s*/\s*a\b)|\btype[\s-]*c\b")


def _connection(text: str, form: HeadsetForm | None) -> list[HeadsetConnection] | None:
    """Kết nối đọc được. Không đoán: "True Wireless/TWS" chỉ suy ra Bluetooth; "không dây" chung
    chung không đủ để nói 2.4 GHz; "USB-C" thường là cổng sạc nên không tính là kết nối USB."""
    folded = fold(text)
    found = read_connectivity(folded)
    usb = read_connectivity(_USB_C.sub(" ", folded)).usb
    if form is HeadsetForm.tws:
        return [HeadsetConnection.bluetooth] if found.bluetooth or found.radio else None
    connection = [
        kind
        for kind, present in (
            (HeadsetConnection.wired_3_5, found.jack),
            (HeadsetConnection.usb, usb),
            (HeadsetConnection.wireless_2_4, found.explicit_radio),
            (HeadsetConnection.bluetooth, found.bluetooth),
        )
        if present
    ]
    return connection or None


def _has_mic(folded_title: str, raw_specs: Mapping[str, str]) -> bool | None:
    if affirmed(_TITLE_MIC, folded_title):
        return True
    for value in label_values(raw_specs, _MIC_LABELS):
        lowered = fold(value)
        return not negated_label(lowered) and lowered not in {"none", "n/a"}
    return None


def _driver_mm(folded_title: str, raw_specs: Mapping[str, str]) -> int | None:
    for value in label_values(raw_specs, _DRIVER_LABELS):
        if match := _DRIVER.search(value):
            return int(match[1])
    if match := _TITLE_DRIVER.search(folded_title):
        return int(match[1] or match[2])
    return None


def extract_headset(title: str, raw_specs: Mapping[str, str]) -> HeadsetSpecs:
    """Thông số tai nghe đọc được từ tiêu đề và bảng thông số thô.

    `form` và `connection` chỉ được điền khi viết rõ ("TWS", "earbuds", "chụp tai", "USB", "3.5mm",
    "2.4G", "Bluetooth"); "không dây" trơn không đủ để nói 2.4G hay Bluetooth, và tên mẫu trơn
    như "HyperX Cloud III" cũng không đủ căn cứ nên để trống.
    """
    title = clean(title)
    folded = fold(title)
    labelled = list(label_values(raw_specs, _CONNECTION_LABELS))
    form = _form(folded)
    return build_specs(
        HeadsetSpecs,
        {
            "form": form,
            "connection": _connection(" ".join([title, *labelled]), form),
            "has_mic": _has_mic(folded, raw_specs),
            "anc": True if affirmed(_ANC, folded) else None,
            "surround_7_1": True if _SURROUND.search(folded) else None,
            "driver_mm": _driver_mm(folded, raw_specs),
        },
    )
