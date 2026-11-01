"""T9.1: AlertEvaluator trên PostgreSQL thật, notifier giả (US-07, docs/01 §5)."""

from collections.abc import Callable, Mapping

import pytest
from sqlmodel import Session, select

from app.db.models import Offer, PriceAlert, PriceHistory, Product
from app.domain.enums import AlertChannel, AlertStatus, Category, SiteKey, StockStatus
from app.scrapers.pipeline import ScrapePipeline
from app.services.alert_evaluation import AlertEvaluator, EvaluationReport
from app.services.notifier.base import NotificationFailed, Notifier
from app.services.scrape_service import ScrapeService
from tests.factories import make_price_alert
from tests.integration.test_pipeline import Clock, mock_fetcher
from tests.service_support import NOW, add_offer, add_product, clock, make_settings

SETTINGS = make_settings()


class FakeNotifier:
    """Ghi lại mọi lần gửi; `fail` bật thì ném `NotificationFailed`."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send(self, destination: str, subject: str, body: str) -> None:
        if self.fail:
            raise NotificationFailed("giả lập lỗi")
        self.sent.append((destination, subject, body))


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def evaluator(
    factory: Callable[[], Session], notifiers: Mapping[AlertChannel, Notifier]
) -> AlertEvaluator:
    return AlertEvaluator(factory, notifiers, SETTINGS, now=clock)


def add_alert(session: Session, product: Product, **overrides: object) -> PriceAlert:
    alert = make_price_alert(product.id or 0, **overrides)
    session.add(alert)
    session.flush()
    return alert


def refreshed(session: Session, alert: PriceAlert) -> PriceAlert:
    session.expire_all()
    return session.get_one(PriceAlert, alert.id)


async def test_us07_threshold_alert_sends_exactly_one_notification(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_490_000, url="https://mock.example/p/us07")
    alert = add_alert(db_session, product, target_price=28_000_000)
    email = FakeNotifier()
    ev = evaluator(factory, {AlertChannel.email: email})

    first = await ev.evaluate([offer.id or 0])
    second = await ev.evaluate([offer.id or 0])

    assert first == EvaluationReport(sent=1, failed=0)
    assert second == EvaluationReport(sent=0, failed=0)
    assert len(email.sent) == 1
    destination, subject, body = email.sent[0]
    assert destination == "mock@example.com"
    assert subject == f"Giá giảm: {product.canonical_name} còn 27.490.000 ₫"
    assert "Link: https://mock.example/p/us07" in body
    saved = refreshed(db_session, alert)
    assert (saved.status, saved.last_notified_price, saved.last_notified_at) == (
        AlertStatus.triggered,
        27_490_000,
        NOW,
    )


async def test_price_above_target_sends_nothing_and_keeps_the_alert_active(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=28_500_000)
    alert = add_alert(db_session, product, target_price=28_000_000)
    email = FakeNotifier()

    report = await evaluator(factory, {AlertChannel.email: email}).evaluate([offer.id or 0])

    assert report == EvaluationReport()
    assert email.sent == []
    assert refreshed(db_session, alert).status is AlertStatus.active


async def test_triggered_alert_is_resent_only_after_a_further_one_percent_drop(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product, target_price=28_000_000)
    email = FakeNotifier()
    ev = evaluator(factory, {AlertChannel.email: email})
    await ev.evaluate([offer.id or 0])

    offer.price = 26_800_000  # giảm 0,74%
    db_session.flush()
    await ev.evaluate([offer.id or 0])
    assert len(email.sent) == 1

    offer.price = 26_730_000  # đúng 1% so với lần báo trước
    db_session.flush()
    report = await ev.evaluate([offer.id or 0])

    assert report.sent == 1
    assert len(email.sent) == 2
    assert "Lần báo trước: 27.000.000 ₫" in email.sent[1][2]
    assert refreshed(db_session, alert).last_notified_price == 26_730_000


async def test_failed_send_leaves_the_alert_active_and_is_retried_next_time(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product, target_price=28_000_000)
    broken = FakeNotifier(fail=True)

    report = await evaluator(factory, {AlertChannel.email: broken}).evaluate([offer.id or 0])

    assert report == EvaluationReport(sent=0, failed=1)
    saved = refreshed(db_session, alert)
    assert (saved.status, saved.last_notified_price, saved.last_notified_at) == (
        AlertStatus.active,
        None,
        None,
    )
    working = FakeNotifier()
    retry = await evaluator(factory, {AlertChannel.email: working}).evaluate([offer.id or 0])
    assert retry.sent == 1
    assert len(working.sent) == 1


async def test_one_failing_alert_does_not_block_the_others(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=24_000_000)
    telegram_alert = add_alert(
        db_session, product, channel=AlertChannel.telegram, destination="@MockChat"
    )
    email_alert = add_alert(db_session, product)
    email = FakeNotifier()
    telegram = FakeNotifier(fail=True)

    report = await evaluator(
        factory, {AlertChannel.email: email, AlertChannel.telegram: telegram}
    ).evaluate([offer.id or 0])

    assert report == EvaluationReport(sent=1, failed=1)
    assert refreshed(db_session, email_alert).status is AlertStatus.triggered
    assert refreshed(db_session, telegram_alert).status is AlertStatus.active


async def test_channel_without_a_notifier_is_skipped_without_marking_it_sent(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=24_000_000)
    alert = add_alert(db_session, product, channel=AlertChannel.telegram, destination="@MockChat")

    report = await evaluator(factory, {AlertChannel.email: FakeNotifier()}).evaluate(
        [offer.id or 0]
    )

    assert report == EvaluationReport(sent=0, failed=1)
    assert refreshed(db_session, alert).status is AlertStatus.active


async def test_paused_alert_is_not_evaluated(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=1_000_000)
    add_alert(db_session, product, status=AlertStatus.paused)
    email = FakeNotifier()

    report = await evaluator(factory, {AlertChannel.email: email}).evaluate([offer.id or 0])

    assert report == EvaluationReport()
    assert email.sent == []


async def test_price_is_the_cheapest_sellable_offer_of_the_product_not_the_changed_one(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    changed = add_offer(db_session, product, price=30_000_000, url="https://mock.example/p/dear")
    add_offer(db_session, product, price=27_000_000, url="https://mock.example/p/cheap")
    add_offer(
        db_session,
        product,
        price=20_000_000,
        stock_status=StockStatus.out_of_stock,
        url="https://mock.example/p/gone",
    )
    add_alert(db_session, product, target_price=28_000_000)
    email = FakeNotifier()

    await evaluator(factory, {AlertChannel.email: email}).evaluate([changed.id or 0])

    assert len(email.sent) == 1
    body = email.sent[0][2]
    assert "27.000.000 ₫" in body
    assert "Link: https://mock.example/p/cheap" in body


async def test_product_with_only_out_of_stock_offers_sends_nothing(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=1_000_000, stock_status=StockStatus.out_of_stock)
    add_alert(db_session, product)
    email = FakeNotifier()

    report = await evaluator(factory, {AlertChannel.email: email}).evaluate([offer.id or 0])

    assert report == EvaluationReport()


async def test_offers_of_other_products_do_not_trigger_unrelated_alerts(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    watched = add_product(db_session)
    other = add_product(db_session)
    add_offer(db_session, watched, price=40_000_000)
    other_offer = add_offer(db_session, other, price=1_000_000)
    add_alert(db_session, watched, target_price=28_000_000)
    email = FakeNotifier()

    report = await evaluator(factory, {AlertChannel.email: email}).evaluate([other_offer.id or 0])

    assert report == EvaluationReport()


async def test_evaluating_without_offer_ids_checks_every_live_alert(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    first, second = add_product(db_session), add_product(db_session)
    add_offer(db_session, first, price=24_000_000)
    add_offer(db_session, second, price=24_000_000)
    add_alert(db_session, first)
    add_alert(db_session, second)
    email = FakeNotifier()

    report = await evaluator(factory, {AlertChannel.email: email}).evaluate(None)

    assert report.sent == 2


async def test_unknown_or_out_of_range_offer_ids_are_ignored(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    report = await evaluator(factory, {AlertChannel.email: FakeNotifier()}).evaluate([0, -1, 2**40])

    assert report == EvaluationReport()


async def test_unexpected_notifier_error_counts_as_failed_not_as_a_crash(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    class Exploding:
        def send(self, destination: str, subject: str, body: str) -> None:
            raise RuntimeError("boom")

    product = add_product(db_session)
    offer = add_offer(db_session, product, price=24_000_000)
    alert = add_alert(db_session, product)

    report = await evaluator(factory, {AlertChannel.email: Exploding()}).evaluate([offer.id or 0])

    assert report == EvaluationReport(sent=0, failed=1)
    assert refreshed(db_session, alert).status is AlertStatus.active


async def test_scrape_service_hands_changed_offers_to_the_evaluator(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    """Luồng thật: mock-shop → pipeline → `price_history` đổi → hook gửi đúng 1 thông báo."""
    fetcher = mock_fetcher()
    pipe_clock = Clock()
    email = FakeNotifier()
    hook = evaluator(factory, {AlertChannel.email: email})
    service = ScrapeService(
        factory,
        fetcher,
        SETTINGS,
        on_price_changes=hook,
        pipeline=ScrapePipeline(factory, fetcher, default_max_pages=5, now=pipe_clock),
    )
    await service.run(SiteKey.mockshop, Category.mouse)
    offer = db_session.exec(select(Offer)).first()
    assert offer is not None and offer.id is not None
    history = db_session.exec(select(PriceHistory).where(PriceHistory.offer_id == offer.id)).one()
    history.price += 50_000  # giá lưu cũ cao hơn: lượt sau sẽ ghi nhận giảm giá
    db_session.flush()
    alert = add_alert(db_session, db_session.get_one(Product, offer.product_id), target_price=10**9)

    await service.run(SiteKey.mockshop, Category.mouse)
    await service.run(SiteKey.mockshop, Category.mouse)

    assert len(email.sent) == 1
    assert refreshed(db_session, alert).status is AlertStatus.triggered
