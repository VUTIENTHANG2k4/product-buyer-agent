"""QA M3: test biên và hồi quy cho GearVNScraper (không gọi mạng, không sleep thật).

Mục "Lỗi đã tái hiện" là các lỗi QA M3 tìm thấy; test được viết đỏ trước, nay đã sửa mã và xanh.
"""

import json
import logging
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from selectolax.lexbor import LexborHTMLParser

from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.robots import parse_robots
from app.scrapers.http.types import FetchResponse
from app.scrapers.parsing import json_ld_objects, node_text
from app.scrapers.sites.gearvn import GearVNScraper
from tests.fakes import FakeFetcher
from tests.unit.test_gearvn_scraper import (
    BASE,
    CATEGORY_URLS,
    FIXTURE_DIR,
    LAPTOP_DETAIL,
    card,
    fixture,
    ld_page,
    parse_cards,
    response,
)

MOUSE = CATEGORY_URLS[Category.mouse]
MOUSE_P2 = f"{MOUSE}?page=2"
NBSP = "\N{NO-BREAK SPACE}"
CLOUDFLARE_503 = {"server": "cloudflare", "cf-mitigated": "challenge"}


@pytest.fixture
def scraper() -> GearVNScraper:
    return GearVNScraper(FakeFetcher({}))


class RecordingFetcher:
    """PageFetcher giả: trang định sẵn theo URL, URL lạ trả trang rỗng; ghi lại mọi request."""

    def __init__(self, pages: dict[str, FetchResponse] | None = None) -> None:
        self.pages = pages or {}
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return self.pages.get(url) or response(url, "<html><body></body></html>")


def listing_html(*cards: str, next_href: str | None = None) -> str:
    head = f'<link rel="next" href="{next_href}"/>' if next_href is not None else ""
    return f"<html><head>{head}</head><body>{''.join(cards)}</body></html>"


def priced(slug: str) -> str:
    return card(href=f"/products/{slug}", title=f"Chuột {slug}", body="<span>1.990.000đ</span>")


# --- Giá: định dạng lạ không bao giờ bị đoán --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"1.990.000{NBSP}đ", id="nbsp-before-unit"),
        pytest.param("1.990.000 đ", id="space-before-unit"),
        pytest.param("1.990.000Đ", id="uppercase-unit"),
        pytest.param("1.990.000\N{DONG SIGN}", id="dong-sign"),
        pytest.param("1,990,000đ", id="comma-grouping"),
        pytest.param("1990000đ", id="no-grouping"),
        pytest.param("1.990.000 VND", id="vnd-suffix"),
        pytest.param("Giá: 1.990.000đ", id="text-prefix"),
        pytest.param("12.34.567đ", id="bad-group-sizes"),
        pytest.param("một triệu đồng", id="amount-in-words"),
    ],
)
def test_price_text_in_an_unexpected_format_gives_no_price_but_keeps_the_item(
    scraper: GearVNScraper, text: str
) -> None:
    page = parse_cards(scraper, card(body=f"<span>{text}</span>"))
    assert (len(page.items), page.skipped) == (1, 0)
    item = page.items[0]
    assert (item.price, item.list_price, item.price_type) == (None, None, PriceType.unknown)


@pytest.mark.parametrize(
    ("text", "price"),
    [
        ("10.000đ", 10_000),
        ("9.999đ", None),
        ("500.000.000đ", 500_000_000),
        ("500.000.001đ", None),
        ("0đ", None),
        ("000.000đ", None),
        ("999.999.999.999đ", None),
    ],
)
def test_price_range_boundaries_are_inclusive_at_both_ends(
    scraper: GearVNScraper, text: str, price: int | None
) -> None:
    item = parse_cards(scraper, card(body=f"<span>{text}</span>")).items[0]
    assert item.price == price
    assert item.price_type is (PriceType.regular if price else PriceType.unknown)


@pytest.mark.parametrize("digits", ["١.٩٩٠.٠٠٠", "１.９９０.０００"])
def test_non_ascii_digits_are_read_as_the_same_price(scraper: GearVNScraper, digits: str) -> None:
    item = parse_cards(scraper, card(body=f"<span>{digits}đ</span>")).items[0]
    assert item.price == 1_990_000


