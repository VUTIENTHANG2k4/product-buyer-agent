"""Kiểu dùng chung của các khung thông số (docs/04 §5).

Giá trị chuỗi của enum là hợp đồng lưu trữ (JSONB trong `product.specs`): không đổi tên mà không
có migration dữ liệu. Tên member không bắt đầu bằng số nên `75` → `ff_75`.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

# Strict như DTO (docs/04 §6): extractor phải đưa về `int` trước, không nhận bool/chuỗi/float.
Count = Annotated[int, Field(ge=0, strict=True)]  # 0 hợp lệ (ví dụ VRAM của GPU tích hợp)
# Số đo vật lý/dung lượng: 0 vô nghĩa, parser đọc hỏng phải trả None chứ không phải 0.
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]


class CpuVendor(StrEnum):
    intel = "intel"
    amd = "amd"
    apple = "apple"
    qualcomm = "qualcomm"


class StorageType(StrEnum):
    ssd = "ssd"
    hdd = "hdd"


class PeripheralConnection(StrEnum):
    """Kết nối của chuột và bàn phím."""

    wired = "wired"
    wireless_2_4 = "wireless_2_4"
    bluetooth = "bluetooth"


class MouseShape(StrEnum):
    ergo_right = "ergo_right"
    ambidextrous = "ambidextrous"


class SwitchType(StrEnum):
    mechanical = "mechanical"
    membrane = "membrane"
    optical = "optical"
    magnetic = "magnetic"


class FormFactor(StrEnum):
    full = "full"
    tkl = "tkl"
    ff_75 = "75"
    ff_65 = "65"
    ff_60 = "60"
    other = "other"


class Backlight(StrEnum):
    none = "none"
    single = "single"
    rgb = "rgb"


class HeadsetForm(StrEnum):
    over_ear = "over_ear"
    on_ear = "on_ear"
    in_ear = "in_ear"
    tws = "tws"


class HeadsetConnection(StrEnum):
    wired_3_5 = "wired_3_5"
    usb = "usb"
    wireless_2_4 = "wireless_2_4"
    bluetooth = "bluetooth"
