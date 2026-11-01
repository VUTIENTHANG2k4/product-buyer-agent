"""T9.2: EmailNotifier với SMTP giả (không mở kết nối thật)."""

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest
from pydantic import SecretStr

from app.services.notifier.base import NotificationFailed
from app.services.notifier.email import EmailNotifier


class FakeSMTP:
    """Thay `smtplib.SMTP`/`SMTP_SSL`: ghi lại các bước và có thể ném lỗi ở một bước."""

    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.calls: list[tuple[str, Any]] = [("connect", (host, port, kwargs.get("timeout")))]
        self.kind = type(self).__name__
        self.has_context = kwargs.get("context") is not None
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step: str) -> None:
        if FakeSMTP.fail_on == step:
            raise smtplib.SMTPAuthenticationError(535, b"secret-user rejected")

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append(("quit", None))

    def starttls(self, **kwargs: Any) -> None:
        self.calls.append(("starttls", kwargs.get("context") is not None))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))
        self._maybe_fail("login")

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(("send", message))
        self._maybe_fail("send")


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_on = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    return FakeSMTP


def notifier(**overrides: Any) -> EmailNotifier:
    config: dict[str, Any] = {
        "host": "smtp.mock.example",
        "port": 587,
        "sender": "alerts@mock.example",
        "user": "mock-user",
        "password": SecretStr("mock-pass"),
    }
    return EmailNotifier(**{**config, **overrides})


def test_port_587_uses_starttls_then_logs_in_then_sends() -> None:
    notifier().send("buyer@mock.example", "Giá giảm: Mock", "Nội dung tiếng Việt có dấu")

    (smtp,) = FakeSMTP.instances
    assert smtp.kind == "FakeSMTP"
    assert [name for name, _ in smtp.calls] == ["connect", "starttls", "login", "send", "quit"]
    assert smtp.calls[0][1] == ("smtp.mock.example", 587, 15)
    assert smtp.calls[1][1] is True  # có ngữ cảnh TLS kiểm chứng chứng chỉ
    assert smtp.calls[2][1] == ("mock-user", "mock-pass")
    message = smtp.calls[3][1]
    assert (message["From"], message["To"], message["Subject"]) == (
        "alerts@mock.example",
        "buyer@mock.example",
        "Giá giảm: Mock",
    )
    assert "Nội dung tiếng Việt có dấu" in message.get_content()


def test_port_465_uses_implicit_tls_without_starttls() -> None:
    notifier(port=465).send("buyer@mock.example", "s", "b")

    (smtp,) = FakeSMTP.instances
    assert smtp.kind == "FakeSMTPSSL"
    assert smtp.has_context
    assert [name for name, _ in smtp.calls] == ["connect", "login", "send", "quit"]


def test_login_is_skipped_when_no_user_is_configured() -> None:
    notifier(user="", password=None).send("buyer@mock.example", "s", "b")

    (smtp,) = FakeSMTP.instances
    assert [name for name, _ in smtp.calls] == ["connect", "starttls", "send", "quit"]


@pytest.mark.parametrize("step", ["connect", "login", "send"])
def test_smtp_errors_become_notification_failed_without_leaking_details(step: str) -> None:
    FakeSMTP.fail_on = step

    with pytest.raises(NotificationFailed) as error:
        notifier().send("buyer@mock.example", "s", "b")

    text = str(error.value)
    assert "SMTPAuthenticationError" in text
    assert "secret-user" not in text and "mock-pass" not in text


def test_network_errors_become_notification_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("connection refused by smtp.mock.example")

    monkeypatch.setattr(smtplib, "SMTP", refuse)

    with pytest.raises(NotificationFailed) as error:
        notifier().send("buyer@mock.example", "s", "b")

    assert "ConnectionRefusedError" in str(error.value)


def test_header_injection_in_destination_is_rejected_as_a_failed_send() -> None:
    with pytest.raises(NotificationFailed):
        notifier().send("a@mock.example\r\nBcc: victim@mock.example", "s", "b")

    assert FakeSMTP.instances == []