def test_four_prices_on_one_card_give_no_price_and_log_a_warning(
    scraper: GearVNScraper, caplog: pytest.LogCaptureFixture
) -> None:
    body = "".join(f"<span>{n}.000.000đ</span>" for n in (4, 3, 2, 1))
    with caplog.at_level(logging.WARNING, logger="app.scrapers.sites.gearvn"):
        item = parse_cards(scraper, card(body=body)).items[0]
    assert (item.price, item.list_price, item.price_type) == (None, None, PriceType.unknown)
    assert any("4 giá" in record.getMessage() for record in caplog.records)


def test_promotion_block_nested_inside_a_price_span_is_not_counted(scraper: GearVNScraper) -> None:
    body = (
        '<span>1.990.000đ<span data-slot="product-promotion">'
        "<span>Tặng quà 500.000đ</span></span></span>"
    )
    item = parse_cards(scraper, card(body=body)).items[0]
    assert (item.price, item.list_price) == (1_990_000, None)


def test_struck_price_badge_and_sale_price_inside_one_wrapper_read_as_a_sale(
    scraper: GearVNScraper,
) -> None:
    body = "<span><span>2.490.000đ</span><span>-20%</span><span>1.990.000đ</span></span>"
    item = parse_cards(scraper, card(body=body)).items[0]
    assert (item.price, item.list_price, item.price_type) == (1_990_000, 2_490_000, PriceType.sale)


def test_inline_script_inside_a_card_does_not_change_the_price(scraper: GearVNScraper) -> None:
    body = "<span>1.990.000đ</span><script>var price = '999.000đ'</script>"
    assert parse_cards(scraper, card(body=body)).items[0].price == 1_990_000


# --- Thẻ: liên kết, tiêu đề, ảnh --------------------------------------------------------------


@pytest.mark.parametrize(
    "href",
    [
        pytest.param("/products/a b", id="space-in-path"),
        pytest.param("/products/" + "a" * 2100, id="overlong"),
        pytest.param("/products/../api/x", id="dot-dot-into-api"),
        pytest.param("/products/x/../../api/x", id="deep-dot-dot-into-api"),
        pytest.param("/api/products/x", id="api-path"),
        pytest.param("products/x", id="relative-resolves-under-collections"),
        pytest.param("?variant=1", id="query-only"),
        pytest.param("/Products/x", id="wrong-case"),
    ],
)
def test_card_link_that_is_not_a_clean_product_url_is_skipped_and_counted(
    scraper: GearVNScraper, href: str
) -> None:
    page = parse_cards(scraper, card(href=href), priced("ok"))
    assert [str(item.url).rsplit("/", 1)[1] for item in page.items] == ["ok"]
    assert page.skipped == 1


@pytest.mark.parametrize("title", ["   \n  ", NBSP, f"{NBSP}  {NBSP}"])
def test_card_whose_title_is_only_whitespace_is_skipped(scraper: GearVNScraper, title: str) -> None:
    page = parse_cards(scraper, card(title=title))
    assert (page.items, page.skipped) == ([], 1)


def test_entities_in_a_title_are_decoded_once_and_never_become_markup(
    scraper: GearVNScraper,
) -> None:
    title = "Chuột &amp; Phím &quot;X&quot; &lt;b&gt;đậm&lt;/b&gt;"
    assert parse_cards(scraper, card(title=title)).items[0].title == 'Chuột & Phím "X" <b>đậm</b>'


def test_nul_in_a_title_is_dropped_by_the_html_parser(scraper: GearVNScraper) -> None:
    assert parse_cards(scraper, card(title="A\x00B")).items[0].title == "AB"


@pytest.mark.parametrize("form", ["NFC", "NFD"])
def test_vietnamese_title_in_either_unicode_form_is_kept_and_equal_after_nfc(
    scraper: GearVNScraper, form: str
) -> None:
    title = unicodedata.normalize(form, "Chuột Razer Viper Ultimate")
    parsed = parse_cards(scraper, card(title=title)).items[0].title
    assert unicodedata.normalize("NFC", parsed) == "Chuột Razer Viper Ultimate"


