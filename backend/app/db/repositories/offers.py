"""Repository cho `Offer`: upsert theo `url`, tắt offer không còn thấy, giá hiệu lực.

Quy ước chung của mọi repository: nhận `Session` qua `__init__`, chỉ `flush`, không `commit`
(service/pipeline giữ transaction). Thời gian truyền vào qua `now` (UTC), mặc định `utc_now()`.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import ColumnElement, case, column, func, literal_column, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, Product, ShoppingListItem
from app.db.repositories.ids import fits_int4, keep_valid
from app.db.repositories.price_alerts import LIVE_STATUSES
from app.domain.clock import utc_now
from app.domain.dto import FiniteFloat, NonEmptyStr, Vnd
from app.domain.enums import Category, MatchMethod, PriceType, SiteKey, StockStatus

# Chỉ mục btree của UNIQUE (url) từ chối khóa lớn hơn ~2.704 byte (ProgramLimitExceeded).
MAX_URL_BYTES = 2704
MAX_IN_PARAMETERS = 10_000  # PostgreSQL: tối đa 65.535 tham số mỗi câu lệnh


def _contains_nul(value: Any) -> bool:
    """Có ký tự NUL ở bất kỳ chuỗi nào (kể cả khóa) trong cấu trúc lồng nhau không."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_nul(item) for item in value)
    return False


def effective_price() -> ColumnElement[int]:
    """Giá dùng để so sánh (docs/04 §4), tính trong SQL trên bảng `offer`.

    `member` so sánh bằng `list_price` khi có (kèm nhãn giá thành viên ở tầng hiển thị);
    các loại còn lại dùng `price`. Đơn vị VND.
    """
    price, list_price = col(Offer.price), col(Offer.list_price)
    return case(
        (col(Offer.price_type) == PriceType.member, func.coalesce(list_price, price)),
        else_=price,
    )


def effective_price_of(offer: Offer) -> int:
    """Cùng quy tắc với `effective_price()` nhưng tính trên một đối tượng đã nạp (VND)."""
    if offer.price_type is PriceType.member and offer.list_price is not None:
        return offer.list_price
    return offer.price


