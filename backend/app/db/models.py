"""Model SQLModel cho 12 bảng của ERD (docs/04 §2–3, ADR-0007).

Quy ước lưu trữ (PostgreSQL):
- Tiền là `BIGINT` + `CHECK >= 0`; thời gian là `TIMESTAMP WITH TIME ZONE`, lưu UTC.
- Enum lưu `VARCHAR(32)` + `CHECK` có tên (không dùng kiểu ENUM gốc). Alembic autogenerate **không**
  so sánh CHECK: thêm giá trị enum phải viết migration tay (xóa rồi tạo lại ràng buộc).
- Cột JSON là `JSONB`; SQLAlchemy không theo dõi thay đổi tại chỗ, nên repository phải gán lại cả
  dict/list thay vì sửa từng khóa.
- Không dùng `Relationship`: repository truy vấn tường minh.

Module này chỉ import `app.domain` (db không import gì khác ngoài domain, config).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.domain.enums import (
    AgentRunStatus,
    AlertChannel,
    AlertStatus,
    Category,
    MatchMethod,
    MessageRole,
    PriceType,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)

# Tên ràng buộc ổn định để migration và test tham chiếu được. `ck` cần `name=` trên từng CHECK.
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Thời điểm hiện tại theo UTC (có timezone); test thay bằng đồng hồ giả (time-machine)."""
    return datetime.now(UTC)


