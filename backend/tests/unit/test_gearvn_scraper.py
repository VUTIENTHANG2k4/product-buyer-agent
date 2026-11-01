"""GearVNScraper (app/scrapers/sites/gearvn.py) trên fixture HTML đã lưu ở T3.1, không gọi mạng."""

from pathlib import Path
from typing import Any

import pytest

from app.domain.dto import ListingItem
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.robots import parse_robots
from app.scrapers.http.types import FetchResponse
from app.scrapers.registry import SCRAPERS, get_scraper
from app.scrapers.sites.gearvn import GearVNScraper
from tests.fakes import FakeFetcher

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"
BASE = "https://gearvn.com"
CATEGORY_URLS = {
    Category.laptop: f"{BASE}/collections/laptop",
    Category.mouse: f"{BASE}/collections/chuot-may-tinh",
    Category.keyboard: f"{BASE}/collections/ban-phim-may-tinh",
    Category.headset: f"{BASE}/collections/tai-nghe-may-tinh",
}
SLUG = {
    Category.laptop: "laptop",
    Category.mouse: "mouse",
    Category.keyboard: "keyboard",
    Category.headset: "headset",
}
MOUSE_LAST = f"{CATEGORY_URLS[Category.mouse]}?page=8"
LAPTOP_DETAIL = "laptop-acer-aspire-lite-15-al15-53p-56qh"
MOUSE_DETAIL = "chuot-gaming-khong-day-logitech-pro-x3-superstrike-lightspeed-black"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def response(url: str, text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text)


@pytest.fixture
def scraper() -> GearVNScraper:
    return GearVNScraper(FakeFetcher({}))


def listing(scraper: GearVNScraper, category: Category) -> tuple[list[ListingItem], str | None]:
    page = scraper.parse_listing(
        fixture(f"listing_{SLUG[category]}_p1.html"), category, CATEGORY_URLS[category]
    )
    return page.items, str(page.next_url) if page.next_url else None


def card(
    *, href: str | None = "/products/x", title: str = "Chuột Mock X", body: str = "", img: str = ""
) -> str:
    """Một thẻ sản phẩm tối giản có cùng thuộc tính `data-slot` như trang thật."""
    link = f' href="{href}"' if href is not None else ""
    return (
        f'<a class="product-card"{link}>{img}<div data-slot="product-card-content">'
        f"<div><p>{title}</p></div><div>{body}</div></div></a>"
    )


def parse_cards(scraper: GearVNScraper, *cards: str) -> Any:
    html = f"<html><body>{''.join(cards)}</body></html>"
    return scraper.parse_listing(html, Category.mouse, f"{BASE}/collections/chuot-may-tinh")


# --- Cấu hình, đăng ký ------------------------------------------------------------------------


def test_config_describes_gearvn() -> None:
    config = GearVNScraper.config
    assert (config.key, config.base_url, config.min_delay_s) == (SiteKey.gearvn, BASE, 5.0)
    assert (config.requires_js, config.supports_live_search, config.is_mock) == (False, True, False)
    assert config.enabled is True
    assert dict(config.categories) == CATEGORY_URLS


def test_scraper_is_registered_and_buildable() -> None:
    assert SCRAPERS[SiteKey.gearvn] is GearVNScraper
    assert isinstance(get_scraper(SiteKey.gearvn, FakeFetcher({})), GearVNScraper)


@pytest.mark.parametrize(
    ("page", "suffix"), [(1, ""), (2, "?page=2"), (3, "?page=3"), (11, "?page=11")]
)
@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_listing_url_uses_page_parameter_from_page_two(
    scraper: GearVNScraper, category: Category, page: int, suffix: str
) -> None:
    assert scraper.listing_url(category, page) == f"{CATEGORY_URLS[category]}{suffix}"


