"""QA lượt việc nhỏ 2 (T9.7): ngắt mạch kênh trong một lượt đánh giá, các chuỗi lỗi xen kẽ."""

import logging
from collections.abc import Callable, Iterable

import pytest
from sqlmodel import Session

from app.db.models import PriceAlert
from app.domain.enums import AlertChannel, AlertStatus
from app.services.alert_evaluation import CHANNEL_DOWN_STRIKES, AlertEvaluator, EvaluationReport
from app.services.notifier.base import NotificationFailed
from tests.factories import make_price_alert
from tests.service_support import add_offer, add_product, clock, make_settings

SETTINGS = make_settings()
DOWN = NotificationFailed("down", channel_down=True)
RECIPIENT = NotificationFailed("người nhận bị từ chối")  # channel_down=False


class Scripted:
    """Notifier trả kết quả theo kịch bản từng lần gọi: None = thành công, hoặc ngoại lệ."""

    def __init__(
        self, script: Iterable[BaseException | None], default: BaseException | None = None
    ):
        self.script = list(script)
        self.default = default
        self.calls: list[str] = []

    def send(self, destination: str, subject: str, body: str) -> None:
        self.calls.append(destination)
        outcome = (
            self.script[len(self.calls) - 1]
            if len(self.calls) <= len(self.script)
            else self.default
        )
        if outcome is not None:
            raise outcome


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def due_alerts(
    session: Session, count: int, channel: AlertChannel = AlertChannel.email, tag: str = "qa"
) -> list[int]:
    ids: list[int] = []
    for number in range(count):
        product = add_product(session, canonical_name=f"Mock {tag} {channel.value} {number}")
        add_offer(
            session,
            product,
            price=10_000_000,
            url=f"https://mock.example/p/{tag}{channel.value}{number}",
        )
        alert = make_price_alert(
            product.id or 0,
            target_price=11_000_000,
            channel=channel,
            destination=f"{channel.value}{number}@x.vn",
        )
        session.add(alert)
        session.flush()
        ids.append(alert.id or 0)
    return ids


def status_of(session: Session, alert_id: int) -> AlertStatus:
    session.expire_all()
    return session.get_one(PriceAlert, alert_id).status


def evaluator(factory: Callable[[], Session], **notifiers: Scripted) -> AlertEvaluator:
    return AlertEvaluator(
        factory,
        {AlertChannel(name): notifier for name, notifier in notifiers.items()},
        SETTINGS,
        now=clock,
    )


def test_strike_threshold_is_two() -> None:
    assert CHANNEL_DOWN_STRIKES == 2


async def test_alternating_down_and_success_never_trips_the_channel(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = due_alerts(db_session, 6)
    email = Scripted([DOWN, None, DOWN, None, DOWN, None])

    report = await evaluator(factory, email=email).evaluate(None)

    assert len(email.calls) == 6
    assert report == EvaluationReport(sent=3, failed=3)
    assert sum(status_of(db_session, i) is AlertStatus.triggered for i in ids) == 3


async def test_a_recipient_failure_between_two_channel_failures_resets_the_streak(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 4)
    email = Scripted([DOWN, RECIPIENT, DOWN, None])

    report = await evaluator(factory, email=email).evaluate(None)

    assert len(email.calls) == 4  # không đủ 2 lỗi cả-kênh LIÊN TIẾP
    assert report == EvaluationReport(sent=1, failed=3)


async def test_recipient_failures_alone_never_trip_the_channel(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 5)
    email = Scripted([], default=RECIPIENT)

    report = await evaluator(factory, email=email).evaluate(None)

    assert len(email.calls) == 5
    assert report == EvaluationReport(sent=0, failed=5)


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyError("k"), ZeroDivisionError()])
async def test_unexpected_exceptions_never_trip_the_channel(
    db_session: Session, factory: Callable[[], Session], error: Exception
) -> None:
    ids = due_alerts(db_session, 5)
    email = Scripted([], default=error)

    report = await evaluator(factory, email=email).evaluate(None)

    assert len(email.calls) == 5  # mỗi cảnh báo vẫn được thử
    assert report == EvaluationReport(sent=0, failed=5)
    assert [status_of(db_session, i) for i in ids] == [AlertStatus.active] * 5


