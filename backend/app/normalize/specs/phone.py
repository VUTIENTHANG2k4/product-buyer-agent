"""Khung thông số điện thoại, pha mở rộng X1 (docs/04 §5.5).

Mỗi biến thể dung lượng là một `Product` riêng nên `ram_gb`/`storage_gb` là số đơn.
"""

from typing import Final

from pydantic import BaseModel

from app.domain.dto import NonEmptyStr
from app.normalize.specs.types import PositiveFloat, PositiveInt

REQUIRED_FIELDS: Final = ("ram_gb", "storage_gb")


class PhoneSpecs(BaseModel):
    chipset: NonEmptyStr | None = None
    ram_gb: PositiveInt | None = None
    storage_gb: PositiveInt | None = None
    screen_in: PositiveFloat | None = None
    battery_mah: PositiveInt | None = None
    os: NonEmptyStr | None = None
