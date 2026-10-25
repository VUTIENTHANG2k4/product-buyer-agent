"""T9.3: worker và lịch APScheduler (không chờ giờ thật, không mạng, không DB)."""

import asyncio
import io
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import worker
from app.config import Settings
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.domain.errors import OfflineMode, ScrapeAlreadyRunning, SiteCooldown
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.pipeline import PipelineResult
from app.scrapers.registry import SiteNotAvailable
from app.services.alert_evaluation import AlertEvaluator
from app.services.scrape_runtime import ScrapeRuntime
from app.services.scrape_service import ScrapeService
from tests.service_support import make_settings

MOMENT = datetime(2026, 10, 22, 5, 30, tzinfo=UTC)


def result(site: SiteKey, category: Category, run_id: int = 1) -> PipelineResult:
    return PipelineResult(
        run_id=run_id,
        site=site,
        category=category,
        status=ScrapeStatus.SUCCEEDED,
        pages_fetched=1,
        items_parsed=1,
        items_failed=0,
        offers_upserted=1,
        price_changes=0,
        changed_offer_ids=(),
    )


def stub_scraper(
    key: SiteKey, categories: list[Category], *, is_mock: bool = False, enabled: bool = True
) -> type[BaseScraper]:
    config = SiteConfig(
        key=key,
        base_url=f"https://{key.value}.example",
        min_delay_s=0,
        categories={
            category: f"https://{key.value}.example/{category.value}" for category in categories
        },
        is_mock=is_mock,
        enabled=enabled,
    )
    return type("Stub", (BaseScraper,), {"config": config, "parse_listing": lambda *a: None})


class StubService:
    """Thay `ScrapeService`: ghi lại lời gọi, có thể ném lỗi theo (site, nhóm)."""

    def __init__(self, errors: dict[tuple[SiteKey, Category | None], BaseException] | None = None):
        self.errors = errors or {}
        self.runs: list[tuple[SiteKey, Category, ScrapeTrigger]] = []
        self.tracked: list[SiteKey] = []

    async def run(
        self, site: SiteKey, category: Category, *, trigger: ScrapeTrigger
    ) -> PipelineResult:
        await asyncio.sleep(0)
        self.runs.append((site, category, trigger))
        if (site, category) in self.errors:
            raise self.errors[(site, category)]
        return result(site, category, len(self.runs))

    async def refresh_tracked(self, site: SiteKey) -> list[PipelineResult]:
        await asyncio.sleep(0)
        self.tracked.append(site)
        if (site, None) in self.errors:
            raise self.errors[(site, None)]
        return [result(site, Category.laptop, len(self.tracked))]


def jobs_with(
    service: StubService, monkeypatch: pytest.MonkeyPatch, *, offline: bool = False, **scrapers: Any
) -> worker.ScheduledJobs:
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    settings = make_settings(scraper_offline_only=offline, **scrapers)
    return worker.ScheduledJobs(cast(ScrapeService, service), settings)


def default_registry() -> dict[SiteKey, type[BaseScraper]]:
    return {
        SiteKey.mockshop: stub_scraper(
            SiteKey.mockshop, [Category.laptop, Category.mouse], is_mock=True
        ),
        SiteKey.gearvn: stub_scraper(SiteKey.gearvn, [Category.laptop, Category.mouse]),
        SiteKey.fptshop: stub_scraper(SiteKey.fptshop, [Category.laptop]),
    }


# ---- lịch -------------------------------------------------------------------------------------
def test_build_scheduler_registers_the_two_jobs_with_the_configured_crons() -> None:
    settings = make_settings(
        catalog_refresh_cron="0 */12 * * *", tracked_refresh_cron="15 */6 * * *"
    )
    scheduler = worker.build_scheduler(
        worker.ScheduledJobs(cast(ScrapeService, StubService()), settings), settings
    )

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"catalog_refresh", "tracked_refresh"}
    catalog_next = jobs["catalog_refresh"].trigger.get_next_fire_time(None, MOMENT)
    tracked_next = jobs["tracked_refresh"].trigger.get_next_fire_time(None, MOMENT)
    assert catalog_next == datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    assert tracked_next == datetime(2026, 10, 22, 6, 15, tzinfo=UTC)


