"""M9 sau review: khóa dòng khi gửi, gửi trùng khi đồng thời, đổi ngưỡng, lượt làm mới."""

import threading
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, delete, update
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, Product, ScrapeRun
from app.db.repositories import ScrapeRunRepository
from app.domain.enums import (
    AlertChannel,
    AlertStatus,
    Category,
    PriceType,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)
from app.domain.errors import ChallengeNotPending
from app.scrapers.pipeline import ScrapePipeline
from app.services.alert_evaluation import AlertEvaluator, EvaluationReport
from app.services.alert_service import AlertService
from app.services.notifier.base import NotificationFailed
from tests.factories import make_offer, make_price_alert, make_product
from tests.integration.test_alert_evaluation import FakeNotifier
from tests.integration.test_pipeline import (
    BASE,
    LAPTOP,
    NOW,
    Clock,
    ScriptedFetcher,
    card,
    listing,
    mock_fetcher,
    page,
)
from tests.integration.test_refresh_tracked import ASUS, offer_by_url
from tests.service_support import add_offer, add_product, clock, make_settings

SETTINGS = make_settings()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


@pytest.fixture
def pipe_clock() -> Clock:
    return Clock()


def evaluator(factory: Callable[[], Session], notifier: Any) -> AlertEvaluator:
    return AlertEvaluator(factory, {AlertChannel.email: notifier}, SETTINGS, now=clock)


def add_alert(session: Session, product: Product, **overrides: Any) -> PriceAlert:
    alert = make_price_alert(product.id or 0, target_price=28_000_000, **overrides)
    session.add(alert)
    session.flush()
    return alert


def reread(session: Session, alert: PriceAlert) -> PriceAlert:
    session.expire_all()
    return session.get_one(PriceAlert, alert.id)


class ActingNotifier(FakeNotifier):
    """Chạy một hành động (do người dùng) ngay trong lúc "đang gửi"."""

    def __init__(self, action: Callable[[], None]) -> None:
        super().__init__()
        self.action = action

    def send(self, destination: str, subject: str, body: str) -> None:
        self.action()
        super().send(destination, subject, body)


# ---- khóa dòng: người dùng đổi cảnh báo trong lúc đang gửi -----------------------------------
async def test_an_alert_paused_while_it_is_being_sent_stays_paused(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product)

    def pause() -> None:
        db_session.execute(
            update(PriceAlert)
            .where(col(PriceAlert.id) == alert.id)
            .values(status=AlertStatus.paused)
        )

    report = await evaluator(factory, ActingNotifier(pause)).evaluate([offer.id or 0])

    assert report == EvaluationReport(sent=0, failed=0)
    assert reread(db_session, alert).status is AlertStatus.paused
    assert reread(db_session, alert).last_notified_price is None


