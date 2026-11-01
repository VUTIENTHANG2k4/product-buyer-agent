"""QA M2: tham số lạ và mã thoát của scripts/fetch_page.py và scripts/scrape.py (không mạng)."""

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import ClassVar

import pytest
import respx
from sqlmodel import Session, select

from app.config import Settings
from app.db.models import ScrapeRun
from app.domain.dto import ListingPage
from app.domain.enums import Category, ScrapeStatus, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.pipeline import ScrapePipeline
from app.scrapers.registry import SCRAPERS
from app.services.scrape_service import ScrapeService
from scripts import fetch_page
from scripts.scrape import EXIT_FAILED, EXIT_NEEDS_HUMAN, EXIT_OK, main, run_command
from tests.integration.test_pipeline import Clock, mock_fetcher

MOCK = "http://localhost:8100"


class MockScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.mockshop, base_url=MOCK, min_delay_s=0.0, is_mock=True
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def fetch_page_sites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SCRAPERS, SiteKey.mockshop, MockScraper)


def fetch(url: str, out: Path) -> int:
    return fetch_page.main(["--site", "mockshop", "--url", url, "--out", str(out)])


# --- fetch_page -------------------------------------------------------------------------------


def test_an_unwritable_output_path_is_a_clean_failure_not_a_traceback(
    http: respx.MockRouter, fetch_page_sites: None, tmp_path: Path
) -> None:
    http.get(f"{MOCK}/robots.txt").respond(404)
    http.get(f"{MOCK}/c/laptop").respond(200, text="<html></html>")

    assert fetch(f"{MOCK}/c/laptop", tmp_path) == fetch_page.EXIT_FAILED


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pw@localhost:8100/c/laptop",
        "http://localhost:8100@evil.example/c/laptop",
        "http://localhost:8100.evil.example/c/laptop",
        "http://localhost:8101/c/laptop",
        "ftp://localhost:8100/c/laptop",
        "localhost:8100/c/laptop",
    ],
)
def test_urls_that_only_look_like_the_site_are_refused_without_a_request_or_a_file(
    http: respx.MockRouter, fetch_page_sites: None, tmp_path: Path, url: str
) -> None:
    out = tmp_path / "page.html"

    assert fetch(url, out) == fetch_page.EXIT_FAILED
    assert http.calls.call_count == 0 and not out.exists()


def test_a_missing_page_or_robots_block_never_leaves_a_file(
    http: respx.MockRouter, fetch_page_sites: None, tmp_path: Path
) -> None:
    http.get(f"{MOCK}/robots.txt").respond(200, text="User-agent: *\nDisallow: /admin\n")
    http.get(f"{MOCK}/c/missing").respond(404, text="no")
    admin = http.get(f"{MOCK}/admin/x").respond(200, text="secret")
    out = tmp_path / "page.html"

    assert fetch(f"{MOCK}/c/missing", out) == fetch_page.EXIT_FAILED
    assert fetch(f"{MOCK}/admin/x", out) == fetch_page.EXIT_FAILED
    assert admin.call_count == 0 and not out.exists()


# --- scrape: tham số --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--site", "mockshop", "--category", "laptop", "--pages", "-1"],
        ["--site", "mockshop", "--category", "laptop", "--pages", "abc"],
        ["--site", "mockshop", "--category", "laptop", "--pages", "1.5"],
        ["--site", "mockshop", "--category", "laptop", "--pages", ""],
        ["--site", "mockshop", "--category", "laptop", "--resume", "x", "--answer", "A"],
        ["--site", "mockshop", "--category", "laptop", "--resume", "3", "--answer", ""],
        ["--site", "MOCKSHOP", "--category", "laptop"],
        ["--site", "mockshop", "--category", "laptop", "--unknown-flag"],
    ],
)
def test_bad_scrape_arguments_exit_with_usage_error_before_touching_anything(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


# --- scrape: kết cục --------------------------------------------------------------------------


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def service(factory: Callable[[], Session], fetcher: object, clock: Clock) -> ScrapeService:
    settings = Settings(scraper_offline_only=True, scraper_max_listing_pages=5)
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)  # type: ignore[arg-type]
    return ScrapeService(factory, fetcher, settings, pipeline=pipe)  # type: ignore[arg-type]


async def test_resuming_with_a_page_limit_below_the_resume_page_exits_1_without_a_traceback(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, mock_fetcher(captcha_after=1), clock)
    first = await run_command(
        svc,
        site=SiteKey.mockshop,
        category=Category.laptop,
        pages=None,
        resume_run=None,
        answer=None,
        ask=None,
    )
    assert first == EXIT_NEEDS_HUMAN
    db_session.expire_all()
    paused = db_session.exec(select(ScrapeRun)).one()
    assert paused.id is not None and paused.challenge is not None
    code = re.search(r"[A-Z2-9]{5}$", str(paused.challenge["prompt"]))
    assert code and paused.pages_fetched == 1

    outcome = await run_command(
        svc,
        site=SiteKey.mockshop,
        category=Category.laptop,
        pages=1,
        resume_run=paused.id,
        answer=code.group(0),
        ask=None,
    )

    assert outcome == EXIT_FAILED
    db_session.expire_all()
    assert db_session.get(ScrapeRun, paused.id).status is ScrapeStatus.NEEDS_HUMAN  # type: ignore[union-attr]


async def test_a_category_run_that_succeeds_exits_0_even_when_it_is_the_second_time(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, mock_fetcher(), clock)
    for _ in range(2):
        code = await run_command(
            svc,
            site=SiteKey.mockshop,
            category=Category.mouse,
            pages=None,
            resume_run=None,
            answer=None,
            ask=None,
        )
        assert code == EXIT_OK
    db_session.expire_all()
    assert [run.status for run in db_session.exec(select(ScrapeRun))] == [
        ScrapeStatus.SUCCEEDED,
        ScrapeStatus.SUCCEEDED,
    ]
