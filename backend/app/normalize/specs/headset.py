"""Khung thông số tai nghe (docs/04 §5.4)."""

from typing import Final

from pydantic import BaseModel

from app.normalize.specs.types import HeadsetConnection, HeadsetForm, PositiveInt

# Danh sách rỗng (connection) coi như thiếu.
REQUIRED_FIELDS: Final = ("form", "connection")


class HeadsetSpecs(BaseModel):
    form: HeadsetForm | None = None
    connection: list[HeadsetConnection] | None = None
    has_mic: bool | None = None
    anc: bool | None = None
    surround_7_1: bool | None = None
    driver_mm: PositiveInt | None = None