def test_jobs_never_overlap_themselves_and_merge_missed_runs() -> None:
    settings = make_settings()
    scheduler = worker.build_scheduler(
        worker.ScheduledJobs(cast(ScrapeService, StubService()), settings), settings
    )

    for job in scheduler.get_jobs():
        assert (job.max_instances, job.coalesce, job.misfire_grace_time) == (
            1,
            True,
            worker.MISFIRE_GRACE_SECONDS,
        )
        assert isinstance(job.trigger, CronTrigger)


def test_build_scheduler_adds_the_jobs_to_a_given_scheduler_and_returns_it() -> None:
    settings = make_settings()
    jobs = worker.ScheduledJobs(cast(ScrapeService, StubService()), settings)
    scheduler = AsyncIOScheduler(timezone=UTC)

    returned = worker.build_scheduler(jobs, settings, scheduler)

    assert returned is scheduler
    assert len(scheduler.get_jobs()) == 2


@pytest.mark.parametrize(
    ("field", "variable"),
    [
        ("catalog_refresh_cron", "CATALOG_REFRESH_CRON"),
        ("tracked_refresh_cron", "TRACKED_REFRESH_CRON"),
    ],
)
@pytest.mark.parametrize("bad", ["", "not a cron", "* * *", "61 * * * *", "0 25 * * *"])
def test_invalid_cron_fails_at_startup_naming_the_variable(
    field: str, variable: str, bad: str
) -> None:
    settings = make_settings(**{field: bad})
    jobs = worker.ScheduledJobs(cast(ScrapeService, StubService()), settings)

    with pytest.raises(ValueError, match=variable):
        worker.build_scheduler(jobs, settings)


def test_cron_is_interpreted_in_utc() -> None:
    trigger = worker.parse_cron("X", "0 0 * * *")

    assert trigger.get_next_fire_time(None, MOMENT) == datetime(2026, 10, 23, 0, 0, tzinfo=UTC)