async def test_an_alert_deleted_while_it_is_being_sent_does_not_stop_the_others(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    doomed = add_alert(db_session, product, destination="first@example.com")
    survivor = add_alert(db_session, product, destination="second@example.com")

    def delete_first() -> None:
        db_session.execute(delete(PriceAlert).where(col(PriceAlert.id) == doomed.id))

    email = ActingNotifier(delete_first)
    first_send = email.send
    calls = 0

    def send_once_acting(destination: str, subject: str, body: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_send(destination, subject, body)
        else:
            FakeNotifier.send(email, destination, subject, body)

    email.send = send_once_acting  # type: ignore[method-assign]

    report = await evaluator(factory, email).evaluate([offer.id or 0])

    assert report.sent == 1
    assert reread(db_session, survivor).status is AlertStatus.triggered
    assert db_session.get(PriceAlert, doomed.id) is None


async def test_an_alert_that_stopped_being_due_before_sending_is_not_sent(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    """`claim` đọc lại dòng: cảnh báo đã bị người dùng đổi ngưỡng giữa `find_due` và lúc gửi."""
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product)
    service = AlertService(factory(), SETTINGS, now=clock)
    (due,) = service.find_due([offer.id or 0])
    alert.target_price = 20_000_000  # người dùng hạ ngưỡng xuống dưới giá hiện tại
    db_session.flush()

    assert service.claim(due) is False


# ---- hai lượt đánh giá chạy đồng thời (hai kết nối thật) -------------------------------------
@pytest.fixture
def committed_alert(db_engine: Engine) -> Iterator[tuple[int, int]]:
    """Sản phẩm + offer 24 triệu + cảnh báo ngưỡng 25 triệu, đã commit (kết nối khác thấy được)."""
    with Session(db_engine) as session:
        product = make_product()
        session.add(product)
        session.flush()
        offer = make_offer(product.id or 0, site=SiteKey.mockshop, price=24_000_000)
        alert = make_price_alert(product.id or 0, target_price=25_000_000)
        session.add_all([offer, alert])
        session.commit()
        ids = (offer.id or 0, alert.id or 0, product.id or 0)
    try:
        yield ids[0], ids[1]
    finally:
        with Session(db_engine) as session:
            session.delete(session.get_one(PriceAlert, ids[1]))
            session.delete(session.get_one(Offer, ids[0]))
            session.commit()
            session.delete(session.get_one(Product, ids[2]))
            session.commit()


def test_two_overlapping_evaluations_send_exactly_one_notification(
    db_engine: Engine, committed_alert: tuple[int, int]
) -> None:
    offer_id, alert_id = committed_alert
    sending = threading.Event()
    release = threading.Event()
    sent: list[str] = []

    class SlowNotifier:
        def send(self, destination: str, subject: str, body: str) -> None:
            sent.append(destination)
            sending.set()
            assert release.wait(timeout=15)

    def factory() -> Session:
        return Session(db_engine)

    first = AlertEvaluator(factory, {AlertChannel.email: SlowNotifier()}, SETTINGS)
    second = AlertEvaluator(factory, {AlertChannel.email: SlowNotifier()}, SETTINGS)
    results: list[EvaluationReport] = []
    worker = threading.Thread(target=lambda: results.append(first.evaluate_sync([offer_id])))
    worker.start()
    try:
        assert sending.wait(timeout=15)  # lượt 1 đang gửi, giữ khóa dòng
        concurrent = second.evaluate_sync([offer_id])  # lượt 2 thấy dòng bị khóa → bỏ qua
    finally:
        release.set()
        worker.join(timeout=20)

    assert concurrent == EvaluationReport(sent=0, failed=0)
    assert results == [EvaluationReport(sent=1, failed=0)]
    assert len(sent) == 1
    with Session(db_engine) as session:
        saved = session.get_one(PriceAlert, alert_id)
        assert (saved.status, saved.last_notified_price) == (AlertStatus.triggered, 24_000_000)


# ---- đổi ngưỡng và bật lại -------------------------------------------------------------------
async def test_changing_the_target_of_a_notified_alert_makes_it_a_new_alert(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product)
    email = FakeNotifier()
    ev = evaluator(factory, email)
    await ev.evaluate([offer.id or 0])
    assert len(email.sent) == 1
    offer.price = 29_500_000  # chưa chạm ngưỡng 28 triệu
    db_session.flush()

    db_session.expire_all()  # như một request mới: đọc lại dòng sau khi bộ đánh giá đã commit
    AlertService(db_session, SETTINGS, now=clock).update(alert.id or 0, target_price=30_000_000)

    saved = reread(db_session, alert)
    assert (saved.status, saved.last_notified_price, saved.last_notified_at) == (
        AlertStatus.active,
        None,
        None,
    )
    await ev.evaluate([offer.id or 0])
    assert len(email.sent) == 2  # giá 29,5 triệu đã chạm ngưỡng mới 30 triệu


async def test_pausing_and_resuming_a_notified_alert_does_not_resend_the_same_price(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=27_000_000)
    alert = add_alert(db_session, product)
    email = FakeNotifier()
    ev = evaluator(factory, email)
    await ev.evaluate([offer.id or 0])
    service = AlertService(db_session, SETTINGS, now=clock)
    service.update(alert.id or 0, status=AlertStatus.paused)
    service.update(alert.id or 0, status=AlertStatus.active)

    await ev.evaluate([offer.id or 0])
    assert len(email.sent) == 1  # bật lại không gửi lại đúng mức giá cũ

    offer.price = 26_700_000  # giảm thêm hơn 1% so với lần báo trước (27.000.000)
    db_session.flush()
    await ev.evaluate([offer.id or 0])
    assert len(email.sent) == 2


def test_retargeting_with_the_same_value_keeps_the_notified_mark(db_session: Session) -> None:
    product = add_product(db_session)
    alert = add_alert(
        db_session, product, status=AlertStatus.triggered, last_notified_price=27_000_000
    )

    AlertService(db_session, SETTINGS, now=clock).update(alert.id or 0, target_price=28_000_000)

    saved = reread(db_session, alert)
    assert (saved.status, saved.last_notified_price) == (AlertStatus.triggered, 27_000_000)


def test_send_test_reports_unexpected_notifier_errors_instead_of_raising(
    db_session: Session,
) -> None:
    class Exploding:
        def send(self, destination: str, subject: str, body: str) -> None:
            raise AttributeError("boom")

    product = add_product(db_session)
    add_offer(db_session, product)
    alert = add_alert(db_session, product)

    result = AlertService(db_session, SETTINGS, now=clock).send_test(
        alert.id or 0, {AlertChannel.email: Exploding()}
    )

    assert result.sent is False and result.reason


def test_send_test_still_reports_a_known_failure_reason(db_session: Session) -> None:
    class Refusing:
        def send(self, destination: str, subject: str, body: str) -> None:
            raise NotificationFailed("Telegram từ chối (HTTP 401)")

    product = add_product(db_session)
    add_offer(db_session, product)
    alert = add_alert(db_session, product)

    result = AlertService(db_session, SETTINGS, now=clock).send_test(
        alert.id or 0, {AlertChannel.email: Refusing()}
    )

    assert (result.sent, result.reason) == (False, "Telegram từ chối (HTTP 401)")


# ---- lượt làm mới giá: captcha, cảnh báo giả, nhãn giá, tồn kho ------------------------------
async def seeded(db_session: Session, factory: Callable[[], Session], pipe_clock: Clock) -> Offer:
    pipe = ScrapePipeline(factory, mock_fetcher(), default_max_pages=5, now=pipe_clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    return offer_by_url(db_session, ASUS)


async def test_a_captcha_during_a_refresh_ends_the_run_instead_of_waiting_for_an_answer(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    asus = await seeded(db_session, factory, pipe_clock)
    other = db_session.exec(select(Offer).where(col(Offer.id) != asus.id)).first()
    assert other is not None
    pipe = ScrapePipeline(factory, mock_fetcher(captcha_after=1), now=pipe_clock)

    # Yêu cầu thứ hai tới mock-shop bị đòi captcha.
    result = await pipe.refresh_offers(
        SiteKey.mockshop, Category.laptop, [asus.id or 0, other.id or 0]
    )

    assert result.status is ScrapeStatus.BLOCKED
    assert result.challenge is not None
    assert all(offer.is_active for offer in db_session.exec(select(Offer)).all())


async def test_a_tracked_refresh_run_can_never_be_resumed_as_a_category_crawl(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    await seeded(db_session, factory, pipe_clock)
    runs = ScrapeRunRepository(db_session)
    run = runs.create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.tracked_refresh, now=pipe_clock.now
    )
    runs.set_status(
        run,
        ScrapeStatus.NEEDS_HUMAN,
        challenge={
            "kind": "captcha",
            "site": "mockshop",
            "url": f"{BASE}/captcha",
            "token": "t",
            "prompt": "p",
        },
        now=pipe_clock.now,
    )
    db_session.flush()
    pipe = ScrapePipeline(factory, mock_fetcher(), now=pipe_clock)

    with pytest.raises(ChallengeNotPending):
        await pipe.reopen(run.id or 0, "answer")


async def test_a_refresh_run_never_reports_a_false_drop_in_item_count(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    asus = await seeded(db_session, factory, pipe_clock)
    pipe = ScrapePipeline(factory, mock_fetcher(), now=pipe_clock)
    pipe_clock.now = NOW + timedelta(hours=6)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    assert result.error_message is None
    run = db_session.get_one(ScrapeRun, result.run_id)
    db_session.refresh(run)
    assert (run.status, run.error_message) == (ScrapeStatus.SUCCEEDED, None)


async def test_an_ended_promotion_returns_the_offer_to_a_regular_price(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    asus = await seeded(db_session, factory, pipe_clock)
    asus.price_type, asus.list_price = PriceType.sale, 15_000_000  # giá niêm yết cũ < giá hiện tại
    db_session.flush()
    pipe = ScrapePipeline(factory, mock_fetcher(), now=pipe_clock)

    await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    saved = offer_by_url(db_session, ASUS)
    assert (saved.price, saved.price_type, saved.list_price) == (
        15_750_000,
        PriceType.regular,
        None,
    )


async def test_a_listing_without_stock_info_keeps_the_known_stock_status(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    first = ScriptedFetcher({LAPTOP: page(listing([card("a", "Laptop Acer Mock A")]))})
    pipe = ScrapePipeline(factory, first, default_max_pages=5, now=pipe_clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    stored = db_session.exec(select(Offer)).one()
    assert stored.stock_status is StockStatus.unknown
    stored.stock_status = StockStatus.in_stock  # lượt làm mới giá đã biết còn hàng
    db_session.flush()
    pipe_clock.now = NOW + timedelta(hours=1)

    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    db_session.expire_all()
    assert db_session.exec(select(Offer)).one().stock_status is StockStatus.in_stock


async def test_stock_info_from_a_listing_still_wins_over_the_stored_value(
    db_session: Session, factory: Callable[[], Session], pipe_clock: Clock
) -> None:
    pipe = ScrapePipeline(factory, mock_fetcher(), default_max_pages=5, now=pipe_clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    asus = offer_by_url(db_session, ASUS)
    asus.stock_status = StockStatus.out_of_stock  # mock-shop báo còn hàng ở lượt sau
    db_session.flush()
    pipe_clock.now = NOW + timedelta(hours=1)

    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert offer_by_url(db_session, ASUS).stock_status is StockStatus.in_stock
