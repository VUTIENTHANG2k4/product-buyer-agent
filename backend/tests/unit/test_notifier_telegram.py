"""T9.2: TelegramNotifier (respx) và `build_notifiers`."""

import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.domain.enums import AlertChannel
from app.services.notifier import build_notifiers
from app.services.notifier.base import NotificationFailed
from app.services.notifier.email import EmailNotifier
from app.services.notifier.telegram import MAX_TEXT_LENGTH, TelegramNotifier
from tests.service_support import make_settings

TOKEN = "123456:MOCK-TOKEN"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def notifier() -> TelegramNotifier:
    return TelegramNotifier(SecretStr(TOKEN))


@respx.mock
def test_send_posts_chat_id_and_text_to_the_bot_api() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    notifier().send("@MockChat", "Giá giảm", "Nội dung")

    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content) == {
        "chat_id": "@MockChat",
        "text": "Giá giảm\n\nNội dung",
    }


@respx.mock
def test_long_text_is_cut_to_the_telegram_limit() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    notifier().send("1", "s", "x" * 10_000)

    assert len(json.loads(route.calls[0].request.content)["text"]) == MAX_TEXT_LENGTH


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_non_200_becomes_notification_failed_with_telegram_description(status: int) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(status, json={"ok": False, "description": "chat not found"})
    )

    with pytest.raises(NotificationFailed) as error:
        notifier().send("1", "s", "b")

    assert f"HTTP {status}" in str(error.value)
    assert "chat not found" in str(error.value)
    assert TOKEN not in str(error.value)


@respx.mock
def test_non_json_error_body_still_fails_cleanly() -> None:
    respx.post(URL).mock(return_value=httpx.Response(502, text="<html>bad gateway</html>"))

    with pytest.raises(NotificationFailed) as error:
        notifier().send("1", "s", "b")

    assert "HTTP 502" in str(error.value)


@respx.mock
@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("x"), httpx.ConnectError("x")])
def test_network_errors_do_not_leak_the_token(failure: httpx.HTTPError) -> None:
    respx.post(URL).mock(side_effect=failure)

    with pytest.raises(NotificationFailed) as error:
        notifier().send("1", "s", "b")

    assert type(failure).__name__ in str(error.value)
    assert TOKEN not in str(error.value)


def test_build_notifiers_with_nothing_configured_returns_no_channels() -> None:
    assert dict(build_notifiers(make_settings())) == {}


def test_build_notifiers_email_needs_both_host_and_sender() -> None:
    assert dict(build_notifiers(make_settings(smtp_host="smtp.mock.example"))) == {}
    assert dict(build_notifiers(make_settings(alert_email_from="a@mock.example"))) == {}

    built = build_notifiers(
        make_settings(smtp_host="smtp.mock.example", alert_email_from="a@mock.example")
    )

    assert isinstance(built[AlertChannel.email], EmailNotifier)
    assert AlertChannel.telegram not in built


def test_build_notifiers_telegram_needs_a_bot_token() -> None:
    built = build_notifiers(make_settings(telegram_bot_token=TOKEN))

    assert isinstance(built[AlertChannel.telegram], TelegramNotifier)
    assert AlertChannel.email not in built


@respx.mock
@pytest.mark.parametrize("body", ["[]", '"text"', "123", "null", '{"description": 5}'])
def test_error_bodies_that_are_not_an_object_with_a_text_description_still_fail_cleanly(
    body: str,
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(502, text=body))

    with pytest.raises(NotificationFailed) as error:
        notifier().send("1", "s", "b")

    assert "HTTP 502" in str(error.value) and "không rõ lý do" in str(error.value)
