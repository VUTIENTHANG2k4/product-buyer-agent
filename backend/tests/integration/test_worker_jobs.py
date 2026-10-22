"""T9.3: job định kỳ của worker chạy qua ScrapeService thật, kèm thông báo giá."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceAlert, ScrapeRun
from app.domain.enums import (
    AlertChannel,
    AlertStatus,
    Category,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
)
from app.scrapers.pipeline import ScrapePipeline
from app.services.alert_evaluation import AlertEvaluator
from app.services.scrape_service import ScrapeService
from app.worker import ScheduledJobs
from tests.factories import make_price_alert
from tests.integration.test_alert_evaluation import FakeNotifier
from tests.integration.test_pipeline import NOW, Clock, mock_fetcher
from tests.integration.test_refresh_tracked import ASUS, make_dearer, offer_by_url
from tests.service_support import make_settings

SETTINGS = make_settings(scraper_offline_only=True, scraper_max_listing_pages=5)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def jobs_for(
    factory: Callable[[], Session], clock: Clock, notifier: FakeNotifier | None = None
) -> tuple[ScheduledJobs, ScrapePipeline]:
    fetcher = mock_fetcher()
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    hook = AlertEvaluator(factory, {AlertChannel.email: notifier or FakeNotifier()}, SETTINGS)
    service = ScrapeService(factory, fetcher, SETTINGS, on_price_changes=hook, pipeline=pipe)
    return ScheduledJobs(service, SETTINGS), pipe


async def test_catalog_job_scrapes_every_mock_shop_category_as_a_scheduled_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    jobs, _ = jobs_for(factory, clock)

    results = await jobs.refresh_catalog()

    assert {r.category for r in results} == {
        Category.laptop,
        Category.mouse,
        Category.keyboard,
        Category.headset,
    }
    assert {r.site for r in results} == {SiteKey.mockshop}
    runs = db_session.exec(select(ScrapeRun)).all()
    assert len(runs) == 4
    assert {run.trigger for run in runs} == {ScrapeTrigger.schedule}
    assert {run.status for run in runs} == {ScrapeStatus.SUCCEEDED}


async def test_catalog_job_skips_a_group_that_already_has_an_active_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    jobs, pipe = jobs_for(factory, clock)
    active = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.manual)

    results = await jobs.refresh_catalog()

    assert Category.laptop not in {r.category for r in results}
    assert len(results) == 3
    laptop_runs = db_session.exec(
        select(ScrapeRun).where(col(ScrapeRun.category) == Category.laptop)
    ).all()
    assert [run.id for run in laptop_runs] == [active.run_id]


async def test_two_overlapping_catalog_runs_never_double_scrape_a_group(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    jobs, pipe = jobs_for(factory, clock)
    await pipe.start(SiteKey.mockshop, Category.mouse, ScrapeTrigger.schedule)  # job trước còn chạy

    first = await jobs.refresh_catalog()
    second = await jobs.refresh_catalog()

    assert Category.mouse not in {r.category for r in first}
    assert Category.mouse not in {r.category for r in second}
    mouse_runs = db_session.exec(
        select(ScrapeRun).where(col(ScrapeRun.category) == Category.mouse)
    ).all()
    assert len(mouse_runs) == 1


async def test_tracked_job_refreshes_only_watched_offers_and_sends_one_notification(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    email = FakeNotifier()
    jobs, _ = jobs_for(factory, clock, email)
    await jobs.refresh_catalog()
    asus = offer_by_url(db_session, ASUS)
    make_dearer(db_session, asus)  # lần trước 16.750.000, mock-shop hiện bán 15.750.000
    watched = make_price_alert(asus.product_id, target_price=16_000_000)
    db_session.add(watched)
    db_session.flush()
    clock.now = NOW + timedelta(hours=6)

    first = await jobs.refresh_tracked()
    second = await jobs.refresh_tracked()

    assert [(r.site, r.category, r.price_changes) for r in first] == [
        (SiteKey.mockshop, Category.laptop, 1)
    ]
    assert [r.price_changes for r in second] == [0]
    assert len(email.sent) == 1
    assert "15.750.000 ₫" in email.sent[0][1]
    db_session.expire_all()
    saved = db_session.get_one(PriceAlert, watched.id)
    assert (saved.status, saved.last_notified_price) == (AlertStatus.triggered, 15_750_000)
    tracked_runs = db_session.exec(
        select(ScrapeRun).where(col(ScrapeRun.trigger) == ScrapeTrigger.tracked_refresh)
    ).all()
    assert len(tracked_runs) == 2
    untouched = db_session.exec(select(Offer).where(col(Offer.id) != asus.id)).all()
    assert all(offer.scraped_at == NOW for offer in untouched)