def test_very_long_title_is_kept_whole(scraper: GearVNScraper) -> None:
    assert len(parse_cards(scraper, card(title="x" * 300_000)).items[0].title) == 300_000


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("/a.jpg", f"{BASE}/a.jpg"),
        ("//cdn.hstatic.net/a.jpg", "https://cdn.hstatic.net/a.jpg"),
        ("/a b.jpg", f"{BASE}/a%20b.jpg"),
    ],
)
def test_relative_and_protocol_relative_image_urls_are_resolved(
    scraper: GearVNScraper, src: str, expected: str
) -> None:
    item = parse_cards(scraper, card(img=f'<img src="{src}">')).items[0]
    assert str(item.image_url) == expected


def test_lazy_loaded_placeholder_image_gives_no_image_url(scraper: GearVNScraper) -> None:
    img = '<img src="data:image/gif;base64,AAAA" data-src="/real.jpg">'
    assert parse_cards(scraper, card(img=img)).items[0].image_url is None


def test_cards_with_the_same_url_are_all_returned_for_the_pipeline_to_deduplicate(
    scraper: GearVNScraper,
) -> None:
    page = parse_cards(scraper, priced("same"), priced("same"))
    assert [str(item.url) for item in page.items] == [f"{BASE}/products/same"] * 2


def test_truncated_html_never_raises_and_returns_what_was_complete(scraper: GearVNScraper) -> None:
    html = listing_html(priced("a"), priced("b"))
    page = scraper.parse_listing(html[: len(html) - 40], Category.mouse, MOUSE)
    assert [str(item.url).rsplit("/", 1)[1] for item in page.items] == ["a", "b"]


def test_empty_and_whitespace_html_give_an_empty_page(scraper: GearVNScraper) -> None:
    for html in ("", "   \n", "<", "<a class='product-card'"):
        page = scraper.parse_listing(html, Category.mouse, MOUSE)
        assert (page.items, page.has_next, page.next_url) == ([], False, None)


def test_a_detail_page_is_not_mistaken_for_one_with_specs_when_parsed_as_a_listing_page_url(
    scraper: GearVNScraper,
) -> None:
    """Trang danh sách đưa vào parse_detail (và ngược lại) không ném lỗi và không bịa thông số."""
    detail = scraper.parse_detail(fixture("listing_laptop_p1.html"), f"{BASE}/products/x")
    assert (detail.raw_specs, detail.brand_hint, detail.model_code_hint) == ({}, None, None)


# --- rel=next ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("?page=2", MOUSE_P2),
        ("/collections/chuot-may-tinh?page=2", MOUSE_P2),
        ("?page=2&utm_source=mail&fbclid=x", MOUSE_P2),
        (f"{MOUSE}?page=2#top", MOUSE_P2),
    ],
)
def test_rel_next_is_resolved_against_the_page_url_and_tracking_is_removed(
    scraper: GearVNScraper, href: str, expected: str
) -> None:
    page = scraper.parse_listing(listing_html(priced("a"), next_href=href), Category.mouse, MOUSE)
    assert (page.has_next, str(page.next_url)) == (True, expected)


@pytest.mark.parametrize("href", ["", "/" + "a" * 2100, "?page=2 3"])
def test_blank_overlong_or_spaced_rel_next_means_no_next_page(
    scraper: GearVNScraper, href: str
) -> None:
    page = scraper.parse_listing(listing_html(priced("a"), next_href=href), Category.mouse, MOUSE)
    assert (len(page.items), page.has_next, page.next_url) == (1, False, None)


def test_first_rel_next_link_wins_when_the_page_has_several(scraper: GearVNScraper) -> None:
    head = '<link rel="next" href="?page=2"><link rel="next" href="?page=9">'
    html = f"<html><head>{head}</head><body>{priced('a')}</body></html>"
    assert str(scraper.parse_listing(html, Category.mouse, MOUSE).next_url) == MOUSE_P2


def test_anchor_with_rel_next_in_the_body_is_not_a_pagination_link(scraper: GearVNScraper) -> None:
    html = f'<html><body>{priced("a")}<a rel="next" href="?page=2">Sau</a></body></html>'
    page = scraper.parse_listing(html, Category.mouse, MOUSE)
    assert (page.has_next, page.next_url) == (False, None)


