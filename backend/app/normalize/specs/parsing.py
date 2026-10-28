"""Hàm đọc giá trị thông số từ tiêu đề và bảng thông số thô (docs/04 §7).

Mọi hàm là hàm thuần. Không suy đoán: không đọc được thì trả `None` (hoặc danh sách rỗng).
Nhãn của bảng thông số được so khớp sau `fold` (không dấu, chữ thường) theo kiểu "chứa bí danh".
"""

import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.normalize.specs.types import PeripheralConnection
from app.normalize.text import fold

M = TypeVar("M", bound=BaseModel)

_NUMBER = r"(\d+(?:[.,]\d+)?)"
_CAPACITY = re.compile(r"(?<![\w.,])(\d{1,4})\s?(tb|gb)\b", re.IGNORECASE)
_INCHES = re.compile(
    r"(?<![\w.])(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:\"|”|″|''|-?\s*inch\b|-?\s*in\b)", re.IGNORECASE
)
_HERTZ = re.compile(r"(?<![\w.])(\d{2,3})\s?hz\b", re.IGNORECASE)
_MASS = re.compile(rf"(?<![\w.]){_NUMBER}\s?(kg|g)\b", re.IGNORECASE)

MAX_TEXT_LENGTH = 2000  # chuỗi dài hơn là rác (hoặc tấn công): cắt trước khi chạy regex


# Chỉ chuẩn hóa phần đầu: chuỗi dài hơn nhiều lần giới hạn là rác mà `clean` gọi rất nhiều lần.
_MAX_RAW_LENGTH = 4 * MAX_TEXT_LENGTH
_MARKS = str.maketrans("", "", "™®©℠")


def clean(text: str) -> str:
    """Chuẩn hóa NFKC (NFC, chữ toàn chiều rộng), bỏ ký tự điều khiển, gộp khoảng trắng."""
    text = text[:_MAX_RAW_LENGTH].translate(
        _MARKS
    )  # NFKC đổi "™" thành "TM" dính vào từ ("Ryzen™" -> "RyzenTM")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if c.isspace() or unicodedata.category(c) not in {"Cc", "Cf"})
    return " ".join(text.split())[:MAX_TEXT_LENGTH]


# Nhãn nói về giới hạn nâng cấp chứ không phải giá trị hiện có ("Nâng cấp RAM: tối đa 64GB").
_LIMIT_LABEL = re.compile(r"toi da|nang cap")


def _is_limit_label(label: str) -> bool:
    return _LIMIT_LABEL.search(label) is not None


def label_values(raw_specs: Mapping[str, str], aliases: Sequence[str]) -> Iterator[str]:
    """Giá trị của các nhãn chứa bí danh, theo thứ tự ưu tiên của `aliases`.

    `aliases` đã viết dạng `fold` (không dấu, chữ thường). Giá trị rỗng bị bỏ qua.
    """
    folded = [(fold(label), clean(value)) for label, value in raw_specs.items()]
    yielded: set[int] = set()  # mỗi nhãn chỉ trả một lần dù khớp nhiều bí danh
    for alias in aliases:
        for index, (label, value) in enumerate(folded):
            if value and alias in label and index not in yielded and not _is_limit_label(label):
                yielded.add(index)
                yield value


def capacities_gb(text: str) -> list[int]:
    """Mọi dung lượng `<số> GB|TB` trong chuỗi, đổi ra GB (1 TB = 1000 GB), theo thứ tự."""
    found: list[int] = []
    for match in _CAPACITY.finditer(text):
        value = int(match[1])
        found.append(value * 1000 if match[2].lower() == "tb" else value)
    return found


def first_capacity_gb(text: str) -> int | None:
    values = capacities_gb(text)
    return values[0] if values else None


def _to_float(number: str) -> float:
    return float(number.replace(",", "."))


