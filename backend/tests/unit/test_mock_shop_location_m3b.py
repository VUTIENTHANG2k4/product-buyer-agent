"""M3b/T2.7a: import `app.scrapers.registry` không cần đủ cấu hình (chỉ `MOCK_SHOP_URL`)."""

import importlib
import sys
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

import app.config as config
from app.config import MockShopLocation, Settings


@pytest.fixture
def no_full_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`get_settings()` ném lỗi như khi thiếu DATABASE_URL; khôi phục module sau test."""

    def boom() -> Settings:
        raise AssertionError("get_settings() must not be called while importing scrapers")

    monkeypatch.setattr(config, "get_settings", boom)
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("app.scrapers.sites") or name == "app.scrapers.registry"
    }
    for name in saved:
        del sys.modules[name]
    yield
    for name in [n for n in sys.modules if n.startswith("app.scrapers.sites")]:
        del sys.modules[name]
    sys.modules.pop("app.scrapers.registry", None)
    sys.modules.update(saved)


def test_importing_the_scraper_registry_does_not_read_the_full_settings(
    no_full_settings: None,
) -> None:
    registry = importlib.import_module("app.scrapers.registry")

    assert "mockshop" in {site.value for site in registry.SCRAPERS}


def test_mock_shop_scraper_config_follows_mock_shop_url(
    monkeypatch: pytest.MonkeyPatch, no_full_settings: None
) -> None:
    config.get_mock_shop_url.cache_clear()
    monkeypatch.setenv("MOCK_SHOP_URL", "http://127.0.0.1:9100/")
    try:
        module = importlib.import_module("app.scrapers.sites.mockshop")
        assert module.MockShopScraper.config.base_url == "http://127.0.0.1:9100"
        assert module.MockShopScraper.config.categories[module.Category.laptop] == (
            "http://127.0.0.1:9100/c/laptop"
        )
    finally:
        config.get_mock_shop_url.cache_clear()


def test_both_settings_classes_read_the_same_mock_shop_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_SHOP_URL", "http://localhost:8123/")

    assert MockShopLocation().mock_shop_url == "http://localhost:8123"
    assert Settings().mock_shop_url == "http://localhost:8123"


@pytest.mark.parametrize(
    "url", ["https://shop.example", "ftp://localhost", "http://evil.test:8100"]
)
def test_mock_shop_location_rejects_non_local_urls_like_settings(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("MOCK_SHOP_URL", url)

    with pytest.raises(ValidationError):
        MockShopLocation()
    with pytest.raises(ValidationError):
        Settings()


def test_mock_shop_location_works_without_any_other_required_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("DATABASE_URL", "SCRAPER_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(MockShopLocation.model_config, "env_file", None)
    monkeypatch.delenv("MOCK_SHOP_URL", raising=False)

    assert MockShopLocation().mock_shop_url == "http://localhost:8100"
