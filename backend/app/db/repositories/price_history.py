"""Repository cho `PriceHistory` (append-only): luật thêm dòng và truy vấn chuỗi giá."""

from datetime import datetime, timedelta
from typing import Literal, NamedTuple

from sqlmodel import Session, col, select

from app.db.models import Offer, PriceHistory
from app.domain.clock import utc_now
from app.domain.enums import PriceType, SiteKey, StockStatus

# Dòng cuối cũ hơn mức này thì thêm một dòng dù không đổi gì (docs/04 §3).
HEARTBEAT_INTERVAL = timedelta(hours=24)

SnapshotReason = Literal["first", "changed", "heartbeat"]


class SnapshotResult(NamedTuple):
    """Kết quả `record_snapshot`.

    `added`: có thêm dòng lịch sử hay không (`reason` là None khi không thêm).
    `previous_price`: giá ở dòng lịch sử gần nhất trước đó (VND), None nếu offer chưa có lịch sử.
    `price_changed`: đã có lịch sử và giá khác dòng đó (chỉ đổi `price_type`/tồn kho là False).
    """

    added: bool
    reason: SnapshotReason | None
    previous_price: int | None
    price_changed: bool


class PricePoint(NamedTuple):
    """Một điểm của chuỗi giá, kèm trang và offer để vẽ biểu đồ theo trang."""

    offer_id: int
    site: SiteKey
    scraped_at: datetime
    price: int
    price_type: PriceType
    stock_status: StockStatus


class PriceHistoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest(self, offer_id: int) -> PriceHistory | None:
        statement = (
            select(PriceHistory)
            .where(PriceHistory.offer_id == offer_id)
            .order_by(col(PriceHistory.scraped_at).desc(), col(PriceHistory.id).desc())
        )
        return self._session.exec(statement).first()

    def record_snapshot(self, offer: Offer, *, now: datetime | None = None) -> SnapshotResult:
        """Thêm dòng lịch sử cho `offer` theo luật docs/04 §3 (so với dòng lịch sử gần nhất).

        Thêm khi: chưa có dòng nào (`first`); `price`, `price_type` hoặc `stock_status` đổi
        (`changed`); hoặc dòng cuối cũ hơn 24 giờ, đúng 24 giờ thì chưa (`heartbeat`).
        """
        if offer.id is None:
            raise ValueError("offer chưa được lưu (id là None)")
        moment = now or utc_now()
        last = self.latest(offer.id)

        reason: SnapshotReason | None
        if last is None:
            reason = "first"
        elif (last.price, last.price_type, last.stock_status) != (
            offer.price,
            offer.price_type,
            offer.stock_status,
        ):
            reason = "changed"
        elif moment - last.scraped_at > HEARTBEAT_INTERVAL:
            reason = "heartbeat"
        else:
            reason = None

        if reason is not None:
            self._session.add(
                PriceHistory(
                    offer_id=offer.id,
                    price=offer.price,
                    price_type=offer.price_type,
                    stock_status=offer.stock_status,
                    scraped_at=moment,
                )
            )
            self._session.flush()
        return SnapshotResult(
            added=reason is not None,
            reason=reason,
            previous_price=None if last is None else last.price,
            price_changed=last is not None and last.price != offer.price,
        )

    def list_for_offer(self, offer_id: int, *, since: datetime | None = None) -> list[PriceHistory]:
        """Lịch sử của một offer, cũ nhất trước; `since` giữ các dòng có `scraped_at >= since`."""
        statement = select(PriceHistory).where(PriceHistory.offer_id == offer_id)
        if since is not None:
            statement = statement.where(col(PriceHistory.scraped_at) >= since)
        statement = statement.order_by(col(PriceHistory.scraped_at), col(PriceHistory.id))
        return list(self._session.exec(statement))

    def series_for_product(
        self, product_id: int, *, since: datetime | None = None
    ) -> list[PricePoint]:
        """Mọi điểm giá của offer (kể cả đã tắt) của sản phẩm, theo trang rồi theo thời gian."""
        statement = (
            select(PriceHistory, Offer.site)
            .join(Offer, col(Offer.id) == col(PriceHistory.offer_id))
            .where(Offer.product_id == product_id)
        )
        if since is not None:
            statement = statement.where(col(PriceHistory.scraped_at) >= since)
        statement = statement.order_by(
            col(Offer.site),
            col(PriceHistory.offer_id),
            col(PriceHistory.scraped_at),
            col(PriceHistory.id),
        )
        return [
            PricePoint(
                offer_id=row.offer_id,
                site=SiteKey(site),
                scraped_at=row.scraped_at,
                price=row.price,
                price_type=row.price_type,
                stock_status=row.stock_status,
            )
            for row, site in self._session.exec(statement)
        ]