async def test_crawl_ignores_a_next_link_that_leaves_the_site_and_builds_its_own_url() -> None:
    fetcher = RecordingFetcher(
        {
            MOUSE: response(
                MOUSE, listing_html(priced("a"), next_href="https://evil.example/x?page=2")
            )
        }
    )
    scraper = GearVNScraper(fetcher)
    pages = [page async for page in scraper.crawl_category(Category.mouse, max_pages=2)]
    assert fetcher.requested == [MOUSE, MOUSE_P2]
    assert len(pages) == 2


@pytest.mark.parametrize("next_href", [MOUSE, "#"])
async def test_crawl_stops_after_one_request_when_next_points_back_to_the_same_page(
    next_href: str,
) -> None:
    fetcher = RecordingFetcher(
        {MOUSE: response(MOUSE, listing_html(priced("a"), next_href=next_href))}
    )
    pages = [page async for page in GearVNScraper(fetcher).crawl_category(Category.mouse, 5)]
    assert fetcher.requested == [MOUSE]
    assert len(pages) == 1


async def test_crawl_stops_on_a_pagination_cycle_without_a_third_request() -> None:
    fetcher = RecordingFetcher(
        {
            MOUSE: response(MOUSE, listing_html(priced("a"), next_href="?page=2")),
            MOUSE_P2: response(MOUSE_P2, listing_html(priced("b"), next_href=MOUSE)),
        }
    )
    pages = [page async for page in GearVNScraper(fetcher).crawl_category(Category.mouse, 10)]
    assert fetcher.requested == [MOUSE, MOUSE_P2]
    assert [len(page.items) for page in pages] == [1, 1]


async def test_crawl_keeps_going_through_an_empty_page_that_still_links_to_the_next() -> None:
    fetcher = RecordingFetcher(
        {
            MOUSE: response(MOUSE, listing_html(next_href="?page=2")),
            MOUSE_P2: response(MOUSE_P2, listing_html(priced("b"))),
        }
    )
    pages = [page async for page in GearVNScraper(fetcher).crawl_category(Category.mouse, 5)]
    assert [len(page.items) for page in pages] == [0, 1]
    assert fetcher.requested == [MOUSE, MOUSE_P2]


@pytest.mark.parametrize(
    "next_href",
    [
        pytest.param("/api/products?page=2", id="api-path"),
        pytest.param("/gio-hang", id="cart"),
        pytest.param("/collections/laptop?page=2", id="other-category"),
    ],
)
async def test_crawl_does_not_follow_a_next_link_outside_the_category_listing(
    next_href: str,
) -> None:
    fetcher = RecordingFetcher(
        {MOUSE: response(MOUSE, listing_html(priced("a"), next_href=next_href))}
    )
    _ = [page async for page in GearVNScraper(fetcher).crawl_category(Category.mouse, 2)]
    assert fetcher.requested == [MOUSE, MOUSE_P2]


# --- Challenge và điều phối --------------------------------------------------------------------


async def test_a_200_page_with_a_recaptcha_widget_raises_captcha_challenge() -> None:
    page = "<html><body><div class='g-recaptcha'></div></body></html>"
    fetcher = RecordingFetcher({MOUSE: response(MOUSE, page)})
    with pytest.raises(ChallengeDetected) as caught:
        _ = [p async for p in GearVNScraper(fetcher).crawl_category(Category.mouse, 3)]
    assert (caught.value.challenge.kind, caught.value.challenge.site) == (
        ChallengeKind.captcha,
        SiteKey.gearvn,
    )
    assert fetcher.requested == [MOUSE]


