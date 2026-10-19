"""M3b/T3.4: liên kết trang sau có `rel` nhiều giá trị (`rel="prev next"`) vẫn được nhận."""

import pytest

from app.domain.enums import Category
from app.scrapers.sites.gearvn import GearVNScraper
from app.scrapers.sites.mockshop import MockShopScraper
from tests.fakes import FakeFetcher

GEARVN_PAGE = "https://gearvn.com/collections/chuot-may-tinh?page=2"
MOCK_PAGE = "http://localhost:8100/c/laptop?page=2"


@pytest.mark.parametrize("rel", ["next", "prev next", "next prev", "NEXT", "nofollow next"])
def test_gearvn_next_link_is_found_whatever_the_rel_tokens(rel: str) -> None:
    html = f'<html><head><link rel="{rel}" href="/collections/chuot-may-tinh?page=3"></head></html>'

    page = GearVNScraper(FakeFetcher({})).parse_listing(html, Category.mouse, GEARVN_PAGE)

    assert page.has_next is True
    assert str(page.next_url) == "https://gearvn.com/collections/chuot-may-tinh?page=3"


@pytest.mark.parametrize("rel", ["prev", "canonical", "nextpage", ""])
def test_gearvn_link_without_a_next_token_is_not_a_next_page(rel: str) -> None:
    html = f'<html><head><link rel="{rel}" href="/collections/chuot-may-tinh?page=1"></head></html>'

    page = GearVNScraper(FakeFetcher({})).parse_listing(html, Category.mouse, GEARVN_PAGE)

    assert (page.has_next, page.next_url) == (False, None)


@pytest.mark.parametrize("rel", ["next", "prev next"])
def test_mock_shop_next_link_is_found_whatever_the_rel_tokens(rel: str) -> None:
    html = f'<html><body><a rel="{rel}" href="/c/laptop?page=3">Trang sau</a></body></html>'

    page = MockShopScraper(FakeFetcher({})).parse_listing(html, Category.laptop, MOCK_PAGE)

    assert page.has_next is True
    assert str(page.next_url) == "http://localhost:8100/c/laptop?page=3"