async def test_unexpected_exception_does_not_leak_into_the_next_alerts(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = due_alerts(db_session, 3)
    email = Scripted([RuntimeError("boom"), None, None])

    report = await evaluator(factory, email=email).evaluate(None)

    assert report == EvaluationReport(sent=2, failed=1)
    assert [status_of(db_session, i) for i in ids].count(AlertStatus.triggered) == 2


async def test_three_failures_after_a_success_trip_after_the_second_one(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 6)
    email = Scripted([None, DOWN, DOWN, DOWN, DOWN, DOWN])

    report = await evaluator(factory, email=email).evaluate(None)

    assert len(email.calls) == 3  # thành công, 2 lỗi cả-kênh, rồi ngắt
    assert report == EvaluationReport(sent=1, failed=5)


async def test_two_channels_down_at_once_are_tripped_independently(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    email_ids = due_alerts(db_session, 4, AlertChannel.email)
    tele_ids = due_alerts(db_session, 4, AlertChannel.telegram)
    email = Scripted([], default=DOWN)
    telegram = Scripted([], default=DOWN)

    report = await evaluator(factory, email=email, telegram=telegram).evaluate(None)

    assert (len(email.calls), len(telegram.calls)) == (2, 2)
    assert report == EvaluationReport(sent=0, failed=8)
    assert [status_of(db_session, i) for i in email_ids + tele_ids] == [AlertStatus.active] * 8


async def test_only_one_channel_down_while_the_other_alternates_keeps_the_other_alive(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 4, AlertChannel.email)
    due_alerts(db_session, 4, AlertChannel.telegram)
    email = Scripted([], default=DOWN)
    telegram = Scripted([DOWN, None, DOWN, None])

    report = await evaluator(factory, email=email, telegram=telegram).evaluate(None)

    assert len(email.calls) == 2 and len(telegram.calls) == 4
    assert report == EvaluationReport(sent=2, failed=2 + 2 + 2)


async def test_skipped_alerts_keep_their_state_and_are_retried_on_the_next_run(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = due_alerts(db_session, 5)
    email = Scripted([], default=DOWN)
    ev = evaluator(factory, email=email)

    first = await ev.evaluate(None)
    db_session.expire_all()
    snapshot = [
        (a.status, a.last_notified_price, a.last_notified_at)
        for a in (db_session.get_one(PriceAlert, i) for i in ids)
    ]

    assert first == EvaluationReport(sent=0, failed=5)
    assert snapshot == [(AlertStatus.active, None, None)] * 5
    assert len(email.calls) == 2

    email.default = (
        None  # kênh phục hồi: lượt sau thử lại cả năm, bộ đếm lỗi không dính sang lượt mới
    )
    second = await ev.evaluate(None)

    assert second == EvaluationReport(sent=5, failed=0)
    assert len(email.calls) == 7


async def test_a_new_run_starts_with_a_fresh_breaker_even_if_the_channel_was_down_before(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 3)
    email = Scripted([], default=DOWN)
    ev = evaluator(factory, email=email)

    await ev.evaluate(None)
    await ev.evaluate(None)

    assert len(email.calls) == 4  # 2 lần mỗi lượt


async def test_an_unconfigured_channel_does_not_count_as_a_strike_and_is_all_failed(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    ids = due_alerts(db_session, 3, AlertChannel.telegram)
    email = Scripted([])  # chỉ có email; cảnh báo telegram không có notifier

    report = await evaluator(factory, email=email).evaluate(None)

    assert report == EvaluationReport(sent=0, failed=3)
    assert email.calls == []
    assert [status_of(db_session, i) for i in ids] == [AlertStatus.active] * 3


async def test_a_telegram_failure_does_not_stop_email_alerts_listed_afterwards(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    due_alerts(db_session, 3, AlertChannel.telegram)
    email_ids = due_alerts(db_session, 3, AlertChannel.email)
    telegram = Scripted([], default=DOWN)
    email = Scripted([])

    report = await evaluator(factory, email=email, telegram=telegram).evaluate(None)

    assert len(email.calls) == 3 and len(telegram.calls) == 2
    assert report == EvaluationReport(sent=3, failed=3)
    assert [status_of(db_session, i) for i in email_ids] == [AlertStatus.triggered] * 3


async def test_evaluating_with_explicit_offer_ids_also_uses_the_breaker(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    from sqlmodel import select

    from app.db.models import Offer

    due_alerts(db_session, 4)
    offer_ids = [o.id or 0 for o in db_session.exec(select(Offer)).all()]
    email = Scripted([], default=DOWN)

    report = await evaluator(factory, email=email).evaluate(offer_ids)

    assert len(email.calls) == 2
    assert report.failed == 4 and report.sent == 0


async def test_logs_name_the_tripped_channel_once_and_do_not_leak_destinations(
    db_session: Session, factory: Callable[[], Session], caplog: pytest.LogCaptureFixture
) -> None:
    due_alerts(db_session, 5)
    email = Scripted([], default=DOWN)
    caplog.set_level(logging.INFO)

    await evaluator(factory, email=email).evaluate(None)

    tripped = [r for r in caplog.records if "không dùng được" in r.getMessage()]
    assert len(tripped) == 1 and "email" in tripped[0].getMessage()
    assert "@x.vn" not in caplog.text


async def test_failure_logs_do_not_contain_secrets_from_the_notifier_message(
    db_session: Session, factory: Callable[[], Session], caplog: pytest.LogCaptureFixture
) -> None:
    due_alerts(db_session, 2)
    email = Scripted(
        [], default=NotificationFailed("Không gửi được email (OSError)", channel_down=True)
    )
    caplog.set_level(logging.INFO)

    await evaluator(factory, email=email).evaluate(None)

    assert "OSError" in caplog.text
    assert "password" not in caplog.text.lower()
