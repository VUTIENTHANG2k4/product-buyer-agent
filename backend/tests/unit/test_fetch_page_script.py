"""scripts/fetch_page.py: lưu trang qua Fetcher, không gọi mạng thật (respx)."""

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
import respx

from app.config import get_settings
from app.domain.dto import ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.registry import SCRAPERS
from scripts.fetch_page import EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, main

MOCK = "http://localhost:8100"
SHOP = "https://shop.example"


class MockScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.mockshop, base_url=MOCK, min_delay_s=0.0, is_mock=True
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


class RealScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(key=SiteKey.gearvn, base_url=SHOP, min_delay_s=5.0)

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


@pytest.fixture(autouse=True)
def registered_sites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SCRAPERS, SiteKey.mockshop, MockScraper)
    monkeypatch.setitem(SCRAPERS, SiteKey.gearvn, RealScraper)
    monkeypatch.setattr("app.scrapers.http.fetcher.random.uniform", lambda a, b: 0.0)


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


def run(site: str, url: str, out: Path, *extra: str) -> int:
    return main(["--site", site, "--url", url, "--out", str(out), *extra])


def test_saves_the_page_html_to_the_output_file(http: respx.MockRouter, tmp_path: Path) -> None:
    http.get(f"{MOCK}/robots.txt").respond(404)
    http.get(f"{MOCK}/c/laptop").respond(200, text="<html>Mô tả</html>")
    out = tmp_path / "nested" / "listing.html"

    assert run("mockshop", f"{MOCK}/c/laptop", out) == EXIT_OK
    assert out.read_text(encoding="utf-8") == "<html>Mô tả</html>"


def test_real_site_is_refused_while_offline_without_the_flag(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    assert get_settings().scraper_offline_only is True
    out = tmp_path / "x.html"

    assert run("gearvn", f"{SHOP}/p", out) == EXIT_FAILED
    assert http.calls.call_count == 0
    assert not out.exists()


def test_allow_online_lets_this_one_command_reach_a_real_site(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(404)
    http.get(f"{SHOP}/p").respond(200, text="real")
    out = tmp_path / "x.html"

    assert run("gearvn", f"{SHOP}/p", out, "--allow-online") == EXIT_OK
    assert out.read_text(encoding="utf-8") == "real"
    assert get_settings().scraper_offline_only is True  # cấu hình chung không bị đổi


def test_robots_blocked_url_fails_without_writing(http: respx.MockRouter, tmp_path: Path) -> None:
    http.get(f"{SHOP}/robots.txt").respond(200, text="User-agent: *\nDisallow: /p")
    page = http.get(f"{SHOP}/p").respond(200)
    out = tmp_path / "x.html"

    assert run("gearvn", f"{SHOP}/p", out, "--allow-online") == EXIT_FAILED
    assert page.call_count == 0
    assert not out.exists()


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_pages_are_not_saved(http: respx.MockRouter, tmp_path: Path, status: int) -> None:
    http.get(f"{MOCK}/robots.txt").respond(404)
    http.get(f"{MOCK}/c").respond(status, text="denied", headers={"Retry-After": "86400"})
    out = tmp_path / "x.html"

    assert run("mockshop", f"{MOCK}/c", out) == EXIT_BLOCKED
    assert not out.exists()


def test_captcha_page_is_reported_as_blocked(http: respx.MockRouter, tmp_path: Path) -> None:
    http.get(f"{MOCK}/robots.txt").respond(404)
    http.get(f"{MOCK}/c").respond(200, text='<div id="captcha">ABCDE</div>')
    out = tmp_path / "x.html"

    assert run("mockshop", f"{MOCK}/c", out) == EXIT_BLOCKED
    assert not out.exists()


def test_url_outside_the_site_is_refused(http: respx.MockRouter, tmp_path: Path) -> None:
    assert run("mockshop", f"{SHOP}/p", tmp_path / "x.html") == EXIT_FAILED
    assert http.calls.call_count == 0


def test_site_without_a_registered_scraper_is_refused(
    http: respx.MockRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(SCRAPERS, SiteKey.gearvn)
    assert run("gearvn", f"{SHOP}/p", tmp_path / "x.html") == EXIT_FAILED


def test_missing_arguments_exit_with_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--site", "mockshop"])
    assert exit_info.value.code == 2
