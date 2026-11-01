"""QA M4: ca biên của FptShopScraper (JSON-LD lạ, sitemap lạ, điều phối theo lô), không gọi mạng.

Bổ sung cho `test_fptshop_scraper.py`: không lặp lại các ca đã có ở đó. Test `xfail(strict=True)` là
lỗi đã tái hiện; khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import json
import time
import unicodedata
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.enums import Category, ChallengeKind, PriceType, StockStatus
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.errors import (
    FetchError,
    FetchFailed,
    HttpStatusError,
    RedirectError,
    RobotsBlocked,
    RobotsDisallowed,
    SiteLayoutChanged,
)
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.fptshop import (
    BATCH_SIZE,
    SITEMAP_INDEX_URL,
    FptShopScraper,
    parse_sitemap_locs,
    select_product_urls,
    select_sitemaps,
)
from tests.unit.test_fptshop_scraper import (
    ACER,
    BASE,
    LAPTOP_SITEMAP,
    ScriptedFetcher,
    collect,
    crawl_fetcher,
    detail,
    laptop_urls,
    ld_page,
    parse,
    product_ld,
    response,
    sitemap_xml,
)


@pytest.fixture
def scraper() -> FptShopScraper:
    return FptShopScraper(ScriptedFetcher({}))


def raw_ld(body: str, h1: str = "<h1>Chuột thử X</h1>") -> str:
    """Trang với JSON-LD viết tay (để dùng cả literal JSON không hợp lệ theo chuẩn như NaN)."""
    return (
        f'<html><head><script type="application/ld+json">{body}</script></head>'
        f"<body>{h1}</body></html>"
    )


# --- JSON-LD lạ ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price_literal", "expected"),
    [
        ("NaN", None),
        ("Infinity", None),
        ("-Infinity", None),
        ("1e400", None),  # json.loads cho ra inf
        ("1e6", 1_000_000),  # float nguyên
        ('"1.990.000"', 1_990_000),
        ('"1,990,000"', 1_990_000),
        ('"1990000đ"', 1_990_000),
        ('" 299000 "', 299_000),
        ('"-299000"', None),
        ('""', None),
        ("1" + "0" * 30, None),
        ('"' + "9" * 5_000 + '"', None),  # dài hơn giới hạn 4300 chữ số của int()
        ("[299000]", None),
        ('{"value": 299000}', None),
    ],
)
def test_odd_json_ld_price_literals_become_a_valid_vnd_or_none(
    scraper: FptShopScraper, price_literal: str, expected: int | None
) -> None:
    body = f'{{"@type":"Product","name":"x","offers":{{"price":{price_literal}}}}}'
    item = parse(scraper, raw_ld(body))
    assert item.price == expected
    assert item.price_type is (PriceType.regular if expected else PriceType.unknown)


@pytest.mark.parametrize("offers", [[], ["a"], [None, 5], "https://schema.org/Offer", 12, True])
def test_unusable_offers_mean_no_price_but_the_page_is_still_read(
    scraper: FptShopScraper, offers: object
) -> None:
    item = parse(scraper, ld_page(product_ld(offers=offers)))
    assert (item.price, item.price_type, item.stock_status) == (
        None,
        PriceType.unknown,
        StockStatus.unknown,
    )
    assert item.title == "Sản phẩm thử"


def test_non_dict_entries_before_the_first_offer_object_are_skipped(
    scraper: FptShopScraper,
) -> None:
    offers = [None, "x", {"price": 120000, "availability": "https://schema.org/InStock"}]
    item = parse(scraper, ld_page(product_ld(offers=offers)))
    assert (item.price, item.stock_status) == (120_000, StockStatus.in_stock)


def test_product_is_found_among_several_json_ld_blocks_and_after_a_broken_one(
    scraper: FptShopScraper,
) -> None:
    def block(data: object) -> str:
        return f'<script type="application/ld+json">{json.dumps(data)}</script>'

    html = (
        "<html><head>"
        + '<script type="application/ld+json">{"@type": "Organi</script>'  # hỏng
        + block({"@type": "Organization", "name": "FPT"})
        + block([{"@type": "BreadcrumbList"}, 7, "x", None])
        + block(product_ld())
        + "</head><body><h1>Chuột thử X</h1></body></html>"
    )
    assert parse(scraper, html).price == 299_000


def test_json_ld_that_is_not_closed_rejects_the_page_instead_of_guessing(
    scraper: FptShopScraper,
) -> None:
    html = '<script type="application/ld+json">{"@type":"Product","name":"x"<h1>x</h1>'
    with pytest.raises(ValueError, match="JSON-LD"):
        parse(scraper, html)


@pytest.mark.parametrize("kind", [{"x": 1}, 7, None, [], ["Thing"], "product"])
def test_product_type_that_is_not_exactly_product_is_rejected(
    scraper: FptShopScraper, kind: object
) -> None:
    with pytest.raises(ValueError, match="JSON-LD"):
        parse(scraper, ld_page(product_ld(**{"@type": kind})))


def test_availability_that_is_not_a_string_is_unknown(scraper: FptShopScraper) -> None:
    offers = {"price": 299000, "availability": ["https://schema.org/InStock"]}
    assert parse(scraper, ld_page(product_ld(offers=offers))).stock_status is StockStatus.unknown


def test_vietnamese_title_and_labels_are_nfc_even_when_the_page_is_nfd(
    scraper: FptShopScraper,
) -> None:
    nfd_title = unicodedata.normalize("NFD", "Chuột không dây Elecom")
    nfd_label = unicodedata.normalize("NFD", "Trọng lượng")
    props = [{"name": nfd_label, "value": unicodedata.normalize("NFD", "Nhẹ")}]
    item = parse(scraper, ld_page(product_ld(additionalProperty=props), h1=nfd_title))
    assert item.title == unicodedata.normalize("NFC", nfd_title)
    assert item.raw_specs == {"Trọng lượng": "Nhẹ"}
    assert all(unicodedata.is_normalized("NFC", key) for key in item.raw_specs)


@pytest.mark.parametrize("name", ["   ", "\x00\x00", None, 5])
def test_page_whose_h1_and_json_ld_name_are_both_unusable_is_rejected(
    scraper: FptShopScraper, name: object
) -> None:
    with pytest.raises(ValidationError):
        parse(scraper, ld_page(product_ld(name=name), h1=None))


# --- Lỗi đã tái hiện: JSON-LD ------------------------------------------------------------------


def test_review_count_beyond_the_database_integer_range_does_not_reach_the_item(
    scraper: FptShopScraper,
) -> None:
    rating = {"ratingValue": 4, "reviewCount": 3_000_000_000}
    item = parse(scraper, ld_page(product_ld(aggregateRating=rating)))
    assert item.rating_count is None or item.rating_count <= 2**31 - 1


def test_sku_with_a_nul_character_is_cleaned(scraper: FptShopScraper) -> None:
    item = parse(scraper, ld_page(product_ld(sku="ab\x00c")))
    assert item.site_sku == "abc"


# --- Sitemap lạ ---------------------------------------------------------------------------------


def test_sitemap_locs_trim_whitespace_and_newlines_and_accept_uppercase_tags() -> None:
    xml = f"<URLSET><URL><LOC>\n  {BASE}/phu-kien/chuot-a \n</LOC></URL></URLSET>"
    assert parse_sitemap_locs(xml) == [f"{BASE}/phu-kien/chuot-a"]


def test_sitemap_entities_are_unescaped_once_only() -> None:
    xml = "<loc>https://fptshop.com.vn/phu-kien/chuot-a?x=1&amp;amp;y=2</loc>"
    assert parse_sitemap_locs(xml) == ["https://fptshop.com.vn/phu-kien/chuot-a?x=1&amp;y=2"]


@pytest.mark.parametrize("xml", ["", "<urlset/>", "<urlset></urlset>", "<loc></loc>"])
def test_sitemaps_without_locs_give_no_urls(xml: str) -> None:
    assert parse_sitemap_locs(xml) == []


def test_hostile_hosts_never_pass_the_same_site_check() -> None:
    locs = [
        "https://fptshop.com.vn.evil.example/phu-kien/chuot-a",
        "https://fptshop.com.vn@evil.example/phu-kien/chuot-a",
        "https://evil.example/fptshop.com.vn/phu-kien/chuot-a",
        "https://evil.example#@fptshop.com.vn/phu-kien/chuot-a",
        "https://user:pw@fptshop.com.vn/phu-kien/chuot-a",
        "//fptshop.com.vn/phu-kien/chuot-a",
        "/phu-kien/chuot-a",
        "ftp://fptshop.com.vn/phu-kien/chuot-a",
        "https://fptshop.com.vn:8443/phu-kien/chuot-a",
    ]
    assert select_product_urls(Category.mouse, locs) == []
    sitemaps = [url.replace("/phu-kien/chuot-a", "/products/sitemap-phu-kien.xml") for url in locs]
    assert select_sitemaps(Category.mouse, sitemaps) == []


def test_uppercase_scheme_and_host_are_normalised_to_one_url() -> None:
    locs = ["HTTPS://FPTSHOP.COM.VN/phu-kien/chuot-a", f"{BASE}/phu-kien/chuot-a"]
    assert select_product_urls(Category.mouse, locs) == [f"{BASE}/phu-kien/chuot-a"]


@pytest.mark.parametrize(
    "path", ["/Phu-Kien/chuot-a", "/phu-kien/Chuot-a", "/phu-kien/chuot-a/b", "/phu-kien", "/"]
)
def test_paths_outside_the_expected_shape_are_dropped(path: str) -> None:
    assert select_product_urls(Category.mouse, [f"{BASE}{path}"]) == []


def test_tens_of_thousands_of_locs_are_filtered_and_deduplicated() -> None:
    mine = [f"{BASE}/phu-kien/chuot-{i}" for i in range(30_000)]
    noise = [f"{BASE}/phu-kien/sac-{i}" for i in range(30_000)]
    xml = sitemap_xml(*mine, *noise, *mine[:10_000])
    locs = parse_sitemap_locs(xml)
    assert len(locs) == 70_000
    assert select_product_urls(Category.mouse, locs) == mine


def test_sitemap_index_with_many_unrelated_entries_selects_only_the_category_ones() -> None:
    other = [f"{BASE}/products/sitemap-dien-thoai-{i}.xml" for i in range(500)]
    locs = [
        *other,
        f"{BASE}/products/sitemap-phu-kien.xml",
        f"{BASE}/products/sitemap-phu-kien-7.xml",
    ]
    assert select_sitemaps(Category.headset, locs) == locs[-2:]


# --- Lỗi đã tái hiện: sitemap -----------------------------------------------------------------


def test_sitemap_loc_scan_stays_fast_on_a_long_unclosed_whitespace_run() -> None:
    started = time.perf_counter()
    assert parse_sitemap_locs("<loc>" + " " * 1_500) == []
    assert time.perf_counter() - started < 0.5


def test_cdata_wrapped_loc_is_read() -> None:
    xml = f"<urlset><url><loc><![CDATA[{BASE}/phu-kien/chuot-a]]></loc></url></urlset>"
    assert parse_sitemap_locs(xml) == [f"{BASE}/phu-kien/chuot-a"]


@pytest.mark.parametrize("bad_host", ["https://[fptshop.com.vn", "https://fptshop.com.vn℀"])
def test_one_malformed_loc_is_skipped_instead_of_crashing_the_selection(bad_host: str) -> None:
    locs = [f"{bad_host}/phu-kien/chuot-a", f"{BASE}/phu-kien/chuot-b"]
    assert select_product_urls(Category.mouse, locs) == [f"{BASE}/phu-kien/chuot-b"]
    sitemaps = [
        f"{bad_host}/products/sitemap-phu-kien.xml",
        f"{BASE}/products/sitemap-phu-kien.xml",
    ]
    assert select_sitemaps(Category.mouse, sitemaps) == [f"{BASE}/products/sitemap-phu-kien.xml"]


# --- Điều phối ---------------------------------------------------------------------------------


def crawl_with(
    urls: list[str], overrides: Mapping[str, FetchResponse | Exception]
) -> ScriptedFetcher:
    fetcher = crawl_fetcher(urls)
    fetcher.pages.update(overrides)
    return fetcher


def light_pages(urls: list[str]) -> dict[str, FetchResponse]:
    """Trang sản phẩm tối giản (parse nhanh) cho test chỉ quan tâm số lô."""
    return {u: response(u, ld_page(product_ld())) for u in urls}


async def test_twenty_one_products_make_two_batches_of_twenty_and_one() -> None:
    urls = laptop_urls(BATCH_SIZE + 1)
    first_only = await collect(FptShopScraper(crawl_with(urls, light_pages(urls))), max_pages=1)
    assert [(len(p.items), p.has_next) for p in first_only] == [(BATCH_SIZE, True)]
    both = await collect(FptShopScraper(crawl_with(urls, light_pages(urls))), max_pages=9)
    assert [(len(p.items), p.has_next) for p in both] == [(BATCH_SIZE, True), (1, False)]


async def test_start_page_beyond_the_last_batch_yields_nothing_and_fetches_no_product() -> None:
    urls = laptop_urls(3)
    fetcher = crawl_fetcher(urls)
    pages = await collect(FptShopScraper(fetcher), max_pages=5, start_page=4)
    assert pages == []
    assert fetcher.requested == [SITEMAP_INDEX_URL, LAPTOP_SITEMAP]


async def test_duplicate_urls_across_accessory_sitemaps_are_fetched_once() -> None:
    url = f"{BASE}/phu-kien/chuot-a"
    sitemaps = [f"{BASE}/products/sitemap-phu-kien{suffix}.xml" for suffix in ("", "-1")]
    pages: dict[str, Any] = {
        SITEMAP_INDEX_URL: response(
            SITEMAP_INDEX_URL, "".join(f"<sitemap><loc>{s}</loc></sitemap>" for s in sitemaps)
        ),
        **{s: response(s, sitemap_xml(url)) for s in sitemaps},
        url: response(url, detail(ACER)),
    }
    fetcher = ScriptedFetcher(pages)
    result = [p async for p in FptShopScraper(fetcher).crawl_category(Category.mouse, 3)]
    assert [len(p.items) for p in result] == [1]
    assert fetcher.requested.count(url) == 1


async def test_a_challenge_in_the_second_batch_keeps_the_first_batch_already_delivered() -> None:
    urls = laptop_urls(BATCH_SIZE + 3)
    blocked = {urls[BATCH_SIZE + 1]: response(urls[BATCH_SIZE + 1], "x", status=429)}
    scraper = FptShopScraper(crawl_with(urls, {**light_pages(urls), **blocked}))
    delivered: list[int] = []
    with pytest.raises(ChallengeDetected) as caught:
        async for page in scraper.crawl_category(Category.laptop, 5):
            delivered.append(len(page.items))
    assert delivered == [BATCH_SIZE]
    assert caught.value.challenge.kind is ChallengeKind.http_429


async def test_a_challenge_after_some_fetch_errors_is_still_a_challenge() -> None:
    urls = laptop_urls(5)
    overrides: dict[str, Any] = {
        urls[0]: FetchFailed("HTTP 500 after 3 retries", url=urls[0]),
        urls[1]: FetchFailed("HTTP 500 after 3 retries", url=urls[1]),
        urls[2]: response(urls[2], "denied", status=403),
    }
    with pytest.raises(ChallengeDetected) as caught:
        await collect(FptShopScraper(crawl_with(urls, overrides)), max_pages=1)
    assert caught.value.challenge.kind is ChallengeKind.http_403


async def test_long_runs_of_removed_products_never_stop_the_run() -> None:
    urls = laptop_urls(BATCH_SIZE)
    gone = {u: HttpStatusError("HTTP 404", url=u, status=404) for u in urls[:-1]}
    pages = await collect(FptShopScraper(crawl_with(urls, gone)), max_pages=1)
    assert (len(pages[0].items), pages[0].skipped, pages[0].gone) == (1, 0, BATCH_SIZE - 1)


async def test_expect_items_only_applies_to_the_first_batch() -> None:
    urls = laptop_urls(BATCH_SIZE + 2)
    empty = {u: response(u, ld_page(None)) for u in urls[BATCH_SIZE:]}
    pages = await collect(
        FptShopScraper(crawl_with(urls, {**light_pages(urls), **empty})),
        max_pages=2,
        expect_items=True,
    )
    assert [(len(p.items), p.skipped) for p in pages] == [(BATCH_SIZE, 0), (0, 2)]


async def test_a_few_unreadable_pages_do_not_count_as_a_soft_block() -> None:
    urls = laptop_urls(5)
    broken = {u: response(u, ld_page(None)) for u in urls[:3]}
    pages = await collect(FptShopScraper(crawl_with(urls, broken)), max_pages=1, expect_items=True)
    assert (len(pages[0].items), pages[0].skipped) == (2, 3)


@pytest.mark.parametrize("failing", ["index", "sitemap"])
async def test_sitemap_download_errors_surface_as_fetch_errors_for_the_pipeline(
    failing: str,
) -> None:
    urls = laptop_urls(2)
    target = SITEMAP_INDEX_URL if failing == "index" else LAPTOP_SITEMAP
    fetcher = crawl_with(urls, {target: FetchFailed("HTTP 500 after 3 retries", url=target)})
    with pytest.raises(FetchError):
        await collect(FptShopScraper(fetcher), max_pages=1)


async def test_robots_block_on_a_product_page_still_stops_the_whole_run() -> None:
    urls = laptop_urls(3)
    blocked = RobotsBlocked("robots.txt blocked", url=urls[1], status=403)
    with pytest.raises(RobotsBlocked):
        await collect(FptShopScraper(crawl_with(urls, {urls[1]: blocked})), max_pages=1)


async def test_index_without_the_category_sitemap_is_a_layout_change_not_a_block() -> None:
    """T4.7: trước đây ra một trang rỗng rồi `soft_block` (BLOCKED + nghỉ 24 giờ cả trang)."""
    other = f"{BASE}/products/sitemap-dien-thoai.xml"
    index = response(
        SITEMAP_INDEX_URL, f"<sitemapindex><sitemap><loc>{other}</loc></sitemap></sitemapindex>"
    )
    fetcher = ScriptedFetcher({SITEMAP_INDEX_URL: index})
    with pytest.raises(SiteLayoutChanged, match="laptop"):
        await collect(FptShopScraper(fetcher), max_pages=2, expect_items=True)
    assert fetcher.requested == [SITEMAP_INDEX_URL]


# --- Lỗi đã tái hiện: điều phối ----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        RobotsDisallowed("robots.txt disallows this URL", url="x"),
        RedirectError("redirect leaves the domain", url="x"),
    ],
    ids=["robots-disallowed", "redirect"],
)
async def test_a_single_product_the_fetcher_refuses_is_skipped_not_fatal(error: FetchError) -> None:
    urls = laptop_urls(4)
    pages = await collect(FptShopScraper(crawl_with(urls, {urls[1]: error})), max_pages=1)
    assert (len(pages[0].items), pages[0].skipped) == (3, 1)


async def test_a_first_batch_that_is_entirely_404_is_not_a_soft_block() -> None:
    urls = laptop_urls(3)
    gone = {u: HttpStatusError("HTTP 404", url=u, status=404) for u in urls}
    pages = await collect(FptShopScraper(crawl_with(urls, gone)), max_pages=1, expect_items=True)
    assert (len(pages[0].items), pages[0].skipped, pages[0].gone) == (0, 0, 3)


def test_struck_price_of_a_related_product_card_is_not_taken_for_the_main_product(
    scraper: FptShopScraper,
) -> None:
    related = (
        '<section id="related"><div><div><p>299.000đ</p>'
        '<p class="line-through">349.000đ</p></div></div></section>'
    )
    main = '<div id="main-price"><p>299.000đ</p></div>'
    item = parse(scraper, ld_page(product_ld(), extra=main + related))
    assert (item.price, item.list_price, item.price_type) == (299_000, None, PriceType.regular)


def test_rejected_pages_in_a_batch_are_validation_or_value_errors_only() -> None:
    """Hợp đồng với `crawl_category`: trang hỏng chỉ ném ValueError/ValidationError (bắt được)."""
    scraper = FptShopScraper(ScriptedFetcher({}))
    pages = [
        "",
        "<html></html>",
        "\x00",
        raw_ld("[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["),
        raw_ld('{"@type":"Product"}', h1=""),
        raw_ld('{"@type":"Product","offers":{"price":1,"availability":{}}}', h1=""),
    ]
    for html in pages:
        with pytest.raises((ValueError, ValidationError)):
            scraper.parse_product(html, f"{BASE}/phu-kien/chuot-x", Category.mouse)
