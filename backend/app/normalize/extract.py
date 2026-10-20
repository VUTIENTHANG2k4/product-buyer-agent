"""Điểm vào của bộ trích xuất thông số theo luật (docs/04 §5, §7).

`extract_specs` đọc tiêu đề + bảng thông số thô của một offer và trả thông số, danh sách trường
bắt buộc còn thiếu và độ tin cậy. Danh sách `missing` là chỗ cắm cho bộ LLM dự phòng (T5.3).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel

from app.domain.enums import Category
from app.normalize.specs import REQUIRED_FIELDS, SPEC_MODELS
from app.normalize.specs.headset import extract_headset
from app.normalize.specs.keyboard import extract_keyboard
from app.normalize.specs.laptop import extract_laptop
from app.normalize.specs.mouse import extract_mouse

Extractor = Callable[[str, Mapping[str, str]], BaseModel]

# Nhóm chưa có bộ trích xuất (điện thoại là pha mở rộng X1, `other` không có khung) → specs rỗng.
_EXTRACTORS: Final[Mapping[Category, Extractor]] = MappingProxyType(
    {
        Category.laptop: extract_laptop,
        Category.mouse: extract_mouse,
        Category.keyboard: extract_keyboard,
        Category.headset: extract_headset,
    }
)

# Thiếu trường bắt buộc thì độ tin cậy luôn dưới 0,5 (docs/04 §5: chỉ xuất hiện khi lọc không dùng
# trường đó); đủ thì 1,0.
INCOMPLETE_CEILING: Final = 0.49


@dataclass(frozen=True)
class SpecsExtraction:
    """Kết quả trích xuất cho một offer.

    `specs` là dict JSON (không có khóa `None`, có `gpu_rank` của laptop) đúng như lưu vào
    `product.specs`; `missing` là các trường bắt buộc chưa có (theo `REQUIRED_FIELDS`).
    """

    specs: dict[str, Any]
    missing: tuple[str, ...]
    confidence: float


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, list) and not value)


def missing_required(category: Category, specs: Mapping[str, Any]) -> tuple[str, ...]:
    """Trường bắt buộc của `category` mà `specs` chưa có (None hoặc list rỗng là thiếu)."""
    return tuple(name for name in REQUIRED_FIELDS.get(category, ()) if _is_missing(specs.get(name)))


def specs_confidence(category: Category, specs: Mapping[str, Any]) -> float:
    """1,0 khi đủ trường bắt buộc; thiếu thì `0,49 × (số trường có / tổng)`."""
    required = REQUIRED_FIELDS.get(category, ())
    if not required:
        return 0.0
    missing = len(missing_required(category, specs))
    if missing == 0:
        return 1.0
    return round(INCOMPLETE_CEILING * (len(required) - missing) / len(required), 2)


def extract_specs(
    category: Category, title: str, raw_specs: Mapping[str, str] | None = None
) -> SpecsExtraction:
    """Trích thông số theo luật. Nhóm chưa hỗ trợ trả `specs` rỗng, `confidence` 0,0."""
    extractor = _EXTRACTORS.get(category)
    if extractor is None:
        return SpecsExtraction(specs={}, missing=(), confidence=0.0)
    specs = extractor(title, raw_specs or {}).model_dump(mode="json", exclude_none=True)
    return SpecsExtraction(
        specs=specs,
        missing=missing_required(category, specs),
        confidence=specs_confidence(category, specs),
    )


def merge_specs(
    category: Category, existing: Mapping[str, Any], new: Mapping[str, Any]
) -> dict[str, Any]:
    """Gộp `new` vào `existing`: chỉ điền trường còn thiếu, giá trị đã có không bị ghi đè.

    Kết quả đi qua khung của `category` nên `gpu_rank` được tính lại từ `gpu_model` cuối cùng.
    """
    merged = {name: value for name, value in new.items() if not _is_missing(value)}
    merged.update({name: value for name, value in existing.items() if not _is_missing(value)})
    model = SPEC_MODELS.get(category)
    if model is None:
        return merged
    return model.model_validate(merged).model_dump(mode="json", exclude_none=True)
