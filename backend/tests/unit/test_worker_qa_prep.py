"""QA "Chuẩn bị bảo vệ" (T10.4): thứ tự và độ bền của bước dọn cache trong job làm mới danh mục."""

import asyncio
import logging
from typing import cast

import pytest

from app import worker
from app.services.alert_evaluation import AlertEvaluator
from app.services.live_search_service import LiveSearchService
from app.services.scrape_service import ScrapeService
from tests.service_support import make_settings
from tests.unit.test_worker import StubService, default_registry
from tests.unit.test_worker_t104 import StubLiveSearch


class OrderedEvaluator:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def evaluate(self, offer_ids: object) -> None:
        self.order.append("sweep")


class OrderedLive(StubLiveSearch):
    def __init__(self, order: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.order = order

    async def purge_expired(self) -> int:
        self.order.append("purge")
        return await super().purge_expired()


def make_jobs(
    live: StubLiveSearch | None, monkeypatch: pytest.MonkeyPatch, evaluator: object = None
) -> worker.ScheduledJobs:
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    return worker.ScheduledJobs(
        cast(ScrapeService, StubService()),
        make_settings(scraper_offline_only=True),
        cast(AlertEvaluator | None, evaluator),
        cast(LiveSearchService | None, live),
    )


async def test_the_purge_runs_after_the_alert_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    jobs = make_jobs(OrderedLive(order), monkeypatch, OrderedEvaluator(order))

    await jobs.refresh_catalog()

    assert order == ["sweep", "purge"]


async def test_a_zero_removal_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    live = StubLiveSearch(removed=0)

    with caplog.at_level(logging.INFO, logger="worker"):
        await make_jobs(live, monkeypatch).refresh_catalog()

    assert live.calls == 1
    assert not any("cache" in record.getMessage() for record in caplog.records)


async def test_cancelling_the_job_during_the_purge_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    class Hanging(StubLiveSearch):
        async def purge_expired(self) -> int:
            entered.set()
            await asyncio.sleep(3600)
            return 0

    jobs = make_jobs(Hanging(), monkeypatch)
    task = asyncio.create_task(jobs.refresh_catalog())
    await entered.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_failing_sweep_does_not_stop_the_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Failing:
        async def evaluate(self, offer_ids: object) -> None:
            raise RuntimeError("smtp down")

    live = StubLiveSearch()

    await make_jobs(live, monkeypatch, Failing()).refresh_catalog()

    assert live.calls == 1


async def test_the_purge_still_runs_when_no_site_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = StubLiveSearch()
    jobs = make_jobs(live, monkeypatch)
    monkeypatch.setattr(worker, "SCRAPERS", {})

    assert await jobs.refresh_catalog() == []
    assert live.calls == 1
