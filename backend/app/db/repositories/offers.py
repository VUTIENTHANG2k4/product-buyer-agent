"""Repository cho `Offer`: upsert theo `url`, tắt offer không còn thấy, giá hiệu lực.

Quy ước chung của mọi repository: nhận `Session` qua `__init__`, chỉ `flush`, không `commit`
(service/pipeline giữ transaction). Thời gian truyền vào qua `now` (UTC), mặc định `utc_now()`.
"""

from datetime import datetime
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, case, column, func, literal_column, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from app.db.models import Offer, Product, utc_now
from app.domain.dto import FiniteFloat, NonEmptyStr, Vnd
from app.domain.enums import Category, MatchMethod, PriceType, SiteKey, StockStatus


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


class UpsertResult(NamedTuple):
    """Kết quả `upsert`: offer sau khi ghi và việc dòng này mới được tạo hay đã có từ trước."""

    offer: Offer
    created: bool


class OfferRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, offer_id: int) -> Offer | None:
        return self._session.get(Offer, offer_id)

    def get_by_url(self, url: str) -> Offer | None:
        return self._session.exec(select(Offer).where(Offer.url == url)).first()

    def list_for_product(self, product_id: int, *, active_only: bool = True) -> list[Offer]:
        """Offer của một sản phẩm, rẻ nhất trước (theo giá hiệu lực)."""
        statement = select(Offer).where(Offer.product_id == product_id)
        if active_only:
            statement = statement.where(col(Offer.is_active).is_(True))
        return list(self._session.exec(statement.order_by(effective_price(), col(Offer.id))))

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
