"""QA M9: biên của lịch cron, hủy job khi tắt worker, trang bị tắt hết."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from app import worker
from app.config import Settings
from app.domain.enums import Category, SiteKey
from app.scrapers.pipeline import PipelineResult
from app.services.alert_evaluation import AlertEvaluator
from app.services.scrape_runtime import ScrapeRuntime
from app.services.scrape_service import ScrapeService
from tests.service_support import make_settings
from tests.unit.test_worker import (
    FakeRuntime,
    HangingService,
    StubEvaluator,
    StubService,
    default_registry,
    jobs_with,
    stub_scraper,
)

MOMENT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


# ---- parse_cron -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "\n",
        "@daily",
        "@reboot",
        "*/0 * * * *",
        "0 0 * * * *",  # 6 trường (có giây)
        "0 0 * *",
        "60 * * * *",
        "0 24 * * *",
        "0 0 32 * *",
        "0 0 * 13 *",
        "a b c d e",
        "0 0 * * 8",
        "0 0 ? * *",
        "0 0 * * 1#2",
        "0 0 L * *",
        "-5 * * * *",
        "5-1 * * * *",
    ],
)
def test_malformed_cron_expressions_fail_at_startup_naming_the_variable(expression: str) -> None:
    with pytest.raises(ValueError, match="TRACKED_REFRESH_CRON"):
        worker.parse_cron("TRACKED_REFRESH_CRON", expression)


@pytest.mark.parametrize(
    "expression", ["0 0 31 2 *", "0 0 30 2 *", "0 0 31 4 *", "0 0 31 6,9,11 *"]
)
def test_cron_that_can_never_fire_is_rejected_at_startup(expression: str) -> None:
    """BUG-M9-3: ngày không tồn tại (31/2...) qua được `from_crontab` nhưng job không bao giờ chạy;
    worker khởi động bình thường và im lặng không thu thập gì."""
    with pytest.raises(ValueError, match="CATALOG_REFRESH_CRON"):
        worker.parse_cron("CATALOG_REFRESH_CRON", expression)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (" 0 0 * * *\n", datetime(2026, 10, 24, 0, 0, tzinfo=UTC)),
        ("0\t0\t*\t*\t*", datetime(2026, 10, 24, 0, 0, tzinfo=UTC)),
        ("0   0  *  * *", datetime(2026, 10, 24, 0, 0, tzinfo=UTC)),
        ("0 0 * * sun", datetime(2026, 10, 25, 0, 0, tzinfo=UTC)),  # tên ngày đúng thứ trong tuần
        ("0 0 * * SUN", datetime(2026, 10, 25, 0, 0, tzinfo=UTC)),
        ("0 0 1 jan *", datetime(2027, 1, 1, 0, 0, tzinfo=UTC)),
        ("0 0 29 2 *", datetime(2028, 2, 29, 0, 0, tzinfo=UTC)),  # chỉ năm nhuận nhưng vẫn chạy
        ("0,30 */6 * * *", datetime(2026, 10, 23, 12, 0, tzinfo=UTC)),
        ("15 3 * * mon-fri", datetime(2026, 10, 26, 3, 15, tzinfo=UTC)),
    ],
)
def test_valid_cron_forms_are_accepted_and_interpreted_in_utc(
    expression: str, expected: datetime
) -> None:
    trigger = worker.parse_cron("X", expression)

    assert trigger.get_next_fire_time(None, MOMENT) == expected


# ---- trang bị tắt hết / registry rỗng ---------------------------------------------------------
async def test_jobs_with_every_site_disabled_do_nothing_and_still_sweep_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker,
        "SCRAPERS",
        {
            SiteKey.mockshop: stub_scraper(
                SiteKey.mockshop, [Category.laptop], is_mock=True, enabled=False
            ),
            SiteKey.gearvn: stub_scraper(SiteKey.gearvn, [Category.laptop], enabled=False),
        },
    )
    service, evaluator = StubService(), StubEvaluator()
    jobs = worker.ScheduledJobs(
        cast(ScrapeService, service),
        make_settings(scraper_offline_only=False),
        cast(AlertEvaluator, evaluator),
    )

    assert jobs.sites() == []
    assert await jobs.refresh_catalog() == []
    assert await jobs.refresh_tracked() == []
    assert service.runs == [] and service.tracked == []
    assert evaluator.calls == [None, None]


async def test_jobs_with_an_empty_registry_return_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "SCRAPERS", {})
    jobs = worker.ScheduledJobs(cast(ScrapeService, StubService()), make_settings())

    assert await jobs.refresh_catalog() == [] and await jobs.refresh_tracked() == []


# ---- hủy khi tắt worker -----------------------------------------------------------------------
class StubbornService(HangingService):
    """Bắt `CancelledError` và tiếp tục chờ tới khi `release` được đặt: job không tuân theo hủy."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def run(self, site: SiteKey, category: Category, *, trigger: object) -> PipelineResult:
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
        raise RuntimeError("released")