def test_every_url_the_scraper_builds_is_allowed_by_the_saved_robots_txt(
    scraper: GearVNScraper,
) -> None:
    rules = parse_robots(
        (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8"), "ProductBuyerAgent/0.1"
    )
    urls = [scraper.listing_url(category, page) for category in CATEGORY_URLS for page in (1, 2, 9)]
    urls += [scraper.search_url("chuột razer"), f"{BASE}/products/{LAPTOP_DETAIL}"]
    assert all(rules.allowed(url) for url in urls)
    assert not rules.allowed(f"{BASE}/api/products")  # chứng minh bộ kiểm tra thật sự chặn


# --- Trang danh sách ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_first_listing_page_has_twenty_complete_items_and_a_next_link(
    scraper: GearVNScraper, category: Category
) -> None:
    page = scraper.parse_listing(
        fixture(f"listing_{SLUG[category]}_p1.html"), category, CATEGORY_URLS[category]
    )
    assert (len(page.items), page.skipped, page.has_next) == (20, 0, True)
    assert str(page.next_url) == f"{CATEGORY_URLS[category]}?page=2"
    first = page.items[0]
    assert first.site is SiteKey.gearvn
    assert first.category_hint is category
    assert str(first.url).startswith(f"{BASE}/products/")
    assert first.title.strip() == first.title and len(first.title) > 10
    assert first.image_url is not None and str(first.image_url).startswith("https://")
    assert first.price is not None and first.price > 0
    assert first.stock_status is StockStatus.unknown
    assert (first.rating, first.rating_count, first.site_sku, first.raw_specs) == (
        None,
        None,
        None,
        {},
    )


@pytest.mark.parametrize("category", list(CATEGORY_URLS))
def test_listing_items_have_unique_clean_urls_and_positive_integer_prices(
    scraper: GearVNScraper, category: Category
) -> None:
    items, _ = listing(scraper, category)
    urls = [str(item.url) for item in items]
    assert len(set(urls)) == len(urls)
    assert all("?" not in url and "#" not in url for url in urls)
    for item in items:
        assert item.price is None or (type(item.price) is int and item.price > 0)
        assert item.list_price is None or (item.price is not None and item.list_price > item.price)


def test_discounted_card_reads_struck_price_as_list_price_and_ignores_promotions(
    scraper: GearVNScraper,
) -> None:
    items, _ = listing(scraper, Category.mouse)
    by_slug = {str(item.url).rsplit("/", 1)[1]: item for item in items}
    pro_x3 = by_slug[MOUSE_DETAIL]  # có khuyến mãi "PRE-ORDER GIẢM NGAY 300.000Đ"
    assert (pro_x3.price, pro_x3.list_price, pro_x3.price_type) == (
        4_790_000,
        5_690_000,
        PriceType.sale,
    )


def test_card_with_a_single_price_is_regular(scraper: GearVNScraper) -> None:
    items, _ = listing(scraper, Category.laptop)
    first = items[0]
    assert (first.price, first.list_price, first.price_type) == (
        24_990_000,
        None,
        PriceType.regular,
    )


def test_listing_item_counts_by_price_type_match_the_survey(scraper: GearVNScraper) -> None:
    """Số đếm theo fixture lưu ngày 2026-10-19 (docs/sources/gearvn.md mục 5); đổi khi làm mới."""
    counts = {PriceType.sale: 0, PriceType.regular: 0, PriceType.unknown: 0}
    for category in CATEGORY_URLS:
        for item in listing(scraper, category)[0]:
            counts[item.price_type] += 1
    assert counts == {PriceType.sale: 70, PriceType.regular: 10, PriceType.unknown: 0}


def test_last_listing_page_has_no_next_and_marks_discontinued_items_without_price(
    scraper: GearVNScraper,
) -> None:
    page = scraper.parse_listing(fixture("listing_mouse_p8.html"), Category.mouse, MOUSE_LAST)
    assert (len(page.items), page.has_next, page.next_url, page.skipped) == (19, False, None, 0)
    unpriced = [item for item in page.items if item.price is None]
    assert len(unpriced) == 18
    assert all((item.list_price, item.price_type) == (None, PriceType.unknown) for item in unpriced)
    assert [item.price_type for item in page.items if item.price is not None] == [PriceType.sale]


def test_empty_listing_has_no_items_and_no_next() -> None:
    page = GearVNScraper(FakeFetcher({})).parse_listing(
        "<html><body></body></html>", Category.laptop, CATEGORY_URLS[Category.laptop]
    )
    assert (page.items, page.has_next, page.next_url, page.skipped) == ([], False, None, 0)


