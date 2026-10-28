"""T9.7: lỗi của cả kênh (`channel_down`) khác lỗi riêng một nơi nhận."""

import smtplib
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed
from app.services.notifier.email import EmailNotifier
from app.services.notifier.telegram import TelegramNotifier


def email_failing_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> NotificationFailed:
    class Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise error

    monkeypatch.setattr(smtplib, "SMTP", Boom)
    notifier = EmailNotifier(host="smtp.example", port=587, sender="a@x.vn")
    with pytest.raises(NotificationFailed) as raised:
        notifier.send("b@x.vn", "s", "b")
    return raised.value


@pytest.mark.parametrize(
    ("error", "channel_down"),
    [
        (ConnectionRefusedError(), True),
        (TimeoutError(), True),
        (smtplib.SMTPConnectError(421, b"busy"), True),
        (smtplib.SMTPAuthenticationError(535, b"bad login"), True),
        (smtplib.SMTPSenderRefused(550, b"no", "a@x.vn"), True),
        (smtplib.SMTPRecipientsRefused({"b@x.vn": (550, b"no such user")}), False),
        (smtplib.SMTPDataError(554, b"rejected"), False),
        (ValueError("header injection"), False),
    ],
)
def test_email_marks_only_channel_wide_failures_as_channel_down(
    monkeypatch: pytest.MonkeyPatch, error: Exception, channel_down: bool
) -> None:
    assert email_failing_with(monkeypatch, error).channel_down is channel_down


def test_telegram_transport_errors_are_channel_down_but_http_rejections_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifier = TelegramNotifier(SecretStr("123:abc"))

    def timeout(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("t")

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(NotificationFailed) as down:
        notifier.send("42", "s", "b")

    def rejected(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    monkeypatch.setattr(httpx, "post", rejected)
    with pytest.raises(NotificationFailed) as per_chat:
        notifier.send("42", "s", "b")

    assert down.value.channel_down is True
    assert per_chat.value.channel_down is False