def parse_inches(text: str) -> float | None:
    """Kích thước màn hình theo inch (`15.6"`, `15.6 inch`, `16-inch`)."""
    match = _INCHES.search(text)
    return _to_float(match[1]) if match else None


def parse_hertz(text: str) -> int | None:
    match = _HERTZ.search(text)
    return int(match[1]) if match else None


def parse_grams(text: str) -> int | None:
    """Khối lượng `59 g` / `0.06 kg` đổi ra gam (làm tròn)."""
    match = _MASS.search(text)
    if match is None:
        return None
    value = _to_float(match[1])
    grams = value * 1000 if match[2].lower() == "kg" else value
    return round(grams) if grams > 0 else None


def parse_grams_all(text: str) -> list[int]:
    """Mọi khối lượng gam trong `text` theo thứ tự xuất hiện ("2.4G" đứng trước "99g" cũng đọc
    được cả hai, nơi gọi chọn giá trị hợp lý)."""
    grams: list[int] = []
    for match in _MASS.finditer(text):
        value = _to_float(match[1])
        mass = value * 1000 if match[2].lower() == "kg" else value
        if mass > 0:
            grams.append(round(mass))
    return grams


def parse_kilograms(text: str) -> float | None:
    """Khối lượng `2.29 kg` / `975 g` đổi ra kg (3 chữ số thập phân)."""
    match = _MASS.search(text)
    if match is None:
        return None
    value = _to_float(match[1])
    kilograms = value if match[2].lower() == "kg" else value / 1000
    return round(kilograms, 3) if kilograms > 0 else None


def has_word(text: str, *words: str) -> bool:
    """Có từ nào trong `words` xuất hiện như một từ riêng (không dính vào chữ/số khác)."""
    return any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) for word in words)


@dataclass(frozen=True)
class Connectivity:
    """Các kiểu kết nối nhắc tới trong một chuỗi (chỉ những gì được viết rõ)."""

    wired: bool = False
    radio: bool = False  # 2.4 GHz / dongle / Lightspeed… (hoặc "không dây" chung chung)
    explicit_radio: bool = False  # radio nhưng chỉ tính khi có chữ 2.4G/dongle/Lightspeed…
    bluetooth: bool = False
    jack: bool = False  # 3.5 mm
    usb: bool = False  # cáp USB (không tính "USB receiver")


_MULTI_MODE = re.compile(r"\b(?:3|ba|tri|triple)[\s-]?(?:mode|che do)\b|\btri[\s-]?mode\b")
_RADIO = re.compile(
    r"2[.,]?4\s?g(?:hz)?\b|lightspeed|hyperspeed|slipstream|logi\s?bolt|\bbolt\b|receiver|dongle"
    r"|bo thu\b|\brf\b"
)
_GENERIC_WIRELESS = re.compile(r"\bkhong day\b|\bwireless\b")
_WIRELESS_PAIRED_BT = re.compile(r"wireless\s*[/&,+-]\s*bluetooth|bluetooth\s*[/&,+-]\s*wireless")
_BLUETOOTH = re.compile(r"bluetooth|\bbt\s?5|\bbt\b")
_WIRED = re.compile(r"\bco day\b|\bwired\b|\bday usb\b")
# Phủ định (đã fold): "không có dây" nghĩa là không dây; "không Bluetooth", "no 2.4G" bỏ tính năng.
_NO_CABLE = re.compile(r"\bkhong co day\b")
# Từ phủ định viết tắt/nối: "không", "ko", "k", "chưa", "no", "non-", "w/o", "without"; theo sau có
# thể là từ đệm ("không hỗ trợ/tích hợp/có …").
_NEGATION = (
    r"\b(?:khong|chua|ko|k|no|non|without|w/o)[\s-]+(?:(?:co|ho tro|tich hop|trang bi|cong)[\s-]+)*"
)
_NEGATED_FEATURE = re.compile(
    _NEGATION + r"(?:bluetooth|bt|usb|jack(?:\s*3[.,]5\s?mm)?|aux|3[.,]5\s?mm"
    r"|2[.,]?4\s?g(?:hz)?|lightspeed|hyperspeed|dongle|receiver|rf)\b"
)
_NEGATION_BEFORE = re.compile(_NEGATION + "$")
_NEGATED_LABEL = re.compile(r"^(?:khong|chua|ko|k|no)(?:[\s,.;-]|$)")
_NEGATION_WINDOW = 32