@pytest.mark.parametrize("operation", ["fetch_detail", "live_search"])
async def test_cloudflare_503_on_detail_or_search_is_a_challenge_not_a_fetch_error(
    operation: str,
) -> None:
    detail_url = f"{BASE}/products/{LAPTOP_DETAIL}"
    search_url = f"{BASE}/search?q=chuot"
    blocked = {
        detail_url: FetchResponse(
            url=detail_url, final_url=detail_url, status=503, text="", headers=CLOUDFLARE_503
        ),
        search_url: FetchResponse(
            url=search_url, final_url=search_url, status=503, text="", headers=CLOUDFLARE_503
        ),
    }
    scraper = GearVNScraper(RecordingFetcher(blocked))
    with pytest.raises(ChallengeDetected) as caught:
        if operation == "fetch_detail":
            await scraper.fetch_detail(detail_url)
        else:
            await scraper.live_search("chuot", limit=3)
    assert caught.value.challenge.kind is ChallengeKind.captcha


async def test_fetch_detail_refuses_other_domains_before_any_request() -> None:
    fetcher = RecordingFetcher()
    with pytest.raises(ValueError, match="outside"):
        await GearVNScraper(fetcher).fetch_detail("https://evil.example/products/a")
    assert fetcher.requested == []


@pytest.mark.parametrize(("query", "limit"), [("", 3), ("   ", 3), ("chuot", 0), ("chuot", -1)])
async def test_live_search_rejects_blank_query_and_non_positive_limit_before_any_request(
    query: str, limit: int
) -> None:
    fetcher = RecordingFetcher()
    with pytest.raises(ValueError):
        await GearVNScraper(fetcher).live_search(query, limit)
    assert fetcher.requested == []


async def test_live_search_returns_at_most_limit_items_from_a_single_request() -> None:
    url = f"{BASE}/search?q=chuot+razer"
    fetcher = RecordingFetcher({url: response(url, fixture("search_chuot_razer.html"))})
    scraper = GearVNScraper(fetcher)
    assert len(await scraper.live_search("chuot razer", limit=1)) == 1
    assert len(await scraper.live_search("chuot razer", limit=50)) == 20  # trang chỉ có 20 thẻ
    assert fetcher.requested == [url, url]


# --- URL dựng ra không vi phạm robots.txt -------------------------------------------------------

HOSTILE_QUERIES = [
    "chuột razer",
    "a&b=c",
    "x#fragment",
    "a b  c",
    "../api/products",
    "/api/",
    "?q=x&page=2",
    "line1\nline2",
    "x" * 5000,
    unicodedata.normalize("NFD", "chuột gaming"),
    "100% giảm giá",
    "+++",
]


@pytest.mark.parametrize("query", HOSTILE_QUERIES, ids=lambda q: repr(q)[:24])
def test_search_url_is_always_one_q_parameter_on_the_search_path_and_allowed_by_robots(
    scraper: GearVNScraper, query: str
) -> None:
    rules = parse_robots(
        (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8"), "ProductBuyerAgent/0.1"
    )
    url = scraper.search_url(query)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path, parts.fragment) == (
        "https",
        "gearvn.com",
        "/search",
        "",
    )
    assert list(parse_qs(parts.query, keep_blank_values=True)) == ["q"]
    # Khứ hồi đúng (không tách thành tham số khác) sau khi chuẩn hóa NFC và bỏ khoảng trắng hai đầu.
    assert parse_qs(parts.query)["q"] == [unicodedata.normalize("NFC", query).strip()]
    assert rules.allowed(url)
    assert "/api/" not in parts.path


