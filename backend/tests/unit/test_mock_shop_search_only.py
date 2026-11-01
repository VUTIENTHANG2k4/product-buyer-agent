"""Mock-shop nhóm tầng 2 (T10.2): sản phẩm `search_only` chỉ có ở /search và trang chi tiết."""

import re
from collections.abc import AsyncIterator

import httpx
import pytest

from app.mock_shop.catalog import (
    CATEGORIES,
    SEARCH_ONLY_CATEGORIES,
    fold,
    load_catalog,
    load_search_catalog,
    search,
)
from app.mock_shop.main import create_app

BASE = "http://mock.test"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(captcha_after=10_000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
        yield http


def card_slugs(page: str) -> list[str]:
    return re.findall(r'<li class="product-card" data-slug="([^"]+)"', page)


def test_search_catalog_adds_ten_fictional_products_without_touching_tier_one() -> None:
    extras = load_search_catalog()[len(load_catalog()) :]

    assert len(load_catalog()) == 60 and len(load_search_catalog()) == 70
    assert load_search_catalog()[:60] == load_catalog()
    assert len(extras) == 10
    assert {p.category for p in extras} == set(SEARCH_ONLY_CATEGORIES)
    assert not set(SEARCH_ONLY_CATEGORIES) & set(CATEGORIES)
    assert all("Mock" in p.name for p in extras)
    assert len({p.slug for p in load_search_catalog()}) == 70


def test_search_only_products_include_cases_for_price_filters() -> None:
    speakers = [p for p in load_search_catalog() if p.category == "speaker"]

    assert len(speakers) == 5
    assert any(p.price is None for p in speakers)  # "Liên hệ": bị bỏ khi lọc giá
    assert any(p.price is not None and p.price < 1_000_000 for p in speakers)
    assert any(p.price is not None and p.price > 1_000_000 for p in speakers)
    assert any(p.list_price is not None for p in speakers)


def test_tier_one_search_does_not_see_the_search_only_products() -> None:
    assert search(load_catalog(), "loa bluetooth") == []
    assert len(search(load_search_catalog(), "loa bluetooth")) == 5
    assert fold("Ổ cứng") == "o cung"  # tìm không dấu ra "Ổ cứng SSD"
    assert len(search(load_search_catalog(), "o cung ssd")) == 3


async def test_search_endpoint_lists_speakers_in_catalog_order(client: httpx.AsyncClient) -> None:
    response = await client.get("/search", params={"q": "loa bluetooth"})

    assert response.status_code == 200
    assert card_slugs(response.text) == [
        p.slug for p in load_search_catalog() if p.category == "speaker"
    ]


async def test_search_only_product_has_a_detail_page(client: httpx.AsyncClient) -> None:
    product = next(p for p in load_search_catalog() if p.category == "monitor")

    response = await client.get(f"/p/{product.slug}")

    assert response.status_code == 200
    assert product.name in response.text


@pytest.mark.parametrize("category", SEARCH_ONLY_CATEGORIES)
async def test_search_only_categories_have_no_category_page(
    client: httpx.AsyncClient, category: str
) -> None:
    assert (await client.get(f"/c/{category}")).status_code == 404


async def test_tier_one_category_pages_still_list_only_tier_one(client: httpx.AsyncClient) -> None:
    response = await client.get("/c/laptop")

    slugs = card_slugs(response.text)
    assert slugs and all(slug in {p.slug for p in load_catalog()} for slug in slugs)


async def test_search_with_no_match_returns_no_cards(client: httpx.AsyncClient) -> None:
    response = await client.get("/search", params={"q": "zzqxnotfound"})

    assert response.status_code == 200 and card_slugs(response.text) == []