# --- Từng kiểu giá (tham số hóa) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "price", "list_price", "price_type"),
    [
        pytest.param("<span>1.990.000đ</span>", 1_990_000, None, PriceType.regular, id="single"),
        pytest.param(
            "<div><span>2.490.000đ</span><span>-20%</span></div><span>1.990.000đ</span>",
            1_990_000,
            2_490_000,
            PriceType.sale,
            id="struck-then-sale",
        ),
        pytest.param(
            "<span>1.990.000đ</span><span>1.990.000đ</span>",
            None,
            None,
            PriceType.unknown,
            id="equal-prices-are-ambiguous",
        ),
        pytest.param(
            "<span>1.500.000đ</span><span>1.990.000đ</span>",
            None,
            None,
            PriceType.unknown,
            id="list-below-sale-is-ambiguous",
        ),
        pytest.param(
            "<span>3.000.000đ</span><span>2.500.000đ</span><span>2.000.000đ</span>",
            None,
            None,
            PriceType.unknown,
            id="three-prices-are-ambiguous",
        ),
        pytest.param(
            '<span data-slot="product-discontinued-price">Liên hệ tư vấn</span>',
            None,
            None,
            PriceType.unknown,
            id="discontinued-contact-price",
        ),
        pytest.param(
            '<span>990.000đ</span><span data-slot="product-discontinued-price">Liên hệ</span>',
            None,
            None,
            PriceType.unknown,
            id="discontinued-wins-over-any-price-text",
        ),
        pytest.param("<span>Liên hệ</span>", None, None, PriceType.unknown, id="no-price-text"),
        pytest.param("", None, None, PriceType.unknown, id="no-price-at-all"),
        pytest.param(
            "<span>5đ</span><span>9.999đ</span>", None, None, PriceType.unknown, id="out-of-range"
        ),
        pytest.param(
            "<span><span>3.290.000đ</span></span>",
            3_290_000,
            None,
            PriceType.regular,
            id="nested-span-not-counted-twice",
        ),
    ],
)
def test_price_display_kinds_map_to_price_and_price_type(
    scraper: GearVNScraper,
    body: str,
    price: int | None,
    list_price: int | None,
    price_type: PriceType,
) -> None:
    item = parse_cards(scraper, card(body=body)).items[0]
    assert (item.price, item.list_price, item.price_type) == (price, list_price, price_type)


def test_promotion_text_is_never_read_as_a_price(scraper: GearVNScraper) -> None:
    body = (
        "<span>1.990.000đ</span>"
        '<span data-slot="product-promotion"><span>Tặng quà trị giá 500.000đ</span>'
        "<span>800.000đ</span></span>"
    )
    item = parse_cards(scraper, card(body=body)).items[0]
    assert (item.price, item.list_price) == (1_990_000, None)


# --- Thẻ lỗi bị bỏ qua -------------------------------------------------------------------------


def test_cards_without_link_or_title_are_skipped_and_counted(scraper: GearVNScraper) -> None:
    page = parse_cards(
        scraper,
        card(href="/products/a", body="<span>1.990.000đ</span>"),
        card(href=None, body="<span>1.990.000đ</span>"),
        card(href="/products/c", title="", body="<span>1.990.000đ</span>"),
        card(href="/products/d", body="<span>2.990.000đ</span>"),
    )
    assert [str(item.url).rsplit("/", 1)[1] for item in page.items] == ["a", "d"]
    assert page.skipped == 2


@pytest.mark.parametrize("href", ["#", "/collections/laptop", "/", "javascript:void(0)"])
def test_card_that_does_not_link_to_a_product_page_is_skipped(
    scraper: GearVNScraper, href: str
) -> None:
    page = parse_cards(scraper, card(href=href, body="<span>1.990.000đ</span>"))
    assert (page.items, page.skipped) == ([], 1)


@pytest.mark.parametrize("href", ["javascript:void(0)", "mailto:a@b.c", "http://[bad"])
def test_unusable_rel_next_href_means_no_next_page_instead_of_a_failed_page(
    scraper: GearVNScraper, href: str
) -> None:
    html = (
        f'<html><head><link rel="next" href="{href}"></head><body>'
        f"{card(body='<span>1.990.000đ</span>')}</body></html>"
    )
    page = scraper.parse_listing(html, Category.mouse, f"{BASE}/collections/chuot-may-tinh")
    assert (len(page.items), page.has_next, page.next_url) == (1, False, None)


def test_card_image_ignores_embedded_flag_graphics(scraper: GearVNScraper) -> None:
    flag = '<img data-slot="product-flag-graphic" src="data:image/svg+xml;charset=utf-8,x">'
    photo = '<img alt="x" src="https://cdn.hstatic.net/products/1/a.jpg">'
    item = parse_cards(scraper, card(img=flag + photo, body="<span>1.990.000đ</span>")).items[0]
    assert str(item.image_url) == "https://cdn.hstatic.net/products/1/a.jpg"


