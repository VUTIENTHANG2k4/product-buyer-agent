"""Repository cho `PriceAlert`."""

from datetime import datetime

from sqlmodel import Session, col, select

from app.db.models import PriceAlert, utc_now
from app.db.repositories.ids import fits_int4, keep_valid
from app.domain.enums import AlertChannel, AlertStatus

# Cảnh báo còn hiệu lực: `triggered` vẫn có thể gửi lại khi giá xuống thấp hơn (docs/11 T9.1).
LIVE_STATUSES = (AlertStatus.active, AlertStatus.triggered)


def normalize_destination(channel: AlertChannel, destination: str) -> str:
    """Bỏ khoảng trắng hai đầu; email thì thêm chữ thường (hộp thư không phân biệt hoa/thường)."""
    cleaned = destination.strip()
    return cleaned.lower() if channel is AlertChannel.email else cleaned


class PriceAlertRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        product_id: int,
        target_price: int,
        channel: AlertChannel,
        destination: str,
        *,
        now: datetime | None = None,
    ) -> PriceAlert:
        """Tạo cảnh báo `active`; `target_price` là VND, phải > 0."""
        alert = PriceAlert(
            product_id=product_id,
            target_price=target_price,
            channel=channel,
            destination=normalize_destination(channel, destination),
            created_at=now or utc_now(),
        )
        self._session.add(alert)
        self._session.flush()
        return alert

    def get(self, alert_id: int) -> PriceAlert | None:
        return self._session.get(PriceAlert, alert_id) if fits_int4(alert_id) else None

    def list_all(self, *, status: AlertStatus | None = None) -> list[PriceAlert]:
        """Mọi cảnh báo (mới nhất trước), có thể lọc theo trạng thái."""
        statement = select(PriceAlert)
        if status is not None:
            statement = statement.where(PriceAlert.status == status)
        statement = statement.order_by(col(PriceAlert.created_at).desc(), col(PriceAlert.id).desc())
        return list(self._session.exec(statement))

    def list_for_products(
        self, product_ids: list[int], *, statuses: tuple[AlertStatus, ...] = LIVE_STATUSES
    ) -> list[PriceAlert]:
        """Cảnh báo của các sản phẩm đã cho, trạng thái trong `statuses` (mặc định còn hiệu lực)."""
        valid = keep_valid(product_ids)
        if not valid:
            return []
        statement = (
            select(PriceAlert)
            .where(
                col(PriceAlert.product_id).in_(valid),
                col(PriceAlert.status).in_(statuses),
            )
            .order_by(col(PriceAlert.id))
        )
        return list(self._session.exec(statement))

    def list_live(self) -> list[PriceAlert]:
        """Mọi cảnh báo còn hiệu lực (`active`, `triggered`), theo id."""
        statement = (
            select(PriceAlert)
            .where(col(PriceAlert.status).in_(LIVE_STATUSES))
            .order_by(col(PriceAlert.id))
        )
        return list(self._session.exec(statement))

    def find_live(
        self, product_id: int, channel: AlertChannel, destination: str
    ) -> PriceAlert | None:
        """Cảnh báo còn hiệu lực cùng (sản phẩm, kênh, nơi nhận); dùng để chặn tạo trùng."""
        if not fits_int4(product_id):
            return None
        statement = (
            select(PriceAlert)
            .where(
                PriceAlert.product_id == product_id,
                PriceAlert.channel == channel,
                PriceAlert.destination == normalize_destination(channel, destination),
                col(PriceAlert.status).in_(LIVE_STATUSES),
            )
            .order_by(col(PriceAlert.id))
        )
        return self._session.exec(statement).first()

    def set_status(self, alert: PriceAlert, status: AlertStatus) -> PriceAlert:
        alert.status = status
        self._session.flush()
        return alert

    def set_target_price(self, alert: PriceAlert, target_price: int) -> PriceAlert:
        alert.target_price = target_price
        self._session.flush()
        return alert

    def mark_notified(
        self, alert: PriceAlert, price: int, *, now: datetime | None = None
    ) -> PriceAlert:
        """Ghi lần gửi: `triggered`, `last_notified_price` (VND) và `last_notified_at` (UTC)."""
        alert.status = AlertStatus.triggered
        alert.last_notified_price = price
        alert.last_notified_at = now or utc_now()
        self._session.flush()
        return alert

    def delete(self, alert: PriceAlert) -> None:
        self._session.delete(alert)
        self._session.flush()
