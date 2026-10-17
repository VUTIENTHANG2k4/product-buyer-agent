"""Khung thông số theo nhóm sản phẩm (docs/04 §5)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel

from app.domain.enums import Category
from app.normalize.specs import headset, keyboard, laptop, mouse, phone
from app.normalize.specs.gpu_rank import GPU_RANKS, gpu_rank, normalize_gpu_name
from app.normalize.specs.headset import HeadsetSpecs
from app.normalize.specs.keyboard import KeyboardSpecs
from app.normalize.specs.laptop import LaptopSpecs
from app.normalize.specs.mouse import MouseSpecs
from app.normalize.specs.phone import PhoneSpecs

# Nhóm `other` (tầng 2) không có khung thông số.
SPEC_MODELS: Final[Mapping[Category, type[BaseModel]]] = MappingProxyType(
    {
        Category.laptop: LaptopSpecs,
        Category.mouse: MouseSpecs,
        Category.keyboard: KeyboardSpecs,
        Category.headset: HeadsetSpecs,
        Category.phone: PhoneSpecs,
    }
)

# Trường cần có để sản phẩm dùng được trong lọc tầng 1 (None hoặc list rỗng = thiếu).
REQUIRED_FIELDS: Final[Mapping[Category, tuple[str, ...]]] = MappingProxyType(
    {
        Category.laptop: laptop.REQUIRED_FIELDS,
        Category.mouse: mouse.REQUIRED_FIELDS,
        Category.keyboard: keyboard.REQUIRED_FIELDS,
        Category.headset: headset.REQUIRED_FIELDS,
        Category.phone: phone.REQUIRED_FIELDS,
    }
)

__all__ = [
    "GPU_RANKS",
    "REQUIRED_FIELDS",
    "SPEC_MODELS",
    "HeadsetSpecs",
    "KeyboardSpecs",
    "LaptopSpecs",
    "MouseSpecs",
    "PhoneSpecs",
    "gpu_rank",
    "normalize_gpu_name",
]
