"""Bộ gửi thông báo giá: email (SMTP) và Telegram."""

from collections.abc import Mapping

from app.config import Settings
from app.domain.enums import AlertChannel
from app.services.notifier.base import NotificationFailed, Notifier
from app.services.notifier.email import EmailNotifier
from app.services.notifier.telegram import TelegramNotifier

__all__ = ["NotificationFailed", "Notifier", "build_notifiers"]


def build_notifiers(settings: Settings) -> Mapping[AlertChannel, Notifier]:
    """Bộ gửi của các kênh đã cấu hình đủ; kênh thiếu cấu hình không có trong kết quả.

    Email cần `SMTP_HOST` và `ALERT_EMAIL_FROM`; Telegram cần `TELEGRAM_BOT_TOKEN`.
    """
    notifiers: dict[AlertChannel, Notifier] = {}
    if settings.smtp_host and settings.alert_email_from:
        notifiers[AlertChannel.email] = EmailNotifier(
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=settings.alert_email_from,
            user=settings.smtp_user,
            password=settings.smtp_password,
        )
    if settings.telegram_bot_token.get_secret_value():
        notifiers[AlertChannel.telegram] = TelegramNotifier(settings.telegram_bot_token)
    return notifiers
