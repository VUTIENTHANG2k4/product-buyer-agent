"""Cảnh báo giá: tạo, xem, sửa, xóa (docs/07 §3.5, tool `create_price_alert`).

Việc đánh giá điều kiện và gửi thông báo thuộc M9 (T9.1). Kênh và nơi nhận mặc định lấy từ cấu hình
(`ALERT_DEFAULT_CHANNEL`, `ALERT_DEFAULT_EMAIL`, `TELEGRAM_CHAT_ID`).
"""

import re

from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.models import PriceAlert, utc_now
from app.db.repositories import (
    OfferRepository,
    PriceAlertRepository,
    ProductRepository,
    normalize_destination,
)
from app.domain.catalog import AlertCreate, AlertView
from app.domain.enums import AlertChannel, AlertStatus
from app.domain.errors import AlertNotFound, DuplicateAlert, ProductNotFound, ValidationFailed
from app.services.views import Clock, aware_now, best_price

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_DESTINATION_LENGTH = 320
# Chỉ hai trạng thái người dùng được đặt tay; `triggered` do bộ đánh giá đặt.
SETTABLE_STATUSES = (AlertStatus.active, AlertStatus.paused)


class AlertService:
    def __init__(
        self, session: Session, settings: Settings | None = None, *, now: Clock = utc_now
    ) -> None:
        self._settings = settings or get_settings()
        self._now = now
        self._alerts = PriceAlertRepository(session)
        self._products = ProductRepository(session)
        self._offers = OfferRepository(session)

    def create(self, request: AlertCreate) -> AlertView:
        """Tạo cảnh báo `active`. Cùng sản phẩm, kênh, nơi nhận (đã chuẩn hóa) và ngưỡng đang có
        hiệu lực → `DuplicateAlert`."""
        product = self._products.get(request.product_id)
        if product is None:
            raise ProductNotFound(details={"product_id": request.product_id})
        channel = request.channel or self._settings.alert_default_channel
        channel = AlertChannel(channel)
        destination = self._destination(channel, request.destination)
        for live in self._alerts.list_for_products([request.product_id]):
            if (
                live.channel is channel
                and live.destination == destination
                and live.target_price == request.target_price
            ):
                raise DuplicateAlert(details={"alert_id": live.id})
        alert = self._alerts.create(
            request.product_id,
            request.target_price,
            channel,
            destination,
            now=aware_now(self._now),
        )
        return self._view(alert)

    def list_alerts(self, status: AlertStatus | None = None) -> list[AlertView]:
        return [self._view(alert) for alert in self._alerts.list_all(status=status)]

    def get(self, alert_id: int) -> AlertView:
        return self._view(self._require(alert_id))

    def update(
        self,
        alert_id: int,
        *,
        target_price: int | None = None,
        status: AlertStatus | None = None,
    ) -> AlertView:
        alert = self._require(alert_id)
        if target_price is not None:
            if not 0 < target_price <= 2**63 - 1:
                raise ValidationFailed("Giá mục tiêu phải lớn hơn 0", details={"target_price": 0})
            self._alerts.set_target_price(alert, target_price)
        if status is not None:
            if status not in SETTABLE_STATUSES:
                raise ValidationFailed("Chỉ đặt được trạng thái active hoặc paused")
            self._alerts.set_status(alert, status)
        return self._view(alert)

    def delete(self, alert_id: int) -> None:
        self._alerts.delete(self._require(alert_id))

    def _require(self, alert_id: int) -> PriceAlert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise AlertNotFound(details={"alert_id": alert_id})
        return alert

    def _destination(self, channel: AlertChannel, given: str | None) -> str:
        if given is None:
            given = (
                self._settings.alert_default_email
                if channel is AlertChannel.email
                else self._settings.telegram_chat_id
            )
        destination = normalize_destination(channel, given)
        if not destination:
            raise ValidationFailed(
                f"Chưa cấu hình nơi nhận cảnh báo cho kênh {channel.value}",
                details={"channel": channel.value},
            )
        if len(destination) > MAX_DESTINATION_LENGTH:
            raise ValidationFailed("Nơi nhận cảnh báo quá dài")
        if channel is AlertChannel.email and not _EMAIL.match(destination):
            raise ValidationFailed("Địa chỉ email không hợp lệ", details={"channel": "email"})
        return destination

    def _view(self, alert: PriceAlert) -> AlertView:
        product = self._products.get(alert.product_id)
        if alert.id is None or product is None:  # pragma: no cover - khóa ngoại bảo đảm
            raise RuntimeError("alert without id or product")
        offers = self._offers.list_for_products([alert.product_id])[alert.product_id]
        return AlertView(
            alert_id=alert.id,
            product_id=alert.product_id,
            product_name=product.canonical_name,
            target_price=alert.target_price,
            channel=alert.channel,
            destination=alert.destination,
            status=alert.status,
            current_best_price=best_price(offers),
            last_notified_price=alert.last_notified_price,
            last_notified_at=alert.last_notified_at,
            created_at=alert.created_at,
        )
