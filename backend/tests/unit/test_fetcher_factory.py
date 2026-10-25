"""build_fetcher (app/scrapers/http/factory.py)."""

from typing import ClassVar

import pytest

from app.domain.dto import ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.factory import RAW_CACHE_DIR, site_delays
from app.scrapers.registry import SCRAPERS


class Slow(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.nguyenkim, base_url="https://Slow.Example", min_delay_s=10.0
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


def test_site_delays_come_from_the_registered_site_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(SCRAPERS, SiteKey.nguyenkim, Slow)
    assert site_delays()["slow.example"] == 10.0


def test_raw_cache_lives_under_backend_data_raw() -> None:
    assert RAW_CACHE_DIR.parts[-3:] == ("backend", "data", "raw")