class OfferUpsert(BaseModel):
    """Giá trị ghi vào một offer. `url` đã qua `clean_url`; giá không đọc được thì không tới đây."""

    model_config = ConfigDict(extra="forbid")

    product_id: int
    site: SiteKey
    url: NonEmptyStr
    title: NonEmptyStr
    price: Vnd
    list_price: Vnd | None = None
    price_type: PriceType = PriceType.unknown
    stock_status: StockStatus = StockStatus.unknown
    site_sku: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0, strict=True)
    raw_specs: dict[str, Any] = Field(default_factory=dict)
    match_method: MatchMethod = MatchMethod.new
    match_score: FiniteFloat | None = Field(default=None, ge=0, le=1)

    @field_validator("url")
    @classmethod
    def _url_fits_unique_index(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_URL_BYTES:
            raise ValueError(f"url is longer than {MAX_URL_BYTES} bytes")
        return value

    @field_validator("url", "title", "site_sku", "raw_specs")
    @classmethod
    def _no_nul_characters(cls, value: Any) -> Any:
        if _contains_nul(value):
            raise ValueError("NUL character is not storable in PostgreSQL text/JSONB")
        return value


class TrackedOffer(NamedTuple):
    """Offer đang được theo dõi và nhóm của sản phẩm (để chọn lượt làm mới giá theo nhóm)."""

    offer_id: int
    category: Category


class UpsertResult(NamedTuple):
    """Kết quả `upsert`: offer sau khi ghi và việc dòng này mới được tạo hay đã có từ trước."""

    offer: Offer
    created: bool


class OfferRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, offer_id: int) -> Offer | None:
        return self._session.get(Offer, offer_id) if fits_int4(offer_id) else None

    def get_by_url(self, url: str) -> Offer | None:
        return self._session.exec(select(Offer).where(Offer.url == url)).first()

    def product_ids_of(self, offer_ids: Sequence[int]) -> list[int]:
        """Id sản phẩm (không trùng, tăng dần) của các offer; id không tồn tại bị bỏ qua."""
        valid = list(dict.fromkeys(keep_valid(offer_ids)))
        found: set[int] = set()
        # PostgreSQL nhận tối đa 65.535 tham số mỗi câu lệnh: chia lô để lượt thu thập rất lớn
        # không làm hỏng bước đánh giá cảnh báo (BUG-M9-6).
        for start in range(0, len(valid), MAX_IN_PARAMETERS):
            batch = valid[start : start + MAX_IN_PARAMETERS]
            found.update(
                self._session.exec(select(Offer.product_id).where(col(Offer.id).in_(batch)))
            )
        return sorted(found)

    def list_tracked(self, site: SiteKey) -> list[TrackedOffer]:
        """Offer còn hoạt động của `site` mà người dùng đang theo dõi: sản phẩm có cảnh báo còn
        hiệu lực (`active`, `triggered`) hoặc nằm trong một danh sách mua. Theo id tăng dần."""
        alerted = select(PriceAlert.product_id).where(col(PriceAlert.status).in_(LIVE_STATUSES))
        listed = select(ShoppingListItem.product_id)
        statement = (
            select(Offer.id, Product.category)
            .join(Product, col(Product.id) == col(Offer.product_id))
            .where(
                Offer.site == site,
                col(Offer.is_active).is_(True),
                or_(col(Offer.product_id).in_(alerted), col(Offer.product_id).in_(listed)),
            )
            .order_by(col(Offer.id))
        )
        return [
            TrackedOffer(offer_id=offer_id, category=Category(category))
            for offer_id, category in self._session.exec(statement)
            if offer_id is not None
        ]

    def list_for_product(self, product_id: int, *, active_only: bool = True) -> list[Offer]:
        """Offer của một sản phẩm, rẻ nhất trước (theo giá hiệu lực)."""
        if not fits_int4(product_id):
            return []
        statement = select(Offer).where(Offer.product_id == product_id)
        if active_only:
            statement = statement.where(col(Offer.is_active).is_(True))
        return list(self._session.exec(statement.order_by(effective_price(), col(Offer.id))))

    def list_for_products(
        self, product_ids: list[int], *, active_only: bool = True
    ) -> dict[int, list[Offer]]:
        """Offer của nhiều sản phẩm trong một truy vấn; mỗi sản phẩm xếp rẻ nhất trước."""
        grouped: dict[int, list[Offer]] = {product_id: [] for product_id in product_ids}
        valid = keep_valid(product_ids)
        if not valid:
            return grouped
        statement = select(Offer).where(col(Offer.product_id).in_(valid))
        if active_only:
            statement = statement.where(col(Offer.is_active).is_(True))
        for offer in self._session.exec(statement.order_by(effective_price(), col(Offer.id))):
            grouped[offer.product_id].append(offer)
        return grouped

    def list_by_category(self, category: Category) -> list[Offer]:
        """Mọi offer (kể cả đã tắt) của sản phẩm thuộc `category`, theo id tăng dần (rematch)."""
        statement = (
            select(Offer)
            .join(Product, col(Product.id) == col(Offer.product_id))
            .where(Product.category == category)
            .order_by(col(Offer.id))
        )
        return list(self._session.exec(statement))

    def reassign(
        self, offer: Offer, product_id: int, method: MatchMethod, score: float | None
    ) -> Offer:
        """Chuyển offer sang sản phẩm khác kèm cách ghép mới (script ghép lại, T5.4).

        Mục danh sách mua của sản phẩm cũ đang ưu tiên offer này thì bỏ ưu tiên (về `NULL`):
        `preferred_offer_id` luôn phải là offer của chính sản phẩm của mục.
        """
        offer.product_id = product_id
        offer.match_method = method
        offer.match_score = score
        self._session.flush()
        self._session.execute(
            update(ShoppingListItem)
            .where(
                col(ShoppingListItem.preferred_offer_id) == offer.id,
                col(ShoppingListItem.product_id) != product_id,
            )
            .values(preferred_offer_id=None)
        )
        return offer

    def upsert(self, data: OfferUpsert, *, now: datetime | None = None) -> UpsertResult:
        """`INSERT … ON CONFLICT (url) DO UPDATE`: giữ `id`, `first_seen_at`, làm mới phần còn lại.

        Offer đã bị tắt (`is_active=false`) được bật lại. `scraped_at` = `now` (UTC).
        """
        moment = now or utc_now()
        values: dict[str, Any] = {
            **data.model_dump(),
            "is_active": True,
            "first_seen_at": moment,
            "scraped_at": moment,
        }
        statement = insert(Offer).values(**values)
        kept = {"url", "first_seen_at"}
        statement = statement.on_conflict_do_update(
            index_elements=["url"],
            set_={name: statement.excluded[name] for name in values if name not in kept},
        )
        # `xmax = 0` chỉ đúng với dòng vừa được INSERT (không phải dòng bị DO UPDATE). Hành vi này
        # không được PostgreSQL tài liệu hóa nhưng ổn định (đã kiểm trên PostgreSQL 17, có test).
        inserted = column("xmax").op("=")(literal_column("0"))
        row = self._session.exec(
            statement.returning(Offer, inserted.label("created")),
            execution_options={"populate_existing": True},
        ).one()
        self._session.flush()
        return UpsertResult(offer=row[0], created=bool(row[1]))

    def deactivate_unseen(self, site: SiteKey, category: Category, scraped_before: datetime) -> int:
        """Tắt offer của (site, category) có `scraped_at` < `scraped_before`; trả số offer vừa tắt.

        Pipeline gọi sau lượt ĐẦY ĐỦ (docs/06 §7 bước 3) với `scraped_before` = lúc lượt bắt đầu.
        """
        product_ids = select(Product.id).where(Product.category == category)
        statement = (
            update(Offer)
            .where(
                col(Offer.site) == site,
                col(Offer.product_id).in_(product_ids),
                col(Offer.is_active).is_(True),
                col(Offer.scraped_at) < scraped_before,
            )
            .values(is_active=False)
            .execution_options(synchronize_session="fetch")
        )
        result = self._session.exec(statement)
        self._session.flush()
        return int(result.rowcount)