async def test_cancel_running_gives_up_after_the_timeout_on_a_job_that_ignores_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "CANCEL_WAIT_SECONDS", 0.05)
    service = StubbornService()
    jobs = jobs_with(service, monkeypatch, offline=True)
    task = asyncio.create_task(jobs.refresh_catalog())
    await asyncio.sleep(0.02)

    try:
        await asyncio.wait_for(jobs.cancel_running(), timeout=5)  # không treo vô hạn
        assert service.cancelled and not task.done()
    finally:
        service.release.set()
        await asyncio.wait([task], timeout=5)


class HangingEvaluator(StubEvaluator):
    """`evaluate` chờ mãi (SMTP treo): job kẹt ở bước quét cảnh báo cuối job."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False
        self.entered = asyncio.Event()

    async def evaluate(self, offer_ids: object = None) -> None:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_cancel_running_also_cancels_a_job_stuck_in_the_final_alert_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = HangingEvaluator()
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    jobs = worker.ScheduledJobs(
        cast(ScrapeService, StubService()),
        make_settings(scraper_offline_only=True),
        cast(AlertEvaluator, evaluator),
    )
    task = asyncio.create_task(jobs.refresh_tracked())
    await asyncio.wait_for(evaluator.entered.wait(), timeout=5)  # không phụ thuộc tải máy
    assert not task.done()

    await jobs.cancel_running()

    assert task.cancelled() and evaluator.cancelled


async def test_a_job_started_by_the_real_apscheduler_executor_is_cancelled_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Giả định của `_track_current_task`: dưới `AsyncIOExecutor` thật, task hiện tại của job là
    task mà `cancel_running` hủy được (không chỉ khi gọi tay)."""
    service = HangingService()
    jobs = jobs_with(service, monkeypatch, offline=True)
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        jobs.refresh_catalog, DateTrigger(run_date=datetime.now(UTC) + timedelta(milliseconds=10))
    )
    scheduler.start()
    try:
        for _ in range(100):
            if service.cancelled or jobs._running:
                break
            await asyncio.sleep(0.02)
        assert jobs._running, "the executor's task was never registered"

        scheduler.shutdown(wait=False)
        await jobs.cancel_running()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)

    assert service.cancelled and not jobs._running


# ---- run_worker -------------------------------------------------------------------------------
async def test_a_failing_runtime_build_propagates_without_leaving_a_half_started_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(settings: Settings, spec_filler: object = None) -> ScrapeRuntime:
        raise ConnectionError("db down")

    monkeypatch.setattr(ScrapeRuntime, "build", boom)
    monkeypatch.setattr(worker, "build_spec_filler", lambda settings: None)
    started: list[AsyncIOScheduler] = []
    monkeypatch.setattr(
        worker,
        "build_scheduler",
        lambda *a, **k: started.append(object()) or None,  # type: ignore[arg-type]
    )

    with pytest.raises(ConnectionError):
        await worker.run_worker(make_settings(scheduler_enabled=True), asyncio.Event())

    assert started == []  # chưa dựng lịch khi chưa có runtime


async def test_scheduler_start_failure_still_closes_the_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime()

    class BrokenScheduler:
        def start(self) -> None:
            raise RuntimeError("no running loop")

        def shutdown(self, wait: bool = True) -> None:
            raise AssertionError("never started, nothing to shut down")

    monkeypatch.setattr(worker, "build_scheduler", lambda *a, **k: BrokenScheduler())

    with pytest.raises(RuntimeError, match="no running loop"):
        await worker.run_worker(
            make_settings(scheduler_enabled=True), asyncio.Event(), cast(ScrapeRuntime, runtime)
        )

    assert runtime.closed == 1
