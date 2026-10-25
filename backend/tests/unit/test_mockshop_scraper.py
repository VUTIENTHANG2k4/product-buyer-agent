"""MockShopScraper (app/scrapers/sites/mockshop.py) trên fixture HTML và trên mock-shop qua ASGI."""

import re
from pathlib import Path

import httpx
import pytest

from app.domain.dto import ListingItem
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.mock_shop.catalog import load_catalog
from app.mock_shop.main import create_app
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.types import FetchResponse
from app.scrapers.registry import SCRAPERS, get_scraper
from app.scrapers.sites.mockshop import MockShopScraper
from scripts.save_mockshop_fixtures import FIXTURE_DIR, render
from tests.fakes import FakeFetcher

BASE = "http://localhost:8100"
LAPTOP_P1 = f"{BASE}/c/laptop"
CATALOG = {product.slug: product for product in load_catalog()}


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def detail_fixture(*, priced: bool) -> tuple[str, str]:
    """(tên file, slug) của trang chi tiết đã lưu cho sản phẩm có/không có giá."""
    for path in sorted(FIXTURE_DIR.glob("detail_*.html")):
        slug = path.stem.removeprefix("detail_")
        if (CATALOG[slug].price is not None) == priced:
            return path.name, slug
    raise LookupError("fixture not found")


@pytest.fixture
def scraper() -> MockShopScraper:
    return MockShopScraper(FakeFetcher({}))


@pytest.fixture
def laptop_page(scraper: MockShopScraper) -> tuple[list[ListingItem], bool, str | None]:
    page = scraper.parse_listing(fixture("listing_laptop_p1.html"), Category.laptop, LAPTOP_P1)
    return page.items, page.has_next, str(page.next_url) if page.next_url else None


# --- Cấu hình, đăng ký ------------------------------------------------------------------------


def test_config_describes_the_mock_shop() -> None:
    config = MockShopScraper.config
    assert (config.key, config.is_mock, config.supports_live_search) == (
        SiteKey.mockshop,
        True,
        True,
    )
    assert config.min_delay_s == 0.0
    assert set(config.categories) == {
        Category.laptop,
        Category.mouse,
        Category.keyboard,
        Category.headset,
    }
    assert config.categories[Category.laptop] == f"{BASE}/c/laptop"


def test_scraper_is_registered_and_buildable(scraper: MockShopScraper) -> None:
    assert SCRAPERS[SiteKey.mockshop] is MockShopScraper
    assert isinstance(get_scraper(SiteKey.mockshop, FakeFetcher({})), MockShopScraper)


def test_search_url_encodes_the_query(scraper: MockShopScraper) -> None:
    assert scraper.search_url("chuột razer") == f"{BASE}/search?q=chu%E1%BB%99t+razer"


# --- parse_listing ----------------------------------------------------------------------------