# ---- chọn trang -------------------------------------------------------------------------------
def test_offline_mode_keeps_only_the_mock_shop(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = jobs_with(StubService(), monkeypatch, offline=True)

    assert jobs.sites() == [SiteKey.mockshop]


def test_online_mode_includes_every_enabled_site(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = jobs_with(StubService(), monkeypatch, offline=False)
    registry = default_registry()
    registry[SiteKey.anphat] = stub_scraper(SiteKey.anphat, [Category.mouse], enabled=False)
    monkeypatch.setattr(worker, "SCRAPERS", registry)

    assert jobs.sites() == [SiteKey.mockshop, SiteKey.gearvn, SiteKey.fptshop]


# ---- job danh mục -----------------------------------------------------------------------------
async def test_catalog_refresh_runs_every_category_of_every_site_as_scheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubService()
    jobs = jobs_with(service, monkeypatch, offline=False)

    results = await jobs.refresh_catalog()

    assert sorted((s.value, c.value) for s, c, _ in service.runs) == [
        ("fptshop", "laptop"),
        ("gearvn", "laptop"),
        ("gearvn", "mouse"),
        ("mockshop", "laptop"),
        ("mockshop", "mouse"),
    ]
    assert {trigger for _, _, trigger in service.runs} == {ScrapeTrigger.schedule}
    assert len(results) == 5


async def test_catalog_refresh_runs_sites_in_parallel_and_categories_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubService()
    jobs = jobs_with(service, monkeypatch, offline=False)

    await jobs.refresh_catalog()

    by_site: dict[SiteKey, list[Category]] = {}
    for site, category, _ in service.runs:
        by_site.setdefault(site, []).append(category)
    assert by_site[SiteKey.gearvn] == [Category.laptop, Category.mouse]
    # xen kẽ giữa các trang: nhóm đầu của cả ba trang chạy trước nhóm thứ hai của bất kỳ trang nào
    assert {site for site, _, _ in service.runs[:3]} == {
        SiteKey.mockshop,
        SiteKey.gearvn,
        SiteKey.fptshop,
    }


async def test_a_cooling_down_site_skips_its_remaining_categories_but_not_other_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubService({(SiteKey.gearvn, Category.laptop): SiteCooldown()})
    jobs = jobs_with(service, monkeypatch, offline=False)

    await jobs.refresh_catalog()

    ran = {(site, category) for site, category, _ in service.runs}
    assert (SiteKey.gearvn, Category.mouse) not in ran
    assert (SiteKey.mockshop, Category.mouse) in ran and (SiteKey.fptshop, Category.laptop) in ran


@pytest.mark.parametrize(
    "error",
    [ScrapeAlreadyRunning(), OfflineMode(), SiteNotAvailable("off"), RuntimeError("boom")],
)
async def test_one_failing_category_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    service = StubService({(SiteKey.gearvn, Category.laptop): error})
    jobs = jobs_with(service, monkeypatch, offline=False)

    results = await jobs.refresh_catalog()

    assert (SiteKey.gearvn, Category.mouse, ScrapeTrigger.schedule) in service.runs
    assert len(results) == 4


async def test_unexpected_errors_are_logged_with_a_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = StubService({(SiteKey.mockshop, Category.laptop): RuntimeError("boom")})
    jobs = jobs_with(service, monkeypatch, offline=True)

    with caplog.at_level(logging.ERROR, logger="worker"):
        await jobs.refresh_catalog()

    assert any(record.exc_info for record in caplog.records)


# ---- job theo dõi -----------------------------------------------------------------------------
async def test_tracked_refresh_visits_each_site_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service = StubService()
    jobs = jobs_with(service, monkeypatch, offline=False)

    results = await jobs.refresh_tracked()

    assert sorted(site.value for site in service.tracked) == ["fptshop", "gearvn", "mockshop"]
    assert len(results) == 3
    assert service.runs == []  # không thu thập danh mục


async def test_tracked_refresh_survives_a_failing_site(monkeypatch: pytest.MonkeyPatch) -> None:
    service = StubService(
        {(SiteKey.gearvn, None): RuntimeError("boom"), (SiteKey.fptshop, None): SiteCooldown()}
    )
    jobs = jobs_with(service, monkeypatch, offline=False)

    results = await jobs.refresh_tracked()

    assert [r.site for r in results] == [SiteKey.mockshop]


async def test_tracked_refresh_in_offline_mode_only_touches_the_mock_shop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubService()
    jobs = jobs_with(service, monkeypatch, offline=True)

    await jobs.refresh_tracked()

    assert service.tracked == [SiteKey.mockshop]


# ---- run_worker -------------------------------------------------------------------------------
class StubEvaluator:
    """Thay `AlertEvaluator`: ghi lại các lần quét `evaluate(None)`, có thể ném lỗi."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[object] = []

    async def evaluate(self, offer_ids: object = None) -> None:
        self.calls.append(offer_ids)
        if self.error is not None:
            raise self.error


class FakeRuntime:
    created: ClassVar[list["FakeRuntime"]] = []

    def __init__(self) -> None:
        self.service = StubService()
        self.alert_evaluator = StubEvaluator()
        self.live_search = None  # như ScrapeRuntime dựng tay: không có tầng 2
        self.closed = 0
        FakeRuntime.created.append(self)

    async def aclose(self) -> None:
        self.closed += 1


async def test_disabled_scheduler_exits_cleanly_without_building_anything(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("runtime must not be built when the scheduler is disabled")

    monkeypatch.setattr(ScrapeRuntime, "build", forbidden)

    with caplog.at_level(logging.WARNING, logger="worker"):
        code = await worker.run_worker(make_settings(scheduler_enabled=False), asyncio.Event())

    assert code == 0
    assert "SCHEDULER_ENABLED" in caplog.text


async def test_enabled_worker_runs_until_stopped_then_closes_the_runtime() -> None:
    runtime = FakeRuntime()
    stop = asyncio.Event()
    task = asyncio.create_task(
        worker.run_worker(make_settings(scheduler_enabled=True), stop, cast(ScrapeRuntime, runtime))
    )
    await asyncio.sleep(0.05)
    assert not task.done() and runtime.closed == 0

    stop.set()

    assert await task == 0
    assert runtime.closed == 1


async def test_an_invalid_cron_aborts_startup_but_still_closes_the_runtime() -> None:
    runtime = FakeRuntime()

    with pytest.raises(ValueError, match="CATALOG_REFRESH_CRON"):
        await worker.run_worker(
            make_settings(scheduler_enabled=True, catalog_refresh_cron="nope"),
            asyncio.Event(),
            cast(ScrapeRuntime, runtime),
        )

    assert runtime.closed == 1


async def test_main_loop_returns_exit_code_2_for_an_invalid_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeRuntime.created.clear()
    settings: Settings = make_settings(scheduler_enabled=True, tracked_refresh_cron="nope")
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(ScrapeRuntime, "build", lambda *a, **k: FakeRuntime())
    monkeypatch.setattr(worker, "build_spec_filler", lambda s: None)

    assert await worker._main() == 2
    assert FakeRuntime.created[0].closed == 1


def test_configure_logging_switches_the_console_streams_to_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)

    worker.configure_logging()

    assert stream.encoding == "utf-8"


# ---- quét cảnh báo sau job, hủy job khi tắt ------------------------------------------------------
def jobs_with_evaluator(
    service: StubService, evaluator: StubEvaluator, monkeypatch: pytest.MonkeyPatch
) -> worker.ScheduledJobs:
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    return worker.ScheduledJobs(
        cast(ScrapeService, service),
        make_settings(scraper_offline_only=True),
        cast(AlertEvaluator, evaluator),
    )


@pytest.mark.parametrize("job", ["refresh_catalog", "refresh_tracked"])
async def test_every_job_sweeps_all_alerts_once_after_the_scrape(
    monkeypatch: pytest.MonkeyPatch, job: str
) -> None:
    evaluator = StubEvaluator()
    jobs = jobs_with_evaluator(StubService(), evaluator, monkeypatch)

    await getattr(jobs, job)()

    assert evaluator.calls == [None]  # None = mọi cảnh báo còn hiệu lực


@pytest.mark.parametrize("job", ["refresh_catalog", "refresh_tracked"])
async def test_a_failing_alert_sweep_does_not_fail_the_job(
    monkeypatch: pytest.MonkeyPatch, job: str, caplog: pytest.LogCaptureFixture
) -> None:
    jobs = jobs_with_evaluator(StubService(), StubEvaluator(RuntimeError("smtp down")), monkeypatch)

    with caplog.at_level(logging.ERROR, logger="worker"):
        results = await getattr(jobs, job)()

    assert results  # kết quả thu thập vẫn trả về
    assert any(record.exc_info for record in caplog.records)


async def test_without_an_evaluator_jobs_just_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = jobs_with(StubService(), monkeypatch, offline=True)

    assert await jobs.refresh_tracked()  # không lỗi dù không có bộ đánh giá


class HangingService(StubService):
    """`run` không bao giờ xong cho tới khi bị hủy; ghi lại việc bị hủy."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def run(
        self, site: SiteKey, category: Category, *, trigger: ScrapeTrigger
    ) -> PipelineResult:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


async def test_cancel_running_cancels_in_flight_jobs_and_waits_for_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = HangingService()
    jobs = jobs_with(service, monkeypatch, offline=True)
    task = asyncio.create_task(jobs.refresh_catalog())
    await asyncio.sleep(0.05)
    assert not task.done()

    await jobs.cancel_running()

    assert task.cancelled() and service.cancelled
    await jobs.cancel_running()  # không còn gì để hủy: không lỗi


async def test_finished_jobs_are_forgotten_so_cancel_running_has_nothing_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubService()
    jobs = jobs_with(service, monkeypatch, offline=True)
    await jobs.refresh_catalog()

    await jobs.cancel_running()

    assert len(service.runs) == 2  # mock-shop có 2 nhóm trong registry giả; job không bị hủy


async def test_stopping_the_worker_sweeps_nothing_extra_and_closes_after_cancelling_jobs() -> None:
    runtime = FakeRuntime()
    stop = asyncio.Event()
    stop.set()

    assert (
        await worker.run_worker(
            make_settings(scheduler_enabled=True), stop, cast(ScrapeRuntime, runtime)
        )
        == 0
    )

    assert runtime.closed == 1 and runtime.alert_evaluator.calls == []  # chưa tới giờ chạy job


def test_default_crons_never_fire_at_the_same_minute() -> None:
    settings = make_settings()
    catalog = worker.parse_cron("A", settings.catalog_refresh_cron)
    tracked = worker.parse_cron("B", settings.tracked_refresh_cron)
    moment, fires_a, fires_b = MOMENT, set(), set()
    for _ in range(40):  # ~10 ngày
        moment_a = catalog.get_next_fire_time(None, moment)
        moment_b = tracked.get_next_fire_time(None, moment)
        assert moment_a is not None and moment_b is not None
        fires_a.add(moment_a)
        fires_b.add(moment_b)
        moment = min(moment_a, moment_b) + timedelta(seconds=1)

    assert fires_a and fires_b and not (fires_a & fires_b)
