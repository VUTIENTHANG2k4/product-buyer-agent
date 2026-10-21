"""T7.4: `start`/`execute`/`reopen` của pipeline và dịch vụ tương đương `run`/`resume`."""

import re
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.db.models import ScrapeRun
from app.db.repositories import ScrapeRunRepository
from app.domain.enums import Category, ScrapeStatus, SiteKey
from app.domain.errors import (
    ChallengeFailed,
    ChallengeNotPending,
    InvalidScrapeRequest,
    OfflineMode,
    RunNotFound,
    ScrapeAlreadyRunning,
)
from app.scrapers.http.robots import RobotsCache, RobotsSnapshot
from app.scrapers.pipeline import NEEDS_HUMAN_STALE_AFTER, ScrapePipeline
from app.services.scrape_service import ScrapeService
from tests.integration.test_pipeline import Clock, mock_fetcher

SETTINGS = Settings(scraper_offline_only=True, scraper_max_listing_pages=5)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def make_service(
    factory: Callable[[], Session], clock: Clock, captcha_after: int = 10_000
) -> ScrapeService:
    fetcher = mock_fetcher(captcha_after=captcha_after)
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    return ScrapeService(factory, fetcher, SETTINGS, pipeline=pipe, now=clock)


async def test_start_creates_a_running_run_without_fetching_and_execute_finishes_it(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock)

    started = await service.start(SiteKey.mockshop, Category.mouse)

    db_session.expire_all()
    run = db_session.get(ScrapeRun, started.run_id)
    assert run is not None
    assert (run.status, run.pages_fetched, run.finished_at) == (ScrapeStatus.RUNNING, 0, None)
    assert (started.site, started.category) == (SiteKey.mockshop, Category.mouse)

    result = await service.execute(started)

    assert result.run_id == started.run_id
    assert result.status is ScrapeStatus.SUCCEEDED
    db_session.expire_all()
    assert db_session.exec(select(ScrapeRun)).all() == [run]


async def test_start_then_execute_gives_the_same_numbers_as_run(
    factory: Callable[[], Session], clock: Clock
) -> None:
    split = make_service(factory, clock)
    started = await split.start(SiteKey.mockshop, Category.mouse)
    from_split = await split.execute(started)

    from_run = await make_service(factory, clock).run(SiteKey.mockshop, Category.mouse)

    fields = ("status", "pages_fetched", "items_parsed", "items_failed", "offers_upserted")
    assert [getattr(from_split, f) for f in fields] == [getattr(from_run, f) for f in fields]


async def test_start_while_a_run_is_active_is_refused_before_execute(
    factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock)
    await service.start(SiteKey.mockshop, Category.mouse)

    with pytest.raises(ScrapeAlreadyRunning):
        await service.start(SiteKey.mockshop, Category.mouse)


async def test_start_reports_unusable_requests_as_validation_errors(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock)

    with pytest.raises(OfflineMode):
        await service.start(SiteKey.gearvn, Category.laptop)
    with pytest.raises(InvalidScrapeRequest):
        await service.start(SiteKey.mockshop, Category.phone)
    with pytest.raises(InvalidScrapeRequest):
        await service.start(SiteKey.mockshop, Category.mouse, max_pages=0)
    with pytest.raises(InvalidScrapeRequest):  # trang chưa có scraper
        await service.start(SiteKey.viettelstore, Category.laptop)

    assert db_session.exec(select(ScrapeRun)).all() == []


async def test_reopen_checks_the_answer_synchronously_and_execute_finishes_the_run(
    factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock, captcha_after=1)
    paused = await service.execute(await service.start(SiteKey.mockshop, Category.laptop))
    assert paused.status is ScrapeStatus.NEEDS_HUMAN and paused.challenge is not None

    with pytest.raises(ChallengeFailed):
        await service.reopen(paused.run_id, "ZZZZZ")
    match = re.search(r"[A-Z2-9]{5}$", paused.challenge.prompt or "")
    assert match
    reopened = await service.reopen(paused.run_id, match.group(0))

    assert reopened.run_id == paused.run_id
    done = await service.execute(reopened)
    assert done.status is ScrapeStatus.SUCCEEDED
    assert done.pages_fetched == 3


async def test_reopen_unknown_or_not_waiting_run(
    factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock)
    finished = await service.run(SiteKey.mockshop, Category.mouse)

    with pytest.raises(RunNotFound):
        await service.reopen(999_999, "ABCDE")
    with pytest.raises(ChallengeNotPending):
        await service.reopen(finished.run_id, "ABCDE")


async def test_challenge_of_hides_the_token_and_expires_with_the_wait(
    factory: Callable[[], Session], clock: Clock
) -> None:
    service = make_service(factory, clock, captcha_after=1)
    paused = await service.execute(await service.start(SiteKey.mockshop, Category.laptop))

    view = service.challenge_of(paused.run_id)

    assert view.kind.value == "captcha"
    assert view.prompt == (paused.challenge.prompt if paused.challenge else None)
    assert "token" not in view.model_dump()
    clock.now += NEEDS_HUMAN_STALE_AFTER - timedelta(seconds=1)
    assert service.challenge_of(paused.run_id).kind.value == "captcha"
    clock.now += timedelta(seconds=1)
    with pytest.raises(ChallengeNotPending):
        service.challenge_of(paused.run_id)


# ---- repository / robots ----
def test_list_filtered_combines_filters_and_returns_the_total(db_session: Session) -> None:
    from tests.factories import make_scrape_run

    db_session.add_all(
        [
            make_scrape_run(status=ScrapeStatus.SUCCEEDED),
            make_scrape_run(status=ScrapeStatus.SUCCEEDED, category=Category.mouse),
            make_scrape_run(status=ScrapeStatus.FAILED),
            make_scrape_run(site=SiteKey.gearvn, status=ScrapeStatus.SUCCEEDED),
        ]
    )
    db_session.flush()
    runs = ScrapeRunRepository(db_session)

    both, total = runs.list_filtered(site=SiteKey.mockshop, status=ScrapeStatus.SUCCEEDED, limit=1)
    none, none_total = runs.list_filtered(site=SiteKey.gearvn, status=ScrapeStatus.FAILED)
    beyond, beyond_total = runs.list_filtered(offset=100)

    assert (len(both), total) == (1, 2)
    assert (none, none_total) == ([], 0)
    assert (beyond, beyond_total) == ([], 4)


async def test_robots_snapshot_summarises_loaded_rules_without_network() -> None:
    bodies = {
        "https://open.example": (200, "User-agent: *\nDisallow:\n"),
        "https://partial.example": (200, "User-agent: *\nDisallow: /admin\nCrawl-delay: 7\n"),
        "https://blocked.example": (401, ""),
        "https://missing.example": (404, ""),
    }

    async def loader(origin: str) -> tuple[int, str]:
        return bodies[origin]

    cache = RobotsCache(loader, "TestAgent/1.0")
    assert cache.snapshot("https://open.example") is None  # chưa tải thì không đoán

    for origin in bodies:
        await cache.rules(origin)

    assert cache.snapshot("https://open.example") == RobotsSnapshot("allowed", None)
    assert cache.snapshot("https://partial.example") == RobotsSnapshot("partial", 7.0)
    assert cache.snapshot("https://blocked.example") == RobotsSnapshot("partial", None)
    assert cache.snapshot("https://missing.example") == RobotsSnapshot("allowed", None)
