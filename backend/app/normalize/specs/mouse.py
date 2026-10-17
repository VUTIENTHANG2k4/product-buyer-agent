"""Khung thông số chuột (docs/04 §5.2)."""

from typing import Final

from pydantic import BaseModel

from app.domain.dto import NonEmptyStr
from app.normalize.specs.types import MouseShape, PeripheralConnection, PositiveInt

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
