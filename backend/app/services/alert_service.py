"""Cảnh báo giá: tạo, xem, sửa, xóa (docs/07 §3.5, tool `create_price_alert`).

Đánh giá điều kiện (`find_due`, `should_notify`) và ghi lần gửi (`mark_sent`) nằm ở đây; việc gửi
thông báo và commit từng cảnh báo do `AlertEvaluator` (`alert_evaluation.py`) làm. Kênh và nơi nhận
mặc định lấy từ cấu hình (`ALERT_DEFAULT_CHANNEL`, `ALERT_DEFAULT_EMAIL`, `TELEGRAM_CHAT_ID`).
"""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.models import PriceAlert
from app.db.repositories import (
    OfferRepository,
    PriceAlertRepository,
    ProductRepository,
    effective_price_of,
    normalize_destination,
)
from app.db.repositories.price_alerts import LIVE_STATUSES
from app.domain.catalog import AlertCreate, AlertView
from app.domain.clock import utc_now
from app.domain.enums import AlertChannel, AlertStatus, SiteKey
from app.domain.errors import AlertNotFound, DuplicateAlert, ProductNotFound, ValidationFailed
from app.services.notifier.base import NotificationFailed, Notifier
from app.services.notifier.message import format_vnd
from app.services.send_limiter import SendLimiter
from app.services.views import Clock, aware_now, best_price, sellable

logger = logging.getLogger(__name__)

# Một địa chỉ thường: dấu phẩy/chấm phẩy/ngoặc/dấu hai chấm biến chuỗi thành danh sách hoặc nhóm địa
# chỉ trong header `To` (BUG-M9-4: "victim,attacker@x.com" gửi tới cả "victim" và attacker@x.com).
_ADDRESS_CHARS = r"[^@\s,;:<>()\[\]\\\"]"
_EMAIL = re.compile(rf"^{_ADDRESS_CHARS}+@{_ADDRESS_CHARS}+\.{_ADDRESS_CHARS}+$")
MAX_DESTINATION_LENGTH = 320
MAX_TARGET_PRICE = 2**63 - 1  # cận trên BIGINT
RENOTIFY_MIN_DROP_PERCENT = 1  # đã báo rồi thì chỉ báo lại khi giá giảm thêm ≥ 1%
# Chỉ hai trạng thái người dùng được đặt tay; `triggered` do bộ đánh giá đặt.
SETTABLE_STATUSES = (AlertStatus.active, AlertStatus.paused)


def should_notify(alert: PriceAlert, price: int | None) -> bool:
    """Có nên gửi thông báo cho `alert` khi giá hiệu lực thấp nhất hiện tại là `price` (VND).

    Giá phải đã xuống tới ngưỡng. Nếu đã từng báo (`last_notified_price`, gồm cả cảnh báo
    `triggered` hoặc đã tạm dừng rồi bật lại) thì chỉ báo lại khi giá thấp hơn mốc đó thêm ít nhất
    1% (so bằng số nguyên, không dùng float). `paused` và sản phẩm không còn offer mua được
    (`price is None`) không bao giờ gửi.
    """
    if price is None or price > alert.target_price or alert.status not in LIVE_STATUSES:
        return False
    last = alert.last_notified_price
    return last is None or price * 100 <= last * (100 - RENOTIFY_MIN_DROP_PERCENT)


@dataclass(frozen=True)
class AlertTestResult:
    sent: bool
    reason: str | None = None


