"""T7.6: vòng đời một lượt thu thập (huỷ trước khi chạy, chạy một lần, reopen offline)."""

import asyncio
import logging
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.tasks import TaskRegistry
from app.config import Settings
from app.db.models import ScrapeRun
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import ChallengeNotPending, OfflineMode, RunNotFound
from app.main import create_app
from app.scrapers import registry
from app.scrapers.pipeline import ScrapePipeline
from app.services.scrape_service import ScrapeService
from tests.factories import make_scrape_run
from tests.integration.test_pipeline import (
    Clock,
    RealScraper,
    ScriptedFetcher,
    mock_fetcher,
    pipeline,
)

SETTINGS = Settings(scraper_offline_only=True, scraper_max_listing_pages=5)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def run_by_id(session: Session, run_id: int) -> ScrapeRun:
    session.expire_all()
    return session.get_one(ScrapeRun, run_id)


# ---- execute một lần, abandon -----------------------------------------------------------------
async def test_a_task_cancelled_before_it_starts_leaves_the_run_running_until_abandoned(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    started = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    task = asyncio.get_running_loop().create_task(pipe.execute(started))
    task.cancel()  # hủy trước lần chạy đầu: thân execute không bao giờ chạy
    await asyncio.gather(task, return_exceptions=True)
    assert run_by_id(db_session, started.run_id).status is ScrapeStatus.RUNNING

    await pipe.abandon(started)

    run = run_by_id(db_session, started.run_id)
    assert run.status is ScrapeStatus.FAILED and run.finished_at is not None
    assert run.error_message == "Lượt thu thập bị huỷ."
    # Lượt mới chạy được ngay, không phải chờ 2 giờ hay gặp ScrapeAlreadyRunning.
    again = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert again.status is ScrapeStatus.SUCCEEDED


async def test_abandon_does_nothing_once_execute_has_taken_the_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    started = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    result = await pipe.execute(started)
    await pipe.abandon(started)

    assert result.status is ScrapeStatus.SUCCEEDED
    assert run_by_id(db_session, started.run_id).status is ScrapeStatus.SUCCEEDED


async def test_abandon_twice_is_a_no_op(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    started = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    await pipe.abandon(started)
    finished_at = run_by_id(db_session, started.run_id).finished_at
    await pipe.abandon(started)

    assert run_by_id(db_session, started.run_id).finished_at == finished_at


async def test_a_started_run_executes_only_once(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    started = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    await pipe.execute(started)

    with pytest.raises(RuntimeError, match="đã được chạy"):
        await pipe.execute(started)


async def test_an_abandoned_run_cannot_be_executed(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    started = await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    await pipe.abandon(started)

    with pytest.raises(RuntimeError):
        await pipe.execute(started)
    assert run_by_id(db_session, started.run_id).status is ScrapeStatus.FAILED


# ---- TaskRegistry.on_cancel + lifespan ---------------------------------------------------------
async def test_registry_runs_on_cancel_for_a_task_cancelled_before_its_first_step() -> None:
    tasks = TaskRegistry()
    ran: list[str] = []
    cleaned: list[str] = []

    async def work() -> None:
        ran.append("body")

    async def cleanup() -> None:
        cleaned.append("cleanup")

    tasks.spawn(work(), name="job", on_cancel=cleanup)
    await tasks.cancel_all()

    assert ran == [] and cleaned == ["cleanup"]
    assert tasks.pending == 0


async def test_registry_skips_on_cancel_for_tasks_that_finished_or_failed() -> None:
    tasks = TaskRegistry()
    cleaned: list[str] = []

    async def cleanup() -> None:
        cleaned.append("cleanup")

    async def ok() -> None:
        return None

    async def boom() -> None:
        raise RuntimeError("x")

    tasks.spawn(ok(), on_cancel=cleanup)
    tasks.spawn(boom(), on_cancel=cleanup)
    await tasks.wait_all()
    await tasks.cancel_all()

    assert cleaned == []


async def test_registry_logs_a_failing_cleanup_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tasks = TaskRegistry()

    async def work() -> None:
        await asyncio.sleep(3600)

    async def cleanup() -> None:
        raise ValueError("cannot clean")

    tasks.spawn(work(), name="job", on_cancel=cleanup)
    with caplog.at_level(logging.ERROR):
        await tasks.cancel_all()

    assert any("Dọn dẹp tác vụ bị hủy" in record.getMessage() for record in caplog.records)


def test_app_shutdown_cancels_background_tasks_and_closes_the_scrape_runtime() -> None:
    app = create_app()
    events: list[str] = []

    class FakeRuntime:
        async def aclose(self) -> None:
            events.append("runtime closed")

    app.state.scrape_runtime = FakeRuntime()

    async def work() -> None:
        events.append("body")
        await asyncio.sleep(3600)

    async def cleanup() -> None:
        events.append("cleanup")

    with TestClient(app) as client:

        async def spawn() -> None:
            app.state.tasks.spawn(work(), name="job", on_cancel=cleanup)

        client.portal.call(spawn)  # type: ignore[union-attr]

    assert events == ["body", "cleanup", "runtime closed"]  # hủy rồi dọn rồi mới đóng Fetcher
    assert app.state.tasks.pending == 0


# ---- reopen: offline và đã bị chiếm -------------------------------------------------------------
async def test_reopen_refuses_a_real_site_run_while_offline(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.gearvn, RealScraper)
    run = make_scrape_run(
        site=SiteKey.gearvn,
        status=ScrapeStatus.NEEDS_HUMAN,
        challenge={"kind": "text", "token": "t", "prompt": "Mã: ABCDE"},
    )
    db_session.add(run)
    db_session.flush()
    fetcher = ScriptedFetcher({})
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    service = ScrapeService(factory, fetcher, SETTINGS, pipeline=pipe)

    with pytest.raises(OfflineMode):
        await service.reopen(run.id or 0, "ABCDE")
    with pytest.raises(OfflineMode):
        await service.resume(run.id or 0, "ABCDE")

    assert run_by_id(db_session, run.id or 0).status is ScrapeStatus.NEEDS_HUMAN  # không bị chiếm
    assert fetcher.requested == []


async def test_reopen_of_an_unknown_run_is_not_found(
    factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({})
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    service = ScrapeService(factory, fetcher, SETTINGS, pipeline=pipe)

    with pytest.raises(RunNotFound):
        await service.reopen(999_999, "ABCDE")


async def test_a_second_reopen_of_a_run_the_first_already_claimed_is_refused(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    """Cuộc đua thật giữa hai tiến trình dựa vào khóa advisory của PostgreSQL; các phiên test dùng
    chung một kết nối nên ta kiểm trạng thái sau khi lần đầu đã chiếm lượt."""
    fetcher = mock_fetcher(captcha_after=1)
    pipe = pipeline(factory, fetcher, clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.challenge is not None and paused.challenge.prompt is not None
    answer = paused.challenge.prompt[-5:]

    first = await pipe.reopen(paused.run_id, answer)

    with pytest.raises(ChallengeNotPending) as second:
        await pipe.reopen(paused.run_id, answer)
    assert second.value.details["status"] == "RUNNING"
    await pipe.abandon(first)  # dọn lượt đã chiếm nhưng không chạy
    assert run_by_id(db_session, paused.run_id).status is ScrapeStatus.FAILED
