"""Schema phản hồi chung của API (docs/07)."""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.domain.catalog import CategoryInfo, ProductSummary


class HealthResponse(BaseModel):
    """GET /api/health. `status` là "degraded" khi CSDL không kết nối được."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    llm_provider: str
    offline_mode: bool
    version: str


class ErrorDetail(BaseModel):
    """Nội dung lỗi (docs/07 §1–2). `details` luôn là object, có thể rỗng."""

    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    """Thân của mọi phản hồi lỗi 4xx/5xx."""

    error: ErrorDetail


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Phân trang chuẩn (docs/07 §1): `?page=1&page_size=20`, tối đa 100."""

    items: list[T]
    total: int
    page: int
    page_size: int


class ProductListResponse(Page[ProductSummary]):
    """GET /products. `stale` khi dữ liệu cũ hơn 24 giờ; `data_as_of` là mốc thu thập cũ nhất."""

    stale: bool
    data_as_of: datetime | None


class CompareRequest(BaseModel):
    """POST /compare: 2–5 sản phẩm. Id không tồn tại (kể cả ngoài miền) → `PRODUCT_NOT_FOUND`."""

    product_ids: list[int] = Field(min_length=2, max_length=5)


class CategoriesResponse(BaseModel):
    items: list[CategoryInfo]
