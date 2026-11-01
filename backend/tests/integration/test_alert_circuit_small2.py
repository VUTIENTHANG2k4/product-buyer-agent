"""T9.7: kênh hỏng cả kênh bị ngắt mạch trong một lượt đánh giá."""

from collections.abc import Callable

import pytest
from sqlmodel import Session

from app.db.models import PriceAlert
from app.domain.enums import AlertChannel, AlertStatus
from app.services.alert_evaluation import AlertEvaluator, EvaluationReport
from app.services.notifier.base import NotificationFailed
from tests.factories import make_price_alert
from tests.service_support import add_offer, add_product, clock, make_settings

SETTINGS = make_settings()


class CountingNotifier:
    def __init__(self, error: NotificationFailed | None = None) -> None:
        self.error = error
        self.calls = 0

    def send(self, destination: str, subject: str, body: str) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def three_due_alerts(session: Session, channel: AlertChannel = AlertChannel.email) -> list[int]:
    ids: list[int] = []
    for number in range(3):
        product = add_product(session, canonical_name=f"Mock circuit {number}")
        add_offer(session, product, price=10_000_000, url=f"https://mock.example/p/c{number}")
        alert = make_price_alert(
            product.id or 0, target_price=11_000_000, channel=channel, destination=f"d{number}@x.vn"
        )
        session.add(alert)
        session.flush()
        ids.append(alert.id or 0)
    return ids


def statuses(session: Session, ids: list[int]) -> list[AlertStatus]:
    session.expire_all()
    return [session.get_one(PriceAlert, alert_id).status for alert_id in ids]


async def test_a_dead_channel_is_tried_twice_and_the_rest_are_skipped_for_the_run(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = three_due_alerts(db_session)
    email = CountingNotifier(NotificationFailed("down", channel_down=True))
    ev = AlertEvaluator(factory, {AlertChannel.email: email}, SETTINGS, now=clock)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=0, failed=3)
    assert email.calls == 2  # hai lỗi liên tiếp thì ngắt, cảnh báo thứ ba không tốn thêm timeout
    assert statuses(db_session, ids) == [AlertStatus.active] * 3

    email.error = None  # kênh sống lại: lượt sau gửi cả ba
    again = await ev.evaluate(None)

    assert again == EvaluationReport(sent=3, failed=0)
    assert email.calls == 5
    assert statuses(db_session, ids) == [AlertStatus.triggered] * 3


async def test_a_failure_of_one_recipient_does_not_stop_the_others(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = three_due_alerts(db_session)

    class OneBadRecipient:
        calls = 0

        def send(self, destination: str, subject: str, body: str) -> None:
            self.calls += 1
            if destination == "d0@x.vn":
                raise NotificationFailed("người nhận bị từ chối")  # channel_down=False

    email = OneBadRecipient()
    ev = AlertEvaluator(factory, {AlertChannel.email: email}, SETTINGS, now=clock)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=2, failed=1)
    assert email.calls == 3
    assert sorted(s.value for s in statuses(db_session, ids)) == [
        "active",
        "triggered",
        "triggered",
    ]


async def test_a_dead_channel_does_not_stop_another_channel(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    email_ids = three_due_alerts(db_session)
    product = add_product(db_session, canonical_name="Mock circuit telegram")
    add_offer(db_session, product, price=10_000_000, url="https://mock.example/p/ctg")
    telegram_alert = make_price_alert(
        product.id or 0, target_price=11_000_000, channel=AlertChannel.telegram, destination="42"
    )
    db_session.add(telegram_alert)
    db_session.flush()
    email = CountingNotifier(NotificationFailed("down", channel_down=True))
    telegram = CountingNotifier()
    ev = AlertEvaluator(
        factory,
        {AlertChannel.email: email, AlertChannel.telegram: telegram},
        SETTINGS,
        now=clock,
    )

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=1, failed=3)
    assert (email.calls, telegram.calls) == (2, 1)
    assert statuses(db_session, email_ids) == [AlertStatus.active] * 3


async def test_a_transient_failure_followed_by_a_success_does_not_trip_the_channel(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = three_due_alerts(db_session)

    class FlakyOnce:
        calls = 0

        def send(self, destination: str, subject: str, body: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise NotificationFailed("hết thời gian chờ thoáng qua", channel_down=True)

    email = FlakyOnce()
    ev = AlertEvaluator(factory, {AlertChannel.email: email}, SETTINGS, now=clock)

    report = await ev.evaluate(None)

    assert report == EvaluationReport(sent=2, failed=1)
    assert email.calls == 3  # cảnh báo thứ hai thành công nên kênh không bị ngắt
    assert sorted(s.value for s in statuses(db_session, ids)) == [
        "active",
        "triggered",
        "triggered",
    ]