def affirmed(pattern: re.Pattern[str], text: str) -> bool:
    """`pattern` khớp trong `text` (đã fold) ở ít nhất một chỗ không bị phủ định ngay trước nó
    ("có mic" khớp, "không có mic"/"không ANC" thì không)."""
    for match in pattern.finditer(text):
        start = max(0, match.start() - _NEGATION_WINDOW)
        if _NEGATION_BEFORE.search(text[start : match.start()]) is None:
            return True
    return False


def negated_label(value: str) -> bool:
    """Giá trị nhãn (đã fold) là một lời phủ định: "không", "no", "ko có" (không phải "noise")."""
    return _NEGATED_LABEL.match(value) is not None


_JACK = re.compile(r"3[.,]5\s?mm|\bjack\b|\baux\b")
_USB_RECEIVER = re.compile(r"usb[\s-]*(?:c\s*)?(?:receiver|dongle)")
_USB = re.compile(r"\busb\b")


def read_connectivity(text: str) -> Connectivity:
    """Kiểu kết nối được nhắc tới trong `text` (đã `fold`).

    "Không dây"/"wireless" chung chung tính là 2.4 GHz, trừ khi chuỗi chỉ nhắc Bluetooth (lúc đó
    "không dây" chính là Bluetooth). "3 mode" là có dây + 2.4 GHz + Bluetooth.
    """
    text = _NEGATED_FEATURE.sub(" ", _NO_CABLE.sub("khong day", text))
    if _MULTI_MODE.search(text):
        return Connectivity(wired=True, radio=True, explicit_radio=True, bluetooth=True, usb=True)
    bluetooth = _BLUETOOTH.search(text) is not None
    generic = _GENERIC_WIRELESS.search(text) is not None
    explicit_radio = _RADIO.search(text) is not None
    radio = explicit_radio or (
        generic and (not bluetooth or _WIRELESS_PAIRED_BT.search(text) is not None)
    )
    cable = _USB_RECEIVER.sub(" ", text)
    return Connectivity(
        wired=_WIRED.search(text) is not None,
        radio=radio,
        explicit_radio=explicit_radio,
        bluetooth=bluetooth,
        jack=_JACK.search(text) is not None,
        usb=_USB.search(cable) is not None,
    )


def peripheral_connection(*texts: str) -> list[PeripheralConnection] | None:
    """Kết nối của chuột/bàn phím đọc được từ các chuỗi; `None` nếu không viết rõ."""
    found = read_connectivity(fold(" ".join(texts)))
    connection = [
        kind
        for kind, present in (
            (PeripheralConnection.wired, found.wired),
            (PeripheralConnection.wireless_2_4, found.radio),
            (PeripheralConnection.bluetooth, found.bluetooth),
        )
        if present
    ]
    return connection or None


def build_specs(model: type[M], fields: Mapping[str, Any]) -> M:
    """Dựng khung thông số từ các trường đọc được; trường nào sai kiểu/miền thì bỏ riêng trường đó.

    Nhờ vậy một giá trị hỏng (ví dụ số âm do đọc nhầm) không làm mất cả bộ thông số.
    """
    pending = {name: value for name, value in fields.items() if value is not None}
    for _ in range(len(pending) + 1):
        try:
            return model.model_validate(pending)
        except ValidationError as error:
            bad = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
            if not bad & pending.keys():
                break
            pending = {name: value for name, value in pending.items() if name not in bad}
    return model.model_validate({})