def _enum_column(enum_cls: type[StrEnum], name: str) -> Column[Any]:
    """Cột `VARCHAR(32)`; Python nhận lại member của enum. CHECK khai báo riêng bằng `_enum_check`.

    Không dùng `create_constraint=True` của SQLAlchemy: autogenerate sẽ sinh trùng ràng buộc.
    """
    return Column(
        Enum(
            enum_cls,
            name=name,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )


def _enum_check(column: str, enum_cls: type[StrEnum]) -> CheckConstraint:
    """`CHECK (<column> IN (...))` tên `ck_<bảng>_<column>`; đổi enum thì viết migration tay."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=column)


def _timestamp(*, nullable: bool = False, onupdate: bool = False) -> Any:
    """Cột `TIMESTAMP WITH TIME ZONE`; không nullable thì mặc định `utc_now()` (và `now()` ở DB)."""
    column: Column[Any] = Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else func.now(),
        onupdate=utc_now if onupdate else None,
    )
    if nullable:
        return Field(default=None, sa_column=column)
    return Field(default_factory=utc_now, sa_column=column)


def _jsonb_object() -> Any:
    return Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )


def _jsonb_array() -> Any:
    return Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )


def _jsonb_nullable() -> Any:
    # none_as_null: Python None là SQL NULL, không phải JSON `null`.
    return Field(default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True))


class Product(SQLModel, table=True):
    """Một mẫu sản phẩm chuẩn hóa; giá và link nằm ở `Offer`."""

    __tablename__ = "product"
    __table_args__ = (
        _enum_check("category", Category),
        CheckConstraint("specs_confidence >= 0 AND specs_confidence <= 1", name="specs_confidence"),
        Index("ix_product_category", "category"),
        Index("ix_product_specs_gin", "specs", postgresql_using="gin"),
        Index(
            "uq_product_category_brand_model_code",
            "category",
            "brand",
            "model_code",
            unique=True,
            postgresql_where=text("model_code IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    category: Category = Field(sa_column=_enum_column(Category, "category"))
    brand: str
    model_code: str | None = None
    canonical_name: str
    specs: dict[str, Any] = _jsonb_object()
    specs_confidence: float = 1.0
    image_url: str | None = None
    created_at: datetime = _timestamp()
    updated_at: datetime = _timestamp(onupdate=True)


class Offer(SQLModel, table=True):
    """Một trang rao bán `Product` với giá và link riêng; `url` đã `clean_url` là khóa tự nhiên."""

    __tablename__ = "offer"
    __table_args__ = (
        _enum_check("site", SiteKey),
        _enum_check("price_type", PriceType),
        _enum_check("stock_status", StockStatus),
        _enum_check("match_method", MatchMethod),
        UniqueConstraint("url", name="uq_offer_url"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("list_price IS NULL OR list_price >= 0", name="list_price_non_negative"),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="rating_range"),
        CheckConstraint("rating_count IS NULL OR rating_count >= 0", name="rating_count"),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)", name="match_score"
        ),
        Index("ix_offer_product_id", "product_id"),
        Index("ix_offer_site_is_active", "site", "is_active"),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")  # không cascade: chặn xóa product còn offer
    site: SiteKey = Field(sa_column=_enum_column(SiteKey, "site"))
    url: str
    site_sku: str | None = None
    title: str
    price: int = Field(sa_type=BigInteger)  # VND, không NULL: giá không đọc được thì bỏ qua mục
    list_price: int | None = Field(default=None, sa_type=BigInteger)
    price_type: PriceType = Field(
        default=PriceType.unknown, sa_column=_enum_column(PriceType, "price_type")
    )
    stock_status: StockStatus = Field(
        default=StockStatus.unknown, sa_column=_enum_column(StockStatus, "stock_status")
    )
    rating: float | None = None
    rating_count: int | None = None
    raw_specs: dict[str, Any] = _jsonb_object()
    match_method: MatchMethod = Field(
        default=MatchMethod.new, sa_column=_enum_column(MatchMethod, "match_method")
    )
    match_score: float | None = None
    is_active: bool = True
    first_seen_at: datetime = _timestamp()
    scraped_at: datetime = _timestamp()


class PriceHistory(SQLModel, table=True):
    """Lịch sử giá chỉ thêm (append-only); luật thêm dòng ở docs/04 §3."""

    __tablename__ = "price_history"
    __table_args__ = (
        _enum_check("price_type", PriceType),
        _enum_check("stock_status", StockStatus),
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_price_history_offer_id_scraped_at", "offer_id", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    offer_id: int = Field(foreign_key="offer.id", ondelete="CASCADE")
    price: int = Field(sa_type=BigInteger)
    price_type: PriceType = Field(
        default=PriceType.unknown, sa_column=_enum_column(PriceType, "price_type")
    )
    stock_status: StockStatus = Field(
        default=StockStatus.unknown, sa_column=_enum_column(StockStatus, "stock_status")
    )
    scraped_at: datetime = _timestamp()


class ScrapeRun(SQLModel, table=True):
    """Một lượt thu thập của một trang cho một nhóm sản phẩm."""

    __tablename__ = "scrape_run"
    __table_args__ = (
        _enum_check("site", SiteKey),
        _enum_check("category", Category),
        _enum_check("status", ScrapeStatus),
        _enum_check("trigger", ScrapeTrigger),
        CheckConstraint(
            "pages_fetched >= 0 AND items_parsed >= 0 AND items_failed >= 0"
            " AND offers_upserted >= 0 AND price_changes >= 0",
            name="counters_non_negative",
        ),
        Index("ix_scrape_run_site_category_started_at", "site", "category", "started_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    site: SiteKey = Field(sa_column=_enum_column(SiteKey, "site"))
    category: Category = Field(sa_column=_enum_column(Category, "category"))
    status: ScrapeStatus = Field(
        default=ScrapeStatus.PENDING, sa_column=_enum_column(ScrapeStatus, "status")
    )
    trigger: ScrapeTrigger = Field(sa_column=_enum_column(ScrapeTrigger, "trigger"))
    pages_fetched: int = 0
    items_parsed: int = 0
    items_failed: int = 0
    offers_upserted: int = 0
    price_changes: int = 0
    challenge: dict[str, Any] | None = _jsonb_nullable()
    error_message: str | None = Field(default=None, sa_type=Text)
    started_at: datetime = _timestamp()
    finished_at: datetime | None = _timestamp(nullable=True)


class ShoppingList(SQLModel, table=True):
    __tablename__ = "shopping_list"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = _timestamp()
    updated_at: datetime = _timestamp(onupdate=True)


class ShoppingListItem(SQLModel, table=True):
    """Thêm trùng sản phẩm vào cùng danh sách thì tăng `quantity` (UNIQUE list_id, product_id)."""

    __tablename__ = "shopping_list_item"
    __table_args__ = (
        UniqueConstraint("list_id", "product_id", name="uq_shopping_list_item_list_id_product_id"),
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("price_at_add IS NULL OR price_at_add >= 0", name="price_at_add"),
    )

    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="shopping_list.id", ondelete="CASCADE")
    product_id: int = Field(foreign_key="product.id", ondelete="RESTRICT")
    preferred_offer_id: int | None = Field(
        default=None, foreign_key="offer.id", ondelete="SET NULL"
    )
    quantity: int = 1
    price_at_add: int | None = Field(default=None, sa_type=BigInteger)
    note: str | None = None
    added_at: datetime = _timestamp()


class PriceAlert(SQLModel, table=True):
    __tablename__ = "price_alert"
    __table_args__ = (
        _enum_check("channel", AlertChannel),
        _enum_check("status", AlertStatus),
        CheckConstraint("target_price > 0", name="target_price_positive"),
        CheckConstraint(
            "last_notified_price IS NULL OR last_notified_price >= 0", name="last_notified_price"
        ),
        Index("ix_price_alert_product_id_status", "product_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", ondelete="CASCADE")
    target_price: int = Field(sa_type=BigInteger)
    channel: AlertChannel = Field(sa_column=_enum_column(AlertChannel, "channel"))
    destination: str  # email hoặc Telegram chat id
    status: AlertStatus = Field(
        default=AlertStatus.active, sa_column=_enum_column(AlertStatus, "status")
    )
    last_notified_price: int | None = Field(default=None, sa_type=BigInteger)
    last_notified_at: datetime | None = _timestamp(nullable=True)
    created_at: datetime = _timestamp()


class Conversation(SQLModel, table=True):
    __tablename__ = "conversation"

    id: int | None = Field(default=None, primary_key=True)
    title: str | None = None
    created_at: datetime = _timestamp()


class Message(SQLModel, table=True):
    __tablename__ = "message"
    __table_args__ = (
        _enum_check("role", MessageRole),
        Index("ix_message_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id", ondelete="CASCADE")
    role: MessageRole = Field(sa_column=_enum_column(MessageRole, "role"))
    content: str = Field(sa_type=Text)
    payload: dict[str, Any] | None = _jsonb_nullable()
    created_at: datetime = _timestamp()


class AgentRun(SQLModel, table=True):
    """Một lượt chạy agent; `events` lưu toàn bộ sự kiện SSE để xem lại và debug."""

    __tablename__ = "agent_run"
    __table_args__ = (
        _enum_check("status", AgentRunStatus),
        CheckConstraint("tool_calls >= 0", name="tool_calls"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_ms"),
        Index("ix_agent_run_conversation_id", "conversation_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id", ondelete="CASCADE")
    status: AgentRunStatus = Field(
        default=AgentRunStatus.running, sa_column=_enum_column(AgentRunStatus, "status")
    )
    intent: dict[str, Any] | None = _jsonb_nullable()
    events: list[dict[str, Any]] = _jsonb_array()
    tool_calls: int = 0
    latency_ms: int | None = None
    created_at: datetime = _timestamp()


class LlmExtractionCache(SQLModel, table=True):
    """Cache kết quả LLM trích thông số; khóa là SHA-256 của (category, title, raw_specs)."""

    __tablename__ = "llm_extraction_cache"
    __table_args__ = (_enum_check("category", Category),)

    content_hash: str = Field(primary_key=True, max_length=64)
    category: Category = Field(sa_column=_enum_column(Category, "category"))
    result: dict[str, Any] = _jsonb_object()
    model: str
    created_at: datetime = _timestamp()


class LiveSearchCache(SQLModel, table=True):
    """Cache tìm kiếm trực tiếp tầng 2 (TTL 6 giờ tính ở service)."""

    __tablename__ = "live_search_cache"

    cache_key: str = Field(primary_key=True)
    results: list[dict[str, Any]] = _jsonb_array()
    created_at: datetime = _timestamp()


class DomainThrottle(SQLModel, table=True):
    """Mốc sớm nhất được gửi request kế tiếp tới một domain, dùng chung mọi tiến trình (T9.8)."""

    __tablename__ = "domain_throttle"

    domain: str = Field(primary_key=True, max_length=255)
    next_allowed_at: datetime = _timestamp()