@pytest.mark.parametrize(
    "img",
    [
        pytest.param("", id="no-img"),
        pytest.param('<img src="">', id="empty-src"),
        pytest.param('<img src="data:image/gif;base64,AAAA">', id="data-uri"),
    ],
)
def test_card_without_usable_image_has_no_image_url(scraper: GearVNScraper, img: str) -> None:
    assert (
        parse_cards(scraper, card(img=img, body="<span>1.990.000đ</span>")).items[0].image_url
        is None
    )


def test_relative_links_and_tracking_parameters_are_cleaned(scraper: GearVNScraper) -> None:
    item = parse_cards(scraper, card(href="/products/a?utm_source=x#top")).items[0]
    assert str(item.url) == f"{BASE}/products/a"


# --- Chi tiết ----------------------------------------------------------------------------------


def test_laptop_detail_reads_labelled_specs_and_brand(scraper: GearVNScraper) -> None:
    url = f"{BASE}/products/{LAPTOP_DETAIL}?utm_source=mail"
    detail = scraper.parse_detail(fixture(f"detail_{LAPTOP_DETAIL}.html"), url)
    assert str(detail.url) == f"{BASE}/products/{LAPTOP_DETAIL}"
    assert detail.brand_hint == "ACER"
    assert detail.model_code_hint is None  # `sku` của GearVN là mã nội bộ, không phải mã hãng
    assert detail.raw_specs == {
        "Card đồ họa": "Intel® UHD Graphics",
        "Kích thước màn hình": "15.6 inch",
        "Dòng CPU": "Core 5",
        "Dung lượng SSD": "512 GB",
        "Tấm nền": "IPS",
        "Độ phân giải": "Full HD (1920x1080)",
        "Dung lượng RAM": "8 GB",
    }


def test_mouse_detail_reads_labelled_specs_and_brand(scraper: GearVNScraper) -> None:
    detail = scraper.parse_detail(
        fixture(f"detail_{MOUSE_DETAIL}.html"), f"{BASE}/products/{MOUSE_DETAIL}"
    )
    assert detail.brand_hint == "Logitech"
    assert detail.raw_specs["Độ phân giải (DPI)"] == "48000 DPI"
    assert detail.raw_specs["Trọng lượng"] == "59 g"
    assert len(detail.raw_specs) == 7


def ld_page(payload: str) -> str:
    return f'<html><head><script type="application/ld+json">{payload}</script></head></html>'


def test_detail_uses_mpn_when_the_page_has_one(scraper: GearVNScraper) -> None:
    html = ld_page('{"@type": "Product", "mpn": " AL15-53P ", "sku": "INTERNAL-1"}')
    assert scraper.parse_detail(html, f"{BASE}/products/a").model_code_hint == "AL15-53P"


@pytest.mark.parametrize(
    ("payload", "brand_hint"),
    [
        pytest.param('{"@type": "Product", "brand": "ASUS"}', "ASUS", id="brand-as-string"),
        pytest.param('{"@type": "Product", "brand": {"name": ["A", "B"]}}', None, id="brand-list"),
        pytest.param('{"@type": "Product", "brand": {"name": "  "}}', None, id="blank-brand"),
        pytest.param(
            '[{"@type": ["Thing", "Product"], "brand": {"name": "MSI"}}]', "MSI", id="type-list"
        ),
        pytest.param('{"@type": "BreadcrumbList"}', None, id="no-product"),
        pytest.param("{not json", None, id="broken-json"),
    ],
)
def test_detail_brand_hint_handles_json_ld_variants(
    scraper: GearVNScraper, payload: str, brand_hint: str | None
) -> None:
    detail = scraper.parse_detail(ld_page(payload), f"{BASE}/products/a")
    assert (detail.brand_hint, detail.raw_specs, detail.model_code_hint) == (brand_hint, {}, None)


def test_detail_specs_skip_malformed_properties_and_merge_repeated_labels(
    scraper: GearVNScraper,
) -> None:
    html = ld_page(
        '{"@type": "Product", "additionalProperty": ['
        '{"name": "Kết nối", "value": "USB"}, {"name": "Kết nối", "value": "Bluetooth"},'
        '{"name": "Kết nối", "value": "USB"}, {"name": " ", "value": "x"},'
        '{"name": "Rỗng", "value": ""}, {"name": "Số", "value": 144},'
        '{"name": "Pin", "value": "Pin sạc"}, {"name": "Pin", "value": "Pin"},'
        '{"name": "Danh sách", "value": ["a"]}, "chuỗi", {"value": "y"}]}'
    )
    assert scraper.parse_detail(html, f"{BASE}/products/a").raw_specs == {
        "Kết nối": "USB; Bluetooth",
        "Số": "144",
        "Pin": "Pin sạc; Pin",  # "Pin" là chuỗi con của "Pin sạc" nhưng vẫn là giá trị khác
    }


