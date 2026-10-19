"""Registry scraper (app/scrapers/registry.py)."""

from typing import ClassVar

import pytest

from app.domain.dto import ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers import registry
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.registry import SiteNotAvailable, get_scraper
from tests.fakes import FakeFetcher


def _scraper_class(key: SiteKey, *, enabled: bool = True) -> type[BaseScraper]:
    class Scraper(BaseScraper):
        config: ClassVar[SiteConfig] = SiteConfig(
            key=key, base_url="https://shop.example", min_delay_s=5, enabled=enabled
        )

        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage()

    return Scraper


def test_registered_site_returns_an_instance_of_its_scraper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls = _scraper_class(SiteKey.gearvn)
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.gearvn, cls)
    assert type(get_scraper(SiteKey.gearvn, FakeFetcher({}))) is cls


def test_unregistered_site_raises_site_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "SCRAPERS", {})
    with pytest.raises(SiteNotAvailable, match="gearvn"):
        get_scraper(SiteKey.gearvn, FakeFetcher({}))


def test_disabled_site_raises_site_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        registry.SCRAPERS, SiteKey.hoangha, _scraper_class(SiteKey.hoangha, enabled=False)
    )
    with pytest.raises(SiteNotAvailable, match="disabled"):
        get_scraper(SiteKey.hoangha, FakeFetcher({}))


def test_scraper_filed_under_another_sites_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.hoangha, _scraper_class(SiteKey.gearvn))
    with pytest.raises(SiteNotAvailable, match="another site"):
        get_scraper(SiteKey.hoangha, FakeFetcher({}))


def test_site_not_available_is_a_lookup_error() -> None:
    assert issubclass(SiteNotAvailable, LookupError)


def test_every_registered_scraper_is_filed_under_its_own_site_key() -> None:
    for key, cls in registry.SCRAPERS.items():
        assert cls.config.key == key
