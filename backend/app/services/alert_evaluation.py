"""Đánh giá cảnh báo giá sau mỗi lượt làm mới và gửi thông báo (docs/03 §5.2, US-07).

`AlertEvaluator` là hook `on_price_changes` của `ScrapeService`. Từng cảnh báo được gửi rồi ghi
`triggered` + commit riêng: gửi lỗi thì cảnh báo giữ nguyên trạng thái (lần đánh giá sau thử lại);
chỉ khi tiến trình sập đúng giữa lúc gửi xong và commit mới có thể gửi trùng một lần.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlmodel import Session

from app.config import Settings
from app.db.models import utc_now
from app.domain.enums import AlertChannel
from app.services.alert_service import AlertService, DueAlert
from app.services.notifier.base import NotificationFailed, Notifier
from app.services.notifier.message import render_alert_message
from app.services.views import Clock

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class EvaluationReport:
    """Kết quả một lần đánh giá: số thông báo đã gửi và số cảnh báo cần gửi nhưng không gửi được."""

    sent: int = 0
    failed: int = 0


class AlertEvaluator:
    def __init__(
        self,
        session_factory: SessionFactory,
        notifiers: Mapping[AlertChannel, Notifier],
        settings: Settings,
        *,
        now: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._notifiers = notifiers
        self._settings = settings
        self._now = now

    async def __call__(self, offer_ids: Sequence[int] | None = None) -> None:
        """Khớp kiểu `PriceChangeHook`; chạy trong thread vì SMTP/HTTP/DB đều đồng bộ."""
        await self.evaluate(offer_ids)

    async def evaluate(self, offer_ids: Sequence[int] | None = None) -> EvaluationReport:
        """Đánh giá cảnh báo của sản phẩm có offer trong `offer_ids` (`None`: mọi cảnh báo)."""
        return await asyncio.to_thread(self.evaluate_sync, offer_ids)

    def evaluate_sync(self, offer_ids: Sequence[int] | None = None) -> EvaluationReport:
        sent = failed = 0
        with self._session_factory() as session:
            service = AlertService(session, self._settings, now=self._now)
            for due in service.find_due(offer_ids):
                if not self._send(due):
                    failed += 1
                    continue
                if service.mark_sent(due.alert_id, due.price):
                    session.commit()
                    sent += 1
                else:
                    session.rollback()  # cảnh báo bị xóa/tạm dừng trong lúc gửi
        if sent or failed:
            logger.info("đánh giá cảnh báo giá: %s đã gửi, %s lỗi", sent, failed)
        return EvaluationReport(sent=sent, failed=failed)

    def _send(self, due: DueAlert) -> bool:
        notifier = self._notifiers.get(due.channel)
        if notifier is None:
            logger.warning(
                "[alert %s] kênh %s chưa được cấu hình, bỏ qua", due.alert_id, due.channel.value
            )
            return False
        message = render_alert_message(
            product_name=due.product_name,
            price=due.price,
            target_price=due.target_price,
            site=due.site,
            url=due.offer_url,
            previous_price=due.previous_price,
        )
        try:
            notifier.send(due.destination, message.subject, message.body)
        except NotificationFailed as error:
            logger.warning("[alert %s] gửi qua %s thất bại: %s", due.alert_id, due.channel, error)
            return False
        except Exception:
            logger.exception("[alert %s] lỗi không lường trước khi gửi", due.alert_id)
            return False
        return True
