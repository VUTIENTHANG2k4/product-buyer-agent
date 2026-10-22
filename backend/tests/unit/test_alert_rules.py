"""T9.1: luật gửi/gửi lại thông báo giá (`should_notify`) và nội dung thông báo."""

import pytest

from app.domain.enums import AlertStatus, SiteKey
from app.services.alert_service import should_notify
from app.services.notifier.message import format_vnd, render_alert_message
from tests.factories import make_price_alert

TARGET = 28_000_000


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (27_490_000, True),
        (TARGET, True),  # đúng ngưỡng vẫn báo
        (TARGET + 1, False),
        (None, False),  # không còn offer mua được
    ],
)
def test_active_alert_fires_once_price_reaches_the_target(
    price: int | None, expected: bool
) -> None:
    alert = make_price_alert(1, target_price=TARGET)

    assert should_notify(alert, price) is expected


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (27_000_000, False),  # bằng lần báo trước
        (27_100_000, False),  # cao hơn lần báo trước
        (26_800_000, False),  # giảm 0,74%
        (26_731_000, False),  # giảm 0,99...% (chưa đủ 1%)
        (26_730_000, True),  # đúng 1% so với 27.000.000
        (25_000_000, True),
    ],
)
def test_triggered_alert_renotifies_only_after_a_one_percent_drop(
    price: int, expected: bool
) -> None:
    alert = make_price_alert(
        1, target_price=TARGET, status=AlertStatus.triggered, last_notified_price=27_000_000
    )

    assert should_notify(alert, price) is expected


def test_triggered_alert_never_fires_above_the_target_even_after_a_big_drop_from_last() -> None:
    alert = make_price_alert(
        1, target_price=20_000_000, status=AlertStatus.triggered, last_notified_price=40_000_000
    )

    assert should_notify(alert, 25_000_000) is False


def test_triggered_alert_without_a_recorded_price_fires() -> None:
    alert = make_price_alert(1, target_price=TARGET, status=AlertStatus.triggered)

    assert should_notify(alert, 27_000_000) is True


def test_paused_alert_never_fires() -> None:
    alert = make_price_alert(1, target_price=TARGET, status=AlertStatus.paused)

    assert should_notify(alert, 1_000_000) is False


def test_format_vnd_uses_dot_grouping() -> None:
    assert format_vnd(27_490_000) == "27.490.000 ₫"
    assert format_vnd(999) == "999 ₫"


def test_message_contains_only_given_facts_and_the_source_link() -> None:
    message = render_alert_message(
        product_name="Mock Laptop 1",
        price=27_490_000,
        target_price=28_000_000,
        site=SiteKey.mockshop,
        url="https://mock.example/p/1",
        previous_price=28_000_000,
    )

    assert message.subject == "Giá giảm: Mock Laptop 1 còn 27.490.000 ₫"
    assert "ngưỡng bạn đặt: 28.000.000 ₫" in message.body
    assert "Lần báo trước: 28.000.000 ₫" in message.body
    assert message.body.endswith("Link: https://mock.example/p/1")


def test_message_omits_previous_price_on_first_notification() -> None:
    message = render_alert_message(
        product_name="Mock Laptop 1",
        price=1,
        target_price=2,
        site=SiteKey.mockshop,
        url="https://mock.example/p/1",
    )

    assert "Lần báo trước" not in message.body


@pytest.mark.parametrize(
    ("price", "expected"),
    [(27_000_000, False), (26_800_000, False), (26_730_000, True)],
)
def test_active_alert_that_was_notified_before_follows_the_one_percent_rule(
    price: int, expected: bool
) -> None:
    """Cảnh báo `paused` rồi bật lại (`active` nhưng còn mốc đã báo) không gửi lại đúng mức cũ."""
    alert = make_price_alert(1, target_price=TARGET, last_notified_price=27_000_000)

    assert should_notify(alert, price) is expected


def test_subject_never_contains_line_breaks_even_if_the_product_name_does() -> None:
    message = render_alert_message(
        product_name="Laptop Mock\r\nBcc: victim@example.com\n  X",
        price=1_000_000,
        target_price=2_000_000,
        site=SiteKey.mockshop,
        url="https://mock.example/p/1",
    )

    assert "\n" not in message.subject and "\r" not in message.subject
    assert message.subject.startswith("Giá giảm: Laptop Mock Bcc: victim@example.com X")
