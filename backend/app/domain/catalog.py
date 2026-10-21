"""DTO của lớp service: danh mục, so sánh, danh sách mua, cảnh báo giá (docs/05 §3, docs/07 §3).

Tiền là `int` VND, thời gian UTC. Đây là dữ liệu đi qua ranh giới service → tool/API; agent và
API không dùng model của `app.db`.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.dto import NonEmptyStr, SpecFilter, Vnd
from app.domain.enums import (
    AlertChannel,
    AlertStatus,
    Category,
    PriceType,
    SiteKey,
    StockStatus,
)

CatalogSort = Literal["relevance", "price_asc", "price_desc", "rating_desc"]
MAX_QUANTITY = 2_147_483_647  # cột `quantity` là INT32


class OfferView(BaseModel):
    """Một offer đang bán. `effective_price` là giá dùng để so sánh (docs/04 §4)."""

    offer_id: int
    site: SiteKey
    title: str
    url: str
    price: Vnd
    list_price: Vnd | None = None
    effective_price: Vnd
    price_type: PriceType
    stock_status: StockStatus
    rating: float | None = None
    scraped_at: datetime


class ProductSummary(BaseModel):
    """Một dòng kết quả tìm kiếm (docs/05 §3)."""

    product_id: int
    name: str
    brand: str
    category: Category
    key_specs: dict[str, Any] = Field(default_factory=dict)  # tối đa 6 trường
    min_price: Vnd
    max_price: Vnd
    best_offer: OfferView
    offers_count: int
    in_stock: bool
    image_url: str | None = None


class RowOffer(BaseModel):
    """Một offer trong dòng bảng kết quả (docs/07 §3.2)."""

    site: SiteKey
    price: Vnd  # giá hiệu lực
    price_type: PriceType
    stock_status: StockStatus
    url: str
    scraped_at: datetime


class ProductRow(BaseModel):
    """Dòng của bảng kết quả, dựng từ CSDL theo `product_id` (không từ số LLM viết)."""

    product_id: int
    name: str
    brand: str
    category: Category
    key_specs: dict[str, Any] = Field(default_factory=dict)
    min_price: Vnd | None = None
    offers: list[RowOffer] = Field(default_factory=list)
    image_url: str | None = None


class ProductFull(BaseModel):
    """Sản phẩm với toàn bộ thông số và mọi offer đang bán (rẻ nhất trước)."""

    product_id: int
    name: str
    brand: str
    category: Category
    model_code: str | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    specs_confidence: float
    image_url: str | None = None
    offers: list[OfferView] = Field(default_factory=list)
    min_price: Vnd | None = None
    max_price: Vnd | None = None


class CatalogFilters(BaseModel):
    """Điều kiện tìm sản phẩm trong danh mục đã thu thập (không gọi mạng)."""

    category: Category | None = None
    q: str | None = Field(default=None, max_length=200)
    price_min: Vnd | None = None
    price_max: Vnd | None = None
    brands: list[str] = Field(default_factory=list)
    sites: list[SiteKey] = Field(default_factory=list)
    spec_filters: list[SpecFilter] = Field(default_factory=list)
    sort: CatalogSort = "relevance"
    limit: int = Field(default=10, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, le=1_000_000, strict=True)
    include_out_of_stock: bool = False


class CatalogSearchResult(BaseModel):
    """Kết quả tìm kiếm.

    `data_as_of` là thời điểm thu thập CŨ NHẤT trong số offer tốt nhất đang hiển thị; `stale` khi
    nó cách hiện tại hơn 24 giờ.
    """

    total: int
    items: list[ProductSummary]
    stale: bool
    data_as_of: datetime | None
    applied_filters: dict[str, Any]


class PricePointView(BaseModel):
    t: datetime
    price: Vnd
    price_type: PriceType


class SiteSeries(BaseModel):
    site: SiteKey
    points: list[PricePointView]


class PriceHistoryResult(BaseModel):
    series: list[SiteSeries]
    min_price: Vnd | None
    max_price: Vnd | None


class Comparison(BaseModel):
    products: list[ProductFull]
    differing_fields: list[str]
    cheapest_product_id: int | None


class ShoppingListItemView(BaseModel):
    item_id: int
    product_id: int
    name: str
    quantity: int
    note: str | None
    preferred_offer_id: int | None
    price_at_add: Vnd | None
    current_price: Vnd | None  # None: không còn offer đang bán
    price_delta: int | None  # current_price - price_at_add (âm = rẻ hơn lúc thêm)
    best_offer: OfferView | None


class ShoppingListSummary(BaseModel):
    list_id: int
    name: str
    item_count: int
    total_price: Vnd  # Σ quantity × giá hiện tại (mục không còn bán bị bỏ qua)
    updated_at: datetime


class ShoppingListDetail(ShoppingListSummary):
    items: list[ShoppingListItemView]


class AlertView(BaseModel):
    alert_id: int
    product_id: int
    product_name: str
    target_price: Vnd
    channel: AlertChannel
    destination: str
    status: AlertStatus
    current_best_price: Vnd | None
    last_notified_price: Vnd | None
    last_notified_at: datetime | None
    created_at: datetime


class AlertCreate(BaseModel):
    """Yêu cầu tạo cảnh báo; thiếu kênh/nơi nhận thì lấy mặc định từ cấu hình."""

    product_id: int
    target_price: int = Field(gt=0, le=2**63 - 1, strict=True)
    channel: AlertChannel | None = None
    destination: NonEmptyStr | None = None
