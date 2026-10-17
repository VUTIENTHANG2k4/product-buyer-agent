"""Khung thông số bàn phím (docs/04 §5.3)."""

from typing import Final

from pydantic import BaseModel

from app.domain.dto import NonEmptyStr
from app.normalize.specs.types import Backlight, FormFactor, PeripheralConnection, SwitchType

# Danh sách rỗng (connection) coi như thiếu.
REQUIRED_FIELDS: Final = ("connection", "switch_type")


class KeyboardSpecs(BaseModel):
    connection: list[PeripheralConnection] | None = None
    switch_type: SwitchType | None = None
    switch_name: NonEmptyStr | None = None
    form_factor: FormFactor | None = None
    hot_swap: bool | None = None
    backlight: Backlight | None = None