def test_detail_specs_ignore_boolean_values(scraper: GearVNScraper) -> None:
    html = ld_page(
        '{"@type": "Product", "additionalProperty": ['
        '{"name": "RGB", "value": true}, {"name": "Có dây", "value": "Có"}]}'
    )
    assert scraper.parse_detail(html, f"{BASE}/products/a").raw_specs == {"Có dây": "Có"}


def test_detail_specs_ignore_non_list_additional_property(scraper: GearVNScraper) -> None:
    html = ld_page('{"@type": "Product", "additionalProperty": {"name": "a", "value": "b"}}')
    assert scraper.parse_detail(html, f"{BASE}/products/a").raw_specs == {}


# --- Tìm kiếm ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("chuot razer", f"{BASE}/search?q=chuot+razer"),
        ("chuột razer", f"{BASE}/search?q=chu%E1%BB%99t+razer"),
        ("a&b=c", f"{BASE}/search?q=a%26b%3Dc"),
    ],
)
def test_search_url_encodes_the_query(scraper: GearVNScraper, query: str, expected: str) -> None:
    assert scraper.search_url(query) == expected


def test_parse_search_returns_the_cards_of_the_results_page(scraper: GearVNScraper) -> None:
    items = scraper.parse_search(fixture("search_chuot_razer.html"), f"{BASE}/search?q=chuot+razer")
    assert len(items) == 20
    assert str(items[0].url) == f"{BASE}/products/chuot-razer-cobra"
    assert all(item.category_hint is Category.other for item in items)
    assert all(item.price is not None and item.price > 0 for item in items)


# --- Điều phối qua fetcher giả -----------------------------------------------------------------


async def test_crawl_category_follows_rel_next_until_the_last_page() -> None:
    page_two = f"{CATEGORY_URLS[Category.mouse]}?page=2"
    fetcher = FakeFetcher(
        {
            CATEGORY_URLS[Category.mouse]: response(
                CATEGORY_URLS[Category.mouse], fixture("listing_mouse_p1.html")
            ),
            page_two: response(page_two, fixture("listing_mouse_p8.html")),
        }
    )
    scraper = GearVNScraper(fetcher)
    pages = [page async for page in scraper.crawl_category(Category.mouse, max_pages=5)]
    assert [len(page.items) for page in pages] == [20, 19]
    assert fetcher.requested == [CATEGORY_URLS[Category.mouse], page_two]


async def test_fetch_detail_and_live_search_go_through_the_fetcher() -> None:
    detail_url = f"{BASE}/products/{LAPTOP_DETAIL}"
    search_url = f"{BASE}/search?q=chuot+razer"
    fetcher = FakeFetcher(
        {
            detail_url: response(detail_url, fixture(f"detail_{LAPTOP_DETAIL}.html")),
            search_url: response(search_url, fixture("search_chuot_razer.html")),
        }
    )
    scraper = GearVNScraper(fetcher)
    assert (await scraper.fetch_detail(detail_url)).brand_hint == "ACER"
    assert len(await scraper.live_search("chuot razer", limit=5)) == 5
    assert fetcher.requested == [detail_url, search_url]


# --- Challenge ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    sorted(path.name for path in FIXTURE_DIR.glob("*.html")),
)
def test_real_pages_are_not_flagged_as_challenges(scraper: GearVNScraper, name: str) -> None:
    assert scraper.detect_challenge(response(f"{BASE}/x", fixture(name))) is None


@pytest.mark.parametrize(
    ("status", "kind"), [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)]
)
async def test_blocking_status_raises_challenge_detected(status: int, kind: ChallengeKind) -> None:
    url = CATEGORY_URLS[Category.laptop]
    scraper = GearVNScraper(FakeFetcher({url: response(url, "", status)}))
    with pytest.raises(ChallengeDetected) as caught:
        _ = [page async for page in scraper.crawl_category(Category.laptop, max_pages=1)]
    assert caught.value.challenge.kind is kind
    assert caught.value.challenge.site is SiteKey.gearvn
