"""QA lượt việc nhỏ 2 (T9.7): lỗi cả-kênh hay riêng người nhận ở notifier, không lộ bí mật."""

import smtplib
import socket
import ssl
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed
from app.services.notifier.email import EmailNotifier
from app.services.notifier.telegram import TelegramNotifier

TOKEN = "123456:SECRET-TOKEN-VALUE"
DESTINATION = "nguoi.nhan.bi.mat@example.com"


def email_error(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> NotificationFailed:
    class Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise error

    monkeypatch.setattr(smtplib, "SMTP", Boom)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Boom)
    notifier = EmailNotifier(host="smtp.example", port=587, sender="a@x.vn")
    with pytest.raises(NotificationFailed) as raised:
        notifier.send(DESTINATION, "s", "b")
    return raised.value


def telegram_response(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception
) -> NotificationFailed:
    def post(*args: Any, **kwargs: Any) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(NotificationFailed) as raised:
        TelegramNotifier(SecretStr(TOKEN)).send("42", "s", "b")
    return raised.value


def test_default_notification_failed_is_not_channel_down() -> None:
    assert NotificationFailed("x").channel_down is False
    assert NotificationFailed("x", channel_down=True).channel_down is True


def test_notification_failed_keeps_its_message_as_str() -> None:
    assert str(NotificationFailed("lý do", channel_down=True)) == "lý do"


# ---------------------------------------------------------------- email
@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPServerDisconnected("bye"),
        smtplib.SMTPNotSupportedError("no starttls"),
        smtplib.SMTPHeloError(500, b"hello?"),
        smtplib.SMTPResponseException(421, b"shutting down"),
        smtplib.SMTPAuthenticationError(535, b"bad"),
        ssl.SSLError("handshake"),
        socket.gaierror(11001, "getaddrinfo failed"),
        TimeoutError("timed out"),
        ConnectionResetError(),
        BrokenPipeError(),
        OSError("network unreachable"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_email_connection_level_failures_are_channel_down(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    assert email_error(monkeypatch, error).channel_down is True


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPRecipientsRefused({DESTINATION: (550, b"unknown user")}),
        smtplib.SMTPDataError(554, b"spam"),
        ValueError("Header values may not contain linefeed"),
        UnicodeEncodeError("ascii", "é", 0, 1, "bad"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_email_recipient_or_content_failures_are_not_channel_down(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    assert email_error(monkeypatch, error).channel_down is False


@pytest.mark.parametrize("subject", ["a\nBcc: x@evil.example", "a\rb"])
def test_email_header_injection_is_rejected_per_alert_without_touching_the_network(
    monkeypatch: pytest.MonkeyPatch, subject: str
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("không được mở kết nối")

    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    notifier = EmailNotifier(host="smtp.example", port=587, sender="a@x.vn")

    with pytest.raises(NotificationFailed) as raised:
        notifier.send(DESTINATION, subject, "b")

    assert raised.value.channel_down is False
    assert "Bcc" not in str(raised.value)


def test_email_messages_name_only_the_error_type_not_address_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = smtplib.SMTPRecipientsRefused({DESTINATION: (550, b"mailbox " + DESTINATION.encode())})

    failure = email_error(monkeypatch, error)

    assert DESTINATION not in str(failure)
    assert str(failure) == "Không gửi được email (SMTPRecipientsRefused)"
    assert failure.__cause__ is None


def test_email_certificate_verification_failure_is_channel_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert email_error(monkeypatch, ssl.SSLCertVerificationError("self signed")).channel_down


def idna_failure(host: str) -> BaseException:
    """Lỗi thật `socket.getaddrinfo` ném khi tên máy chủ không mã hóa IDNA được."""
    try:
        host.encode("idna")
    except UnicodeError as error:
        return error
    raise AssertionError(f"{host!r} lẽ ra không mã hóa IDNA được")  # pragma: no cover


@pytest.mark.parametrize("host", ["a..b", "a" * 70 + ".example"])
def test_email_malformed_smtp_host_is_channel_down(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    # Bộ chặn mạng của test thay `getaddrinfo` nên lỗi IDNA thật phải được tiêm ở bước kết nối.
    assert email_error(monkeypatch, idna_failure(host)).channel_down is True


# ---------------------------------------------------------------- telegram
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("t"),
        httpx.ReadTimeout("t"),
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("bad"),
        httpx.WriteTimeout("t"),
        httpx.PoolTimeout("t"),
        httpx.ProxyError("proxy"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_telegram_transport_errors_are_channel_down(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    assert telegram_response(monkeypatch, error).channel_down is True


@pytest.mark.parametrize("status", [400, 403, 409])
def test_telegram_per_chat_rejections_are_not_channel_down(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    failure = telegram_response(
        monkeypatch, httpx.Response(status, json={"ok": False, "description": "chat not found"})
    )

    assert failure.channel_down is False


@pytest.mark.parametrize("status", [401, 404, 429])
def test_telegram_token_or_rate_limit_rejections_are_channel_down_even_without_json(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    failure = telegram_response(monkeypatch, httpx.Response(status, text="<html>nope</html>"))

    assert failure.channel_down is True
    assert "không rõ lý do" in str(failure)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_telegram_server_errors_are_channel_down(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    failure = telegram_response(monkeypatch, httpx.Response(status, text="bad gateway"))

    assert failure.channel_down is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>captive portal</html>"),
        httpx.Response(200, json={"ok": False, "description": "x"}),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json="ok"),
    ],
)
def test_telegram_http_200_without_ok_is_a_failure_for_that_alert_only(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    assert telegram_response(monkeypatch, response).channel_down is False


def test_telegram_errors_never_contain_the_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for error in (
        httpx.ConnectError(f"cannot reach {url}"),
        httpx.ReadTimeout(f"timeout {url}"),
        httpx.InvalidURL(f"bad {url}"),
    ):
        failure = telegram_response(monkeypatch, error)

        assert TOKEN not in str(failure) and "SECRET-TOKEN" not in repr(failure)
        assert failure.__cause__ is None
        assert failure.__suppress_context__ is True


def test_telegram_invalid_url_is_reported_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = telegram_response(monkeypatch, httpx.InvalidURL("bad"))

    assert str(failure) == "Không gửi được Telegram (InvalidURL)"


def test_telegram_description_is_truncated_to_200_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = telegram_response(
        monkeypatch, httpx.Response(400, json={"ok": False, "description": "x" * 5000})
    )

    assert len(str(failure)) < 300