def test_listing_urls_for_every_category_and_up_to_page_60_stay_allowed_by_robots(
    scraper: GearVNScraper,
) -> None:
    rules = parse_robots(
        (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8"), "ProductBuyerAgent/0.1"
    )
    for category in CATEGORY_URLS:
        for page in range(1, 61):
            url = scraper.listing_url(category, page)
            assert rules.allowed(url)
            assert urlsplit(url).query in ("", f"page={page}")


@pytest.mark.parametrize("category", [Category.phone, Category.other])
def test_listing_url_for_a_category_gearvn_does_not_cover_is_an_error(
    scraper: GearVNScraper, category: Category
) -> None:
    with pytest.raises(ValueError, match="no listing URL"):
        scraper.listing_url(category, 1)


@pytest.mark.parametrize("page", [0, -1])
def test_listing_url_rejects_pages_below_one(scraper: GearVNScraper, page: int) -> None:
    with pytest.raises(ValueError, match="page must be >= 1"):
        scraper.listing_url(Category.mouse, page)


# --- Chi tiết: JSON-LD -------------------------------------------------------------------------


def ld(payload: Any) -> str:
    return ld_page(json.dumps(payload))


def test_product_is_found_after_other_json_ld_objects(scraper: GearVNScraper) -> None:
    html = ld_page(
        json.dumps(
            [
                {"@type": "Organization", "name": "GearVN"},
                {"@type": "BreadcrumbList"},
                {"@type": "Product", "brand": {"name": " Razer "}},
            ]
        )
    )
    assert scraper.parse_detail(html, f"{BASE}/products/a").brand_hint == "Razer"


def test_first_product_object_wins_when_a_page_has_two(scraper: GearVNScraper) -> None:
    html = ld([{"@type": "Product", "brand": "A"}, {"@type": "Product", "brand": "B"}])
    assert scraper.parse_detail(html, f"{BASE}/products/a").brand_hint == "A"


def test_json_ld_blocks_after_a_broken_one_are_still_read(scraper: GearVNScraper) -> None:
    good = '<script type="application/ld+json">{"@type": "Product", "brand": "ASUS"}</script>'
    bad = '<script type="application/ld+json">{"@type": "Product", </script>'
    assert (
        scraper.parse_detail(
            f"<html><head>{bad}{good}</head></html>", f"{BASE}/products/a"
        ).brand_hint
        == "ASUS"
    )


@pytest.mark.parametrize("mpn", [12345, ["AL15"], {"v": "x"}, True, None, "", "   "])
def test_mpn_that_is_not_a_non_blank_string_gives_no_model_code(
    scraper: GearVNScraper, mpn: Any
) -> None:
    html = ld({"@type": "Product", "mpn": mpn})
    assert scraper.parse_detail(html, f"{BASE}/products/a").model_code_hint is None


@pytest.mark.parametrize("brand", [5, ["A"], {"name": 5}, {"name": None}, {}, "", None])
def test_brand_of_an_unexpected_type_gives_no_brand_hint(
    scraper: GearVNScraper, brand: Any
) -> None:
    html = ld({"@type": "Product", "brand": brand})
    assert scraper.parse_detail(html, f"{BASE}/products/a").brand_hint is None


def test_labels_and_values_are_stripped_before_merging(scraper: GearVNScraper) -> None:
    props = [
        {"name": " Kết nối ", "value": " USB "},
        {"name": "Kết nối", "value": "USB"},
        {"name": "Kết nối ", "value": "Bluetooth"},
    ]
    html = ld({"@type": "Product", "additionalProperty": props})
    assert scraper.parse_detail(html, f"{BASE}/products/a").raw_specs == {
        "Kết nối": "USB; Bluetooth"
    }


def test_very_long_values_and_thousands_of_properties_are_kept(scraper: GearVNScraper) -> None:
    props = [{"name": f"n{i}", "value": "v"} for i in range(3000)]
    props.append({"name": "dài", "value": "x" * 100_000})
    specs = scraper.parse_detail(
        ld({"@type": "Product", "additionalProperty": props}), f"{BASE}/products/a"
    ).raw_specs
    assert (len(specs), len(specs["dài"])) == (3001, 100_000)


@pytest.mark.parametrize("url", ["not a url", "", f"{BASE}/products/" + "a" * 2100])
def test_parse_detail_rejects_a_bad_page_url_with_value_error(
    scraper: GearVNScraper, url: str
) -> None:
    with pytest.raises(ValueError):
        scraper.parse_detail("<html></html>", url)


def test_parse_detail_strips_tracking_from_the_page_url(scraper: GearVNScraper) -> None:
    detail = scraper.parse_detail("", f"{BASE}/products/a?utm_source=x&fbclid=1#spec")
    assert str(detail.url) == f"{BASE}/products/a"


def test_detail_fixture_specs_do_not_include_the_related_product_cards(
    scraper: GearVNScraper,
) -> None:
    html = fixture(f"detail_{LAPTOP_DETAIL}.html")
    detail = scraper.parse_detail(html, f"{BASE}/products/{LAPTOP_DETAIL}")
    assert "1.990.000đ" not in json.dumps(detail.raw_specs, ensure_ascii=False)
    assert len(detail.raw_specs) == 7


# --- Lỗi đã tái hiện bởi QA M3, đã sửa -----------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("javascript:alert(1)", id="javascript-scheme"),
        pytest.param("http://[bad", id="unparsable"),
        pytest.param("/" + "a" * 2100 + ".jpg", id="overlong"),
    ],
)
def test_unusable_image_src_does_not_discard_the_product(scraper: GearVNScraper, src: str) -> None:
    page = parse_cards(scraper, card(img=f'<img src="{src}">', body="<span>1.990.000đ</span>"))
    assert (len(page.items), page.skipped) == (1, 0)
    assert page.items[0].image_url is None
    assert page.items[0].price == 1_990_000


