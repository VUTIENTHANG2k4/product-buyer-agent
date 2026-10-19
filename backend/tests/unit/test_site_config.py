"""SiteConfig (app/scrapers/base.py): kiểm tra khi khởi tạo, bất biến."""

import dataclasses
import math
from typing import Any

import pytest

from app.domain.enums import Category, SiteKey
from app.scrapers.base import SiteConfig

BASE = "https://shop.example"


def _config(**overrides: Any) -> SiteConfig:
    data: dict[str, Any] = {"key": SiteKey.gearvn, "base_url": BASE, "min_delay_s": 5.0}
    data.update(overrides)
    return SiteConfig(**data)


def test_defaults_match_the_documented_interface() -> None:
    config = _config()
    assert config.requires_js is False
    assert config.supports_live_search is False
    assert config.is_mock is False
    assert config.enabled is True
    assert dict(config.categories) == {}


def test_valid_config_keeps_category_urls() -> None:
    config = _config(categories={Category.laptop: f"{BASE}/collections/laptop"})
    assert config.categories[Category.laptop] == f"{BASE}/collections/laptop"


@pytest.mark.parametrize("delay", [-1.0, -0.001, math.nan, math.inf, -math.inf])
def test_min_delay_must_be_finite_and_non_negative(delay: float) -> None:
    with pytest.raises(ValueError, match="min_delay_s"):
        _config(min_delay_s=delay)


def test_zero_delay_is_allowed_for_mock_shop() -> None:
    assert _config(min_delay_s=0.0, is_mock=True).min_delay_s == 0.0


@pytest.mark.parametrize("url", ["", "shop.example", "ftp://shop.example", "https://", "/relative"])
def test_base_url_must_be_absolute_http(url: str) -> None:
    with pytest.raises(ValueError, match="absolute http"):
        _config(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example/laptop",
        "https://shop.example.evil.test/x",
        "http://shop.example:8080/",
    ],
)
def test_category_url_on_another_host_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="outside"):
        _config(categories={Category.laptop: url})


def test_host_comparison_ignores_case() -> None:
    config = _config(categories={Category.laptop: "https://SHOP.example/laptop"})
    assert Category.laptop in config.categories


def test_config_is_frozen() -> None:
    config = _config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.enabled = False  # type: ignore[misc]


def test_categories_are_copied_and_read_only() -> None:
    source = {Category.laptop: f"{BASE}/laptop"}
    config = _config(categories=source)
    source[Category.mouse] = f"{BASE}/mouse"
    assert Category.mouse not in config.categories
    with pytest.raises(TypeError):
        config.categories[Category.mouse] = f"{BASE}/mouse"  # type: ignore[index]