def test_listing_page_one_has_twelve_items_and_a_next_page(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    items, has_next, next_url = laptop_page
    assert len(items) == 12
    assert has_next is True
    assert next_url == f"{LAPTOP_P1}?page=2"


def test_first_item_has_every_field(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    first = laptop_page[0][0]
    expected = CATALOG["asus-mock-strix-15-x01-mk-la001"]

    assert first.site is SiteKey.mockshop
    assert str(first.url) == f"{BASE}/p/{expected.slug}"
    assert first.title == expected.name
    assert first.price == expected.price
    assert first.list_price is None
    assert first.price_type is PriceType.regular
    assert first.stock_status is StockStatus.in_stock
    assert str(first.image_url) == f"{BASE}/static/{expected.slug}.jpg"
    assert (first.rating, first.rating_count) == (expected.rating, expected.rating_count)
    assert first.site_sku == expected.sku
    assert first.category_hint is Category.laptop
    assert first.raw_specs == dict(list(expected.specs.items())[:3])


def test_every_price_is_a_positive_integer_or_none(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    for item in laptop_page[0]:
        assert item.price is None or (type(item.price) is int and item.price > 0)


def test_items_follow_catalog_order_and_match_catalog_data(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    expected = [p for p in load_catalog() if p.category == "laptop"][:12]
    items = laptop_page[0]
    assert [i.title for i in items] == [p.name for p in expected]
    assert [i.price for i in items] == [p.price for p in expected]
    assert [i.stock_status is StockStatus.in_stock for i in items] == [p.in_stock for p in expected]


def test_discounted_item_is_a_sale_with_list_price_above_price(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    sales = [i for i in laptop_page[0] if i.price_type is PriceType.sale]
    assert sales
    for item in sales:
        assert item.price is not None and item.list_price is not None
        assert item.list_price > item.price


def test_contact_price_item_has_no_price_and_unknown_type(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    contact = next(p for p in load_catalog() if p.price is None)
    item = next(i for i in laptop_page[0] if i.title == contact.name)
    assert (item.price, item.list_price, item.price_type) == (None, None, PriceType.unknown)
    assert item.rating is None


def test_out_of_stock_item_is_reported_out_of_stock(
    laptop_page: tuple[list[ListingItem], bool, str | None],
) -> None:
    sold_out = next(p for p in load_catalog() if p.category == "laptop" and not p.in_stock)
    item = next(i for i in laptop_page[0] if i.title == sold_out.name)
    assert item.stock_status is StockStatus.out_of_stock


def test_last_page_has_the_remaining_items_and_no_next(scraper: MockShopScraper) -> None:
    page = scraper.parse_listing(
        fixture("listing_laptop_p3.html"), Category.laptop, f"{LAPTOP_P1}?page=3"
    )
    assert len(page.items) == 2
    assert (page.has_next, page.next_url) == (False, None)


def test_a_single_full_page_has_no_next(scraper: MockShopScraper) -> None:
    page = scraper.parse_listing(
        fixture("listing_mouse_p1.html"), Category.mouse, f"{BASE}/c/mouse"
    )
    assert len(page.items) == 12
    assert page.has_next is False
    assert {i.category_hint for i in page.items} == {Category.mouse}


def test_empty_page_has_no_items_and_no_next(scraper: MockShopScraper) -> None:
    page = scraper.parse_listing(fixture("listing_empty.html"), Category.laptop, LAPTOP_P1)
    assert (page.items, page.has_next, page.skipped) == ([], False, 0)


def test_html_cards_alone_give_the_same_items_when_json_ld_is_missing(
    scraper: MockShopScraper,
) -> None:
    html = fixture("listing_laptop_p1.html")
    without_ld = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    assert "ld+json" not in without_ld

    with_ld = scraper.parse_listing(html, Category.laptop, LAPTOP_P1).items
    cards_only = scraper.parse_listing(without_ld, Category.laptop, LAPTOP_P1).items

    assert [(i.title, i.price, i.stock_status, str(i.url)) for i in cards_only] == [
        (i.title, i.price, i.stock_status, str(i.url)) for i in with_ld
    ]


def test_corrupt_json_ld_does_not_break_parsing(scraper: MockShopScraper) -> None:
    html = re.sub(
        r'(<script type="application/ld\+json">).*?(</script>)',
        r"\1{not json\2",
        fixture("listing_laptop_p1.html"),
        flags=re.S,
    )
    page = scraper.parse_listing(html, Category.laptop, LAPTOP_P1)
    assert len(page.items) == 12
    assert page.items[0].price == CATALOG["asus-mock-strix-15-x01-mk-la001"].price


def test_unreadable_cards_are_skipped_and_counted(scraper: MockShopScraper) -> None:
    html = fixture("listing_laptop_p1.html")
    html = html.replace('<a class="product-link" href="/p/', '<a class="broken" href="/p/', 1)
    # thẻ đầu mất liên kết, thẻ thứ hai mất tên
    html = re.sub(
        r'(<li class="product-card" data-slug="acer[^>]*>.*?)<h2 class="product-name">[^<]*</h2>',
        r'\1<h2 class="product-name"> </h2>',
        html,
        count=1,
        flags=re.S,
    )

    page = scraper.parse_listing(html, Category.laptop, LAPTOP_P1)

    assert page.skipped == 2
    assert len(page.items) == 10


def test_malformed_numbers_on_the_card_become_none_instead_of_failing(
    scraper: MockShopScraper,
) -> None:
    html = fixture("listing_laptop_p1.html")
    html = re.sub(r'(<script type="application/ld\+json">).*?(</script>)', "", html, flags=re.S)
    html = html.replace('data-rating="4.5"', 'data-rating="abc"').replace(
        'data-count="9"', 'data-count="-3"'
    )
    page = scraper.parse_listing(html, Category.laptop, LAPTOP_P1)
    assert (page.items[0].rating, page.items[0].rating_count) == (None, None)


def test_html_in_titles_is_returned_as_plain_text(scraper: MockShopScraper) -> None:
    html = (
        '<ul><li class="product-card" data-slug="x" data-sku="S1">'
        '<a class="product-link" href="/p/x">'
        '<h2 class="product-name">A &lt;b&gt;B&lt;/b&gt; &amp; C</h2></a>'
        '<span class="price">1.000.000₫</span></li></ul>'
    )
    item = scraper.parse_listing(html, Category.mouse, BASE).items[0]
    assert item.title == "A <b>B</b> & C"
    assert item.price == 1_000_000


def test_tracking_parameters_are_removed_from_item_urls(scraper: MockShopScraper) -> None:
    html = (
        '<li class="product-card"><a class="product-link" href="/p/x?utm_source=a&amp;v=1#f">'
        '<h2 class="product-name">Chuột</h2></a><span class="price">990.000₫</span></li>'
    )
    item = scraper.parse_listing(html, Category.mouse, BASE).items[0]
    assert str(item.url) == f"{BASE}/p/x?v=1"


# --- parse_detail, parse_search ---------------------------------------------------------------


def test_detail_has_specs_model_code_and_brand(scraper: MockShopScraper) -> None:
    name, slug = detail_fixture(priced=True)
    product = CATALOG[slug]

    detail = scraper.parse_detail(fixture(name), f"{BASE}/p/{slug}?utm_source=x")

    assert str(detail.url) == f"{BASE}/p/{slug}"
    assert detail.raw_specs == product.specs
    assert detail.model_code_hint == product.sku
    assert detail.brand_hint == product.brand


def test_detail_without_a_price_still_parses(scraper: MockShopScraper) -> None:
    name, slug = detail_fixture(priced=False)
    detail = scraper.parse_detail(fixture(name), f"{BASE}/p/{slug}")
    assert detail.raw_specs == CATALOG[slug].specs


def test_detail_of_an_empty_page_has_no_specs_and_no_hints(scraper: MockShopScraper) -> None:
    detail = scraper.parse_detail("<html></html>", f"{BASE}/p/x")
    assert (detail.raw_specs, detail.model_code_hint, detail.brand_hint) == ({}, None, None)


def test_search_results_parse_like_a_listing(scraper: MockShopScraper) -> None:
    items = scraper.parse_search(fixture("search_chuot_razer.html"), f"{BASE}/search?q=chuot+razer")
    assert items
    assert all("Razer" in i.title and i.title.startswith("Chuột") for i in items)


# --- Challenge --------------------------------------------------------------------------------


def response(text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=LAPTOP_P1, final_url=LAPTOP_P1, status=status, text=text)


def test_captcha_page_gives_a_challenge_with_prompt_and_token(scraper: MockShopScraper) -> None:
    challenge = scraper.detect_challenge(response(fixture("captcha.html")))

    assert challenge is not None
    assert (challenge.kind, challenge.site) == (ChallengeKind.captcha, SiteKey.mockshop)
    assert challenge.token == "FIXTURETOKEN"
    assert challenge.prompt is not None and "AB3XY" in challenge.prompt


def test_normal_pages_are_not_challenges(scraper: MockShopScraper) -> None:
    for name in ("listing_laptop_p1.html", "listing_empty.html", "search_chuot_razer.html"):
        assert scraper.detect_challenge(response(fixture(name))) is None


def test_http_errors_stay_plain_challenges_without_prompt(scraper: MockShopScraper) -> None:
    challenge = scraper.detect_challenge(response("denied", status=403))
    assert challenge is not None
    assert challenge.kind is ChallengeKind.http_403
    assert (challenge.prompt, challenge.token) == (None, None)


def test_captcha_marker_without_the_box_is_still_a_challenge(scraper: MockShopScraper) -> None:
    challenge = scraper.detect_challenge(response('<p class="captcha">Please solve the captcha</p>'))
    assert challenge is not None
    assert (challenge.kind, challenge.prompt, challenge.token) == (
        ChallengeKind.captcha,
        None,
        None,
    )


# --- Trên mock-shop thật qua ASGI -------------------------------------------------------------


class AsgiFetcher:
    """PageFetcher gọi thẳng mock-shop qua ASGI (không robots/độ trễ: đó là việc của Fetcher)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(self, url: str) -> FetchResponse:
        response = await self._client.get(url)
        return FetchResponse(
            url=url, final_url=str(response.url), status=response.status_code, text=response.text
        )


class EmptyPagesFetcher(AsgiFetcher):
    """Mô phỏng chặn mềm: mọi trang danh sách trả 200 nhưng không có sản phẩm."""

    async def get(self, url: str) -> FetchResponse:
        return await super().get(f"{url}{'&' if '?' in url else '?'}fail=empty")


async def test_crawl_category_walks_all_pages_of_the_live_mock_shop() -> None:
    app = create_app(captcha_after=1000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        scraper = MockShopScraper(AsgiFetcher(client))
        pages = [page async for page in scraper.crawl_category(Category.laptop, max_pages=10)]

    assert [len(page.items) for page in pages] == [12, 12, 2]
    titles = [item.title for page in pages for item in page.items]
    assert titles == [p.name for p in load_catalog() if p.category == "laptop"]


async def test_crawl_category_raises_a_captcha_challenge_with_the_page_code() -> None:
    app = create_app(captcha_after=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        scraper = MockShopScraper(AsgiFetcher(client))
        pages = []
        with pytest.raises(ChallengeDetected) as error:
            async for page in scraper.crawl_category(Category.laptop, max_pages=10):
                pages.append(page)

    assert len(pages) == 2
    challenge = error.value.challenge
    assert challenge.kind is ChallengeKind.captcha
    assert challenge.token
    assert challenge.prompt is not None and re.search(r"[A-Z2-9]{5}$", challenge.prompt)


async def test_live_search_returns_at_most_limit_results() -> None:
    app = create_app(captcha_after=1000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        found = await MockShopScraper(AsgiFetcher(client)).live_search("chuot", limit=3)
    assert len(found) == 3


async def test_soft_block_is_raised_when_first_page_is_empty_but_items_were_expected() -> None:
    app = create_app(captcha_after=1000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        scraper = MockShopScraper(EmptyPagesFetcher(client))
        with pytest.raises(ChallengeDetected) as error:
            [p async for p in scraper.crawl_category(Category.laptop, 3, expect_items=True)]
        assert error.value.challenge.kind is ChallengeKind.soft_block

        quiet = [p async for p in scraper.crawl_category(Category.laptop, 3, expect_items=False)]
        assert [(len(p.items), p.has_next) for p in quiet] == [(0, False)]


# --- Fixture khớp mock-shop hiện tại ----------------------------------------------------------


def test_mockshop_fixtures_match_the_live_app(tmp_path: Path) -> None:
    rendered = render()
    on_disk = {path.name for path in Path(FIXTURE_DIR).glob("*.html")}
    assert on_disk == set(rendered), "chạy lại: uv run python -m scripts.save_mockshop_fixtures"
    for name, html in rendered.items():
        assert fixture(name).replace("\r\n", "\n") == html, f"{name} đã lệch mock-shop"