@pytest.mark.parametrize("href", ["/products", "/products/"])
def test_card_linking_to_the_products_root_without_a_slug_is_skipped(
    scraper: GearVNScraper, href: str
) -> None:
    page = parse_cards(scraper, card(href=href))
    assert (page.items, page.skipped) == ([], 1)


def test_title_with_inline_markup_keeps_the_spaces_between_words(scraper: GearVNScraper) -> None:
    item = parse_cards(scraper, card(title="Chuột <b>Razer</b> <i>Viper</i> V3")).items[0]
    assert item.title == "Chuột Razer Viper V3"


def test_title_inner_whitespace_runs_and_newlines_are_collapsed(scraper: GearVNScraper) -> None:
    item = parse_cards(scraper, card(title="\n   Chuột   Razer\n     Viper  \n")).items[0]
    assert item.title == "Chuột Razer Viper"


def test_product_inside_a_json_ld_graph_is_read(scraper: GearVNScraper) -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage"},
            {
                "@type": "Product",
                "brand": {"name": "Razer"},
                "additionalProperty": [{"name": "Trọng lượng", "value": "59 g"}],
            },
        ],
    }
    detail = scraper.parse_detail(ld(graph), f"{BASE}/products/a")
    assert (detail.brand_hint, detail.raw_specs) == ("Razer", {"Trọng lượng": "59 g"})


def test_deeply_nested_json_ld_is_ignored_instead_of_crashing(scraper: GearVNScraper) -> None:
    nested = "[" * 5000 + "]" * 5000
    detail = scraper.parse_detail(ld_page(nested), f"{BASE}/products/a")
    assert (detail.raw_specs, detail.brand_hint) == ({}, None)


def test_spec_labels_differing_only_in_unicode_form_are_merged(scraper: GearVNScraper) -> None:
    props = [
        {"name": unicodedata.normalize("NFC", "Trọng lượng"), "value": "59 g"},
        {"name": unicodedata.normalize("NFD", "Trọng lượng"), "value": "60 g"},
    ]
    specs = scraper.parse_detail(
        ld({"@type": "Product", "additionalProperty": props}), f"{BASE}/products/a"
    ).raw_specs
    assert len(specs) == 1


def test_search_url_trims_and_normalizes_the_query_to_nfc(scraper: GearVNScraper) -> None:
    nfd = unicodedata.normalize("NFD", "  chuột razer ")
    assert scraper.search_url(nfd) == scraper.search_url("chuột razer")


# --- parsing.py dùng chung ---------------------------------------------------------------------


def test_json_ld_objects_flattens_lists_and_skips_broken_blocks_and_non_objects() -> None:
    html = (
        '<script type="application/ld+json">[{"a": 1}, 5, "x", [{"nested": 1}], {"b": 2}]</script>'
        '<script type="application/ld+json">{broken</script>'
        '<script type="application/ld+json">"just a string"</script>'
        '<script type="application/ld+json">{"c": 3}</script>'
        '<script type="application/json">{"ignored": true}</script>'
    )
    assert json_ld_objects(LexborHTMLParser(html)) == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_node_text_of_a_missing_node_is_an_empty_string_and_text_is_stripped() -> None:
    tree = LexborHTMLParser("<p>\n  Chuột Razer \n</p>")
    assert (node_text(None), node_text(tree.css_first("p"))) == ("", "Chuột Razer")