@dataclass(frozen=True)
class DueAlert:
    """Một cảnh báo cần gửi ngay, kèm dữ liệu dựng thông báo (tất cả lấy từ CSDL)."""

    alert_id: int
    channel: AlertChannel
    destination: str
    product_name: str
    target_price: int
    price: int
    previous_price: int | None
    site: SiteKey
    offer_url: str


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
        """Đổi ngưỡng và/hoặc trạng thái (active/paused). Kiểm tra hết rồi mới ghi, nên lỗi
        không để lại thay đổi một phần; đổi sang ngưỡng trùng cảnh báo khác → `DuplicateAlert`."""
        # Khóa dòng và đọc lại: nếu worker đang gửi cảnh báo này thì chờ nó commit rồi mới sửa trên
        # trạng thái mới nhất. Đọc không khóa làm UPDATE chỉ ghi cột đã đổi, để lại `triggered` và
        # `last_notified_price` của ngưỡng cũ cạnh ngưỡng mới (BUG-M9-7).
        alert = self._alerts.lock(alert_id, skip_locked=False)
        if alert is None:
            raise AlertNotFound(details={"alert_id": alert_id})
        if target_price is not None and not 0 < target_price <= MAX_TARGET_PRICE:
            raise ValidationFailed(
                f"Giá mục tiêu phải trong khoảng 1..{MAX_TARGET_PRICE}",
                details={"target_price": target_price},
            )
        if status is not None and status not in SETTABLE_STATUSES:
            raise ValidationFailed("Chỉ đặt được trạng thái active hoặc paused")
        # Trùng chỉ xét giữa các cảnh báo còn hiệu lực: đổi ngưỡng, hoặc bật lại cảnh báo đang
        # tạm dừng (trong lúc dừng có thể đã tạo cái giống hệt) đều phải kiểm tra.
        resulting_target = alert.target_price if target_price is None else target_price
        retargeted = target_price is not None and target_price != alert.target_price
        reactivated = status in LIVE_STATUSES and alert.status not in LIVE_STATUSES
        if retargeted or reactivated:
            for other in self._alerts.list_for_products([alert.product_id]):
                if (
                    other.id != alert.id
                    and other.channel is alert.channel
                    and other.destination == alert.destination
                    and other.target_price == resulting_target
                ):
                    raise DuplicateAlert(details={"alert_id": other.id})
        if target_price is not None:
            self._alerts.set_target_price(alert, target_price)
        if status is not None:
            self._alerts.set_status(alert, status)
        return self._view(alert)

    def delete(self, alert_id: int) -> None:
        self._alerts.delete(self._require(alert_id))

    def send_test(
        self,
        alert_id: int,
        notifiers: Mapping[AlertChannel, Notifier],
        limiter: SendLimiter | None = None,
    ) -> AlertTestResult:
        """Gửi thông báo thử tới nơi nhận của cảnh báo; không đổi trạng thái cảnh báo.

        Kênh chưa cấu hình, gửi lỗi hoặc gửi lại quá sớm (`limiter`) trả `sent=False` kèm lý do
        (không ném lỗi). Chỉ lần gọi thật sự đến notifier mới được tính vào giới hạn.
        """
        alert = self._require(alert_id)
        notifier = notifiers.get(alert.channel)
        if notifier is None:
            return AlertTestResult(
                sent=False, reason=f"Kênh {alert.channel.value} chưa được cấu hình trong .env"
            )
        if limiter is not None:
            wait = limiter.try_acquire(alert_id)
            if wait > 0:
                return AlertTestResult(
                    sent=False, reason=f"Vừa gửi thử cho cảnh báo này, thử lại sau {wait} giây"
                )
        view = self._view(alert)
        try:
            notifier.send(
                alert.destination,
                "Thông báo thử từ Product Buyer Agent",
                f"Cảnh báo giá cho {view.product_name}: ngưỡng {format_vnd(alert.target_price)}.\n"
                "Đây chỉ là tin nhắn thử, cảnh báo của bạn không thay đổi.",
            )
        except NotificationFailed as error:
            return AlertTestResult(sent=False, reason=str(error))
        except Exception:
            logger.exception("[alert %s] lỗi không lường trước khi gửi thử", alert_id)
            return AlertTestResult(sent=False, reason="Lỗi không xác định khi gửi thử")
        return AlertTestResult(sent=True)

    def find_due(self, offer_ids: Sequence[int] | None = None) -> list[DueAlert]:
        """Cảnh báo cần gửi sau khi giá của `offer_ids` đổi (`None`: xét mọi cảnh báo còn hiệu lực).

        Giá so sánh là giá hiệu lực thấp nhất của cả sản phẩm (mọi offer còn mua được), không chỉ
        của offer vừa đổi. Chỉ đọc; gửi xong nơi gọi phải `mark_sent` rồi commit từng cảnh báo.
        """
        if offer_ids is None:
            alerts = self._alerts.list_live()
        else:
            alerts = self._alerts.list_for_products(self._offers.product_ids_of(offer_ids))
        by_product = self._offers.list_for_products(sorted({alert.product_id for alert in alerts}))
        due: list[DueAlert] = []
        for alert in alerts:
            cheapest = sellable(by_product.get(alert.product_id, []))
            price = effective_price_of(cheapest[0]) if cheapest else None
            if alert.id is None or not should_notify(alert, price) or price is None:
                continue
            product = self._products.get(alert.product_id)
            if product is None:  # pragma: no cover - khóa ngoại bảo đảm
                continue
            due.append(
                DueAlert(
                    alert_id=alert.id,
                    channel=alert.channel,
                    destination=alert.destination,
                    product_name=product.canonical_name,
                    target_price=alert.target_price,
                    price=price,
                    previous_price=alert.last_notified_price,
                    site=cheapest[0].site,
                    offer_url=cheapest[0].url,
                )
            )
        return due

    def claim(self, due: DueAlert) -> bool:
        """Khóa dòng cảnh báo và xác nhận lại với trạng thái mới nhất trước khi gửi.

        `False` nếu cảnh báo đang được lượt đánh giá khác xử lý (khóa dòng, bỏ qua thay vì chờ nên
        không gửi trùng), đã bị xóa/tạm dừng, hoặc không còn đủ điều kiện kể từ `find_due`. Khi
        `True`, khóa được giữ tới lúc nơi gọi commit/rollback: người dùng sửa hoặc xóa cảnh báo
        này trong lúc gửi sẽ chờ tối đa thời gian gửi (≤ 15 giây).
        """
        alert = self._alerts.lock(due.alert_id, skip_locked=True)
        return alert is not None and should_notify(alert, due.price)

    def mark_sent(self, alert_id: int, price: int) -> bool:
        """Ghi lần gửi (`triggered`, `last_notified_*`). `False` nếu cảnh báo đã bị xóa hoặc tạm
        dừng trong lúc gửi (không ghi đè lựa chọn của người dùng). Đọc lại dòng từ CSDL, không dùng
        bản đã nạp từ `find_due`."""
        alert = self._alerts.lock(alert_id, skip_locked=False)
        if alert is None or alert.status not in LIVE_STATUSES:
            return False
        self._alerts.mark_notified(alert, price, now=aware_now(self._now))
        return True

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
        if "\x00" in destination:  # PostgreSQL không lưu được NUL (DataError → 500)
            raise ValidationFailed("Nơi nhận cảnh báo không hợp lệ")
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
