"""T10.4a: worker dọn cache tìm kiếm trực tiếp hết hạn sau mỗi lượt làm mới danh mục."""

import logging
from typing import cast

import pytest

from app import worker
from app.services.live_search_service import LiveSearchService
from app.services.scrape_service import ScrapeService
from tests.service_support import make_settings
from tests.unit.test_worker import StubService, default_registry


class StubLiveSearch:
    def __init__(self, error: Exception | None = None, removed: int = 3) -> None:
        self.calls = 0
        self._error = error
        self._removed = removed

    async def purge_expired(self) -> int:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._removed


def jobs(live: StubLiveSearch, monkeypatch: pytest.MonkeyPatch) -> worker.ScheduledJobs:
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    return worker.ScheduledJobs(
        cast(ScrapeService, StubService()),
        make_settings(scraper_offline_only=True),
        live_search=cast(LiveSearchService, live),
    )


async def test_catalog_refresh_purges_the_live_search_cache_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    live = StubLiveSearch()

    with caplog.at_level(logging.INFO, logger="worker"):
        await jobs(live, monkeypatch).refresh_catalog()

    assert live.calls == 1
    assert any("3 mục cache" in record.getMessage() for record in caplog.records)


async def test_tracked_refresh_does_not_purge(monkeypatch: pytest.MonkeyPatch) -> None:
    live = StubLiveSearch()

    await jobs(live, monkeypatch).refresh_tracked()

    assert live.calls == 0


async def test_a_failing_purge_is_logged_and_the_job_still_returns_its_results(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    live = StubLiveSearch(RuntimeError("db down"))

    with caplog.at_level(logging.ERROR, logger="worker"):
        results = await jobs(live, monkeypatch).refresh_catalog()

    assert results and live.calls == 1
    assert any(record.exc_info for record in caplog.records)


async def test_without_a_live_search_service_the_job_just_scrapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "SCRAPERS", default_registry())
    plain = worker.ScheduledJobs(
        cast(ScrapeService, StubService()), make_settings(scraper_offline_only=True)
    )

    assert await plain.refresh_catalog()
