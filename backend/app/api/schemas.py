"""Schema phản hồi chung của API (docs/07)."""

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, Self, TypeVar

from pydantic import BaseModel, Field, StrictInt, model_validator

from app.agent.schemas import ErrorEvent, FinalEvent
from app.domain.admin import ScrapeRunView, SourceView
from app.domain.catalog import AlertView, CategoryInfo, ProductSummary, ShoppingListSummary
from app.domain.chat import ConversationView, MessageView
from app.domain.dto import QueryIntent
from app.domain.enums import AgentRunStatus, Category, SiteKey


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

    product_ids: list[StrictInt] = Field(min_length=2, max_length=5)


class CategoriesResponse(BaseModel):
    items: list[CategoryInfo]


class ItemsResponse(BaseModel, Generic[T]):
    """Danh sách không phân trang: `{items: [...]}`."""

    items: list[T]


class ListsResponse(ItemsResponse[ShoppingListSummary]):
    """GET /lists."""


class AlertsResponse(ItemsResponse[AlertView]):
    """GET /alerts."""


class ListBody(BaseModel):
    """POST /lists và PATCH /lists/{id}: tên 1–100 ký tự sau khi chuẩn hóa (service kiểm)."""

    name: str = Field(max_length=1000)


class ItemCreate(BaseModel):
    """POST /lists/{id}/items. Sản phẩm đã có trong danh sách thì cộng dồn `quantity`."""

    product_id: StrictInt
    quantity: StrictInt = 1
    note: str | None = Field(default=None, max_length=1000)
    preferred_offer_id: StrictInt | None = None


class ItemPatch(BaseModel):
    """PATCH /lists/{id}/items/{item_id}. Trường bỏ vắng giữ nguyên; `null` ở `note` hoặc
    `preferred_offer_id` xóa giá trị đó."""

    quantity: StrictInt | None = None
    note: str | None = Field(default=None, max_length=1000)
    preferred_offer_id: StrictInt | None = None

    @model_validator(mode="after")
    def _quantity_is_not_null(self) -> Self:
        if "quantity" in self.model_fields_set and self.quantity is None:
            raise ValueError("quantity must be a number when present")
        return self


class AlertPatch(BaseModel):
    """PATCH /alerts/{id}: đổi ngưỡng và/hoặc tạm dừng/bật lại (`triggered` do hệ thống đặt)."""

    target_price: StrictInt | None = None
    status: Literal["active", "paused"] | None = None


class AlertTestResponse(BaseModel):
    """POST /alerts/{id}/test."""

    sent: bool
    reason: str | None = None


class SourcesResponse(ItemsResponse[SourceView]):
    """GET /admin/sources."""


class ScrapeRunPage(Page[ScrapeRunView]):
    """GET /admin/scrape-runs."""


class ScrapeRunCreate(BaseModel):
    """POST /admin/scrape-runs. `max_pages` bỏ trống thì theo `SCRAPER_MAX_LISTING_PAGES`."""

    site: SiteKey
    category: Category
    max_pages: StrictInt | None = Field(default=None, ge=1, le=100)


class ChallengeAnswer(BaseModel):
    """POST /admin/scrape-runs/{id}/challenge: đáp án captcha của mock-shop."""

    answer: str = Field(min_length=1, max_length=200, pattern=r"^[^\x00]+$")


class ChatRequest(BaseModel):
    """POST /chat. `conversation_id` bỏ trống thì tạo hội thoại mới."""

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: StrictInt | None = None


class ChatAccepted(BaseModel):
    run_id: uuid.UUID
    conversation_id: int


class RunStatusResponse(BaseModel):
    """GET /chat/{run_id}: trạng thái và kết quả cuối (cùng nội dung với sự kiện SSE tương ứng)."""

    run_id: uuid.UUID
    conversation_id: int
    status: AgentRunStatus
    intent: QueryIntent | None
    final: FinalEvent | None = None
    clarification: str | None = None  # câu hỏi lại khi `status = needs_clarification`
    error: ErrorEvent | None = None


class ConversationsResponse(ItemsResponse[ConversationView]):
    """GET /conversations."""


class MessagesResponse(ItemsResponse[MessageView]):
    """GET /conversations/{id}/messages."""
