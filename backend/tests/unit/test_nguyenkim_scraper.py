"""NguyenKimScraper (app/scrapers/sites/nguyenkim.py) trên fixture đã lưu ở X1.1, không gọi mạng."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.normalize.extract import extract_specs
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.types import FetchResponse
from app.scrapers.registry import SCRAPERS, get_scraper
from app.scrapers.sites.nguyenkim import NguyenKimScraper

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nguyenkim"
BASE = "https://www.nguyenkim.com"
CATEGORY_URL = f"{BASE}/dien-thoai.c"
OPPO_URL = (
    f"{BASE}/dien-thoai-di-dong-oppo-cph2859-8gb-256gb-reno16-f-5g-8gb-256gb-trang-CPH28598GB256GB"
)
NEXT_DATA = re.compile(r'(<script id="__NEXT_DATA__"[^>]*>)(.*?)(</script>)', re.S)


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def scraper() -> NguyenKimScraper:
    return NguyenKimScraper(ScriptedFetcher({}))


def response(url: str, text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text)


class ScriptedFetcher:
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return self.pages[url]


def entry(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": {"vi": "Điện thoại Mock X 8GB/256GB Đen"},
        "code": "MOCKX8256",
        "price": 10_000_000,
        "salePrice": 9_000_000,
        "mediaPrice": 9_000_000,
        "stockStatus": "inStock",
        "slugs": {"value": {"vi": "dien-thoai-mock-x"}, "postfix": "-MOCKX8256"},
        "thumbnail": "https://cdn.example/mock-x.png",
    }
    base.update(changes)
    return base


def next_page(entries: list[Any], *, page: int = 1, pages: int = 1) -> str:
    data = {
        "props": {
            "pageProps": {"pageDetail": {"data": entries, "page": page, "pages": pages, "total": 0}}
        }
    }
    script = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    return f"<html>{script}</html>"


# --- cấu hình -----------------------------------------------------------------------------------


def test_config_describes_nguyen_kim_as_a_phone_only_static_site() -> None:
    config = NguyenKimScraper.config
    assert (config.key, config.base_url, config.min_delay_s) == (SiteKey.nguyenkim, BASE, 5.0)
    assert (config.requires_js, config.supports_live_search, config.is_mock) == (
        False,
        False,
        False,
    )
    assert dict(config.categories) == {Category.phone: CATEGORY_URL}


def test_scraper_is_registered_and_listing_pages_use_the_page_parameter() -> None:
    assert SCRAPERS[SiteKey.nguyenkim] is NguyenKimScraper
    found = get_scraper(SiteKey.nguyenkim, ScriptedFetcher({}))
    assert found.listing_url(Category.phone, 1) == CATEGORY_URL
    assert found.listing_url(Category.phone, 2) == f"{CATEGORY_URL}?page=2"


# --- danh mục -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["listing_phone_p1.html", "listing_phone_p2.html"])
def test_listing_page_has_25_phones_with_prices_and_more_pages(name: str) -> None:
    page = scraper().parse_listing(fixture(name), Category.phone, CATEGORY_URL)

    assert (len(page.items), page.skipped, page.has_next) == (25, 0, True)
    assert page.next_url is None  # URL trang sau do crawl_category dựng bằng listing_url
    urls = [str(item.url) for item in page.items]
    assert len(set(urls)) == 25 and all(url.startswith(f"{BASE}/") for url in urls)
    for item in page.items:
        assert item.site is SiteKey.nguyenkim and item.category_hint is Category.phone
        assert item.price is not None and item.price > 0
        assert item.stock_status is StockStatus.in_stock and item.site_sku
        assert item.raw_specs == {}  # thông số lấy từ trang chi tiết


def test_a_discounted_phone_has_sale_price_and_list_price() -> None:
    first = scraper().parse_listing(fixture("listing_phone_p1.html"), Category.phone, CATEGORY_URL)
    a08 = first.items[0]

    assert a08.title == "Điện thoại Samsung Galaxy A08 4G (4GB, 64GB ) Green"
    assert (a08.price, a08.list_price, a08.price_type) == (4_699_000, 4_790_000, PriceType.sale)
    assert a08.site_sku == "SMA085FZGDXXV"


def test_a_phone_sold_at_list_price_is_regular() -> None:
    first = scraper().parse_listing(fixture("listing_phone_p1.html"), Category.phone, CATEGORY_URL)
    honor = next(item for item in first.items if "Honor Magic V5" in item.title)

    assert (honor.price, honor.list_price, honor.price_type) == (
        44_990_000,
        None,
        PriceType.regular,
    )


def test_product_urls_are_the_slug_plus_postfix_the_site_links_to() -> None:
    html = fixture("listing_phone_p1.html")
    page = scraper().parse_listing(html, Category.phone, CATEGORY_URL)
    urls = {str(item.url) for item in page.items}
    linked = {f"{BASE}{href}" for href in re.findall(r'href="(/[^"?#]+)"', html)}
    product_links = {url for url in linked if "-" in url.removeprefix(BASE)}

    assert OPPO_URL in urls
    assert product_links & urls  # ít nhất các thẻ trang có liên kết thật khớp URL dựng từ slug
    assert not {url for url in product_links if url.endswith("-CPH28598GB256GB")} - urls


def test_last_page_has_no_next_and_pages_are_compared_as_numbers() -> None:
    assert (
        not scraper()
        .parse_listing(next_page([entry()], page=9, pages=9), Category.phone, "x")
        .has_next
    )
    assert (
        scraper().parse_listing(next_page([entry()], page=8, pages=9), Category.phone, "x").has_next
    )
    assert not scraper().parse_listing(next_page([], page=1, pages=9), Category.phone, "x").has_next


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>không có dữ liệu nhúng</body></html>",
        '<script id="__NEXT_DATA__" type="application/json">{không phải json</script>',
        '<script id="__NEXT_DATA__" type="application/json">[]</script>',
        '<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script>',
        "",
    ],
)
def test_pages_without_usable_embedded_data_give_an_empty_page(html: str) -> None:
    page = scraper().parse_listing(html, Category.phone, CATEGORY_URL)
    assert (page.items, page.has_next, page.skipped) == ([], False, 0)


def test_unreadable_entries_are_skipped_and_counted() -> None:
    entries: list[Any] = [
        entry(),
        "not an object",
        entry(slugs=None),
        entry(slugs={"value": {"vi": "a/b"}, "postfix": "-X"}),  # dấu / không thuộc một đoạn
        entry(slugs={"value": {"vi": "a?b"}, "postfix": ""}),
        entry(name={"vi": ""}),
    ]
    page = scraper().parse_listing(next_page(entries), Category.phone, CATEGORY_URL)

    assert [item.title for item in page.items] == ["Điện thoại Mock X 8GB/256GB Đen"]
    assert page.skipped == 5


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (9_000_000, 10_000_000, PriceType.sale)),
        ({"salePrice": 0}, (9_000_000, 10_000_000, PriceType.sale)),  # dùng mediaPrice
        ({"salePrice": None, "mediaPrice": None}, (10_000_000, None, PriceType.regular)),
        ({"price": 9_000_000}, (9_000_000, None, PriceType.regular)),
        ({"price": 8_000_000}, (9_000_000, None, PriceType.regular)),  # giá niêm yết thấp hơn
        ({"price": None, "salePrice": None, "mediaPrice": None}, (None, None, PriceType.unknown)),
        ({"price": "x", "salePrice": True, "mediaPrice": -5}, (None, None, PriceType.unknown)),
        ({"price": 5, "salePrice": 5, "mediaPrice": 5}, (None, None, PriceType.unknown)),
    ],
)
def test_price_rules(
    changes: dict[str, Any], expected: tuple[int | None, int | None, PriceType]
) -> None:
    item = scraper().parse_listing(next_page([entry(**changes)]), Category.phone, "x").items[0]
    assert (item.price, item.list_price, item.price_type) == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("inStock", StockStatus.in_stock),
        ("outOfStock", StockStatus.out_of_stock),
        ("preOrder", StockStatus.preorder),
        ("somethingNew", StockStatus.unknown),
        (None, StockStatus.unknown),
    ],
)
def test_stock_status(status: str | None, expected: StockStatus) -> None:
    item = scraper().parse_listing(next_page([entry(stockStatus=status)]), Category.phone, "x")
    assert item.items[0].stock_status is expected


def test_bad_images_are_dropped_without_losing_the_phone() -> None:
    entries = [
        entry(thumbnail="javascript:alert(1)"),
        entry(thumbnail="data:image/png;base64,AAAA"),
    ]
    page = scraper().parse_listing(next_page(entries), Category.phone, "x")
    assert [item.image_url for item in page.items] == [None, None]


# --- chi tiết -----------------------------------------------------------------------------------

DETAIL = "detail_dien-thoai-oppo-reno16f-8gb-256gb-trang.html"


def test_detail_page_gives_price_stock_brand_and_the_property_table() -> None:
    detail = scraper().parse_detail(fixture(DETAIL), OPPO_URL)

    assert (detail.price, detail.list_price, detail.price_type) == (
        13_599_000,
        15_990_000,
        PriceType.sale,
    )
    assert detail.stock_status is StockStatus.in_stock
    assert detail.brand_hint == "OPPO"
    assert detail.model_code_hint == "CPH2859-8/256/TRANG"
    assert detail.raw_specs["RAM"] == "8 GB"
    assert detail.raw_specs["Dung lượng lưu trữ"] == "256 GB"
    assert detail.raw_specs["Hệ điều hành"] == "Android"
    assert detail.raw_specs["Chip xử lý (CPU)"].startswith("MediaTek Dimensity 7300")
    assert detail.raw_specs["Màu sắc"] == "Trắng"
    assert "Dòng" not in detail.raw_specs  # thuộc tính không có giá trị bị bỏ


def test_title_and_detail_table_give_complete_phone_specs() -> None:
    listing = scraper().parse_listing(
        fixture("listing_phone_p1.html"), Category.phone, CATEGORY_URL
    )
    oppo = next(item for item in listing.items if str(item.url) == OPPO_URL)
    detail = scraper().parse_detail(fixture(DETAIL), OPPO_URL)

    result = extract_specs(Category.phone, oppo.title, detail.raw_specs)

    assert result.specs == {
        "chipset": "MediaTek Dimensity 7300 Energy 5G 8 nhân",
        "ram_gb": 8,
        "storage_gb": 256,
        "screen_in": 6.57,
        "battery_mah": 7000,
        "os": "Android",
    }
    assert (result.missing, result.confidence) == ((), 1.0)


def test_detail_falls_back_to_the_json_ld_price_without_next_data() -> None:
    product = {
        "@type": "Product",
        "name": "Mock",
        "brand": {"@type": "Brand", "name": "Mock"},
        "mpn": "M-1",
        "offers": {"price": 5_500_000, "availability": "https://schema.org/OutOfStock"},
    }
    html = f'<script type="application/ld+json">{json.dumps(product)}</script>'

    detail = scraper().parse_detail(html, f"{BASE}/mock")

    assert (detail.price, detail.list_price, detail.price_type) == (
        5_500_000,
        None,
        PriceType.regular,
    )
    assert (detail.stock_status, detail.brand_hint, detail.model_code_hint) == (
        StockStatus.out_of_stock,
        "Mock",
        "M-1",
    )
    assert detail.raw_specs == {}


def test_detail_of_an_unreadable_page_has_no_price() -> None:
    detail = scraper().parse_detail("<html></html>", f"{BASE}/mock")
    assert (detail.price, detail.price_type, detail.raw_specs) == (None, PriceType.unknown, {})
    assert (detail.brand_hint, detail.model_code_hint) == (None, None)


def test_detail_properties_join_choices_and_drop_empty_or_huge_values() -> None:
    props = [
        {
            "name": {"vi": "Sim"},
            "type": "multipleSelect",
            "values": [{"value": {"vi": "Nano SIM"}}, {"value": {"vi": "eSIM"}}],
        },
        {"name": {"vi": "Rỗng"}, "type": "input", "values": []},
        {"name": {"vi": "Dài"}, "type": "input", "value": {"vi": "x" * 600}},
        {"name": {"vi": "Pin"}, "type": "input", "value": {"vi": "\nPin: 5000 mAh\nSạc: 45W"}},
        {"name": {"vi": "Pin"}, "type": "input", "value": {"vi": "5000 mAh"}},
        "không phải đối tượng",
        {"name": {"vi": ""}, "value": {"vi": "bỏ"}},
    ]
    data = {"props": {"pageProps": {"pageDetail": {"data": {"properties": props}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'

    assert scraper().parse_detail(html, f"{BASE}/mock").raw_specs == {
        "Sim": "Nano SIM; eSIM",
        "Pin": "Pin: 5000 mAh Sạc: 45W; 5000 mAh",
    }


# --- điều phối ----------------------------------------------------------------------------------


async def test_crawl_reads_listing_pages_with_the_page_parameter() -> None:
    page2 = f"{CATEGORY_URL}?page=2"
    fetcher = ScriptedFetcher(
        {
            CATEGORY_URL: response(CATEGORY_URL, fixture("listing_phone_p1.html")),
            page2: response(page2, fixture("listing_phone_p2.html")),
        }
    )

    pages = [p async for p in NguyenKimScraper(fetcher).crawl_category(Category.phone, 2)]

    assert fetcher.requested == [CATEGORY_URL, page2]
    assert [(len(page.items), page.has_next) for page in pages] == [(25, True), (25, True)]


async def test_crawl_stops_at_the_last_page() -> None:
    url = CATEGORY_URL
    fetcher = ScriptedFetcher({url: response(url, next_page([entry()], page=1, pages=1))})

    pages = [p async for p in NguyenKimScraper(fetcher).crawl_category(Category.phone, 5)]

    assert [(len(page.items), page.has_next) for page in pages] == [(1, False)]
    assert fetcher.requested == [url]


async def test_an_empty_first_page_is_a_soft_block_only_when_items_were_expected() -> None:
    empty = ScriptedFetcher({CATEGORY_URL: response(CATEGORY_URL, next_page([]))})
    pages = [p async for p in NguyenKimScraper(empty).crawl_category(Category.phone, 1)]
    assert [len(page.items) for page in pages] == [0]

    with pytest.raises(ChallengeDetected) as caught:
        _ = [
            p
            async for p in NguyenKimScraper(empty).crawl_category(
                Category.phone, 1, expect_items=True
            )
        ]
    assert caught.value.challenge.kind is ChallengeKind.soft_block


async def test_a_blocked_response_raises_challenge_detected() -> None:
    fetcher = ScriptedFetcher({CATEGORY_URL: response(CATEGORY_URL, "Forbidden", status=403)})
    with pytest.raises(ChallengeDetected):
        _ = [p async for p in NguyenKimScraper(fetcher).crawl_category(Category.phone, 1)]


async def test_fetch_detail_goes_through_the_fetcher_and_rejects_foreign_hosts() -> None:
    fetcher = ScriptedFetcher({OPPO_URL: response(OPPO_URL, fixture(DETAIL))})
    scraper_ = NguyenKimScraper(fetcher)

    detail = await scraper_.fetch_detail(OPPO_URL)

    assert detail.price == 13_599_000 and fetcher.requested == [OPPO_URL]
    with pytest.raises(ValueError, match="outside"):
        await scraper_.fetch_detail("https://evil.example/x")
    assert fetcher.requested == [OPPO_URL]


@pytest.mark.parametrize("slug", ["..", ".", "-x", ".hidden", "a/b", "a?b", "a#b", "a b"])
def test_slugs_that_are_not_a_plain_path_segment_are_skipped(slug: str) -> None:
    page = scraper().parse_listing(
        next_page([entry(slugs={"value": {"vi": slug}, "postfix": ""})]), Category.phone, "x"
    )
    assert (page.items, page.skipped) == ([], 1)


async def test_a_repeated_listing_page_stops_the_crawl_and_reports_the_loop() -> None:
    page2 = f"{CATEGORY_URL}?page=2"
    same = fixture("listing_phone_p1.html")  # máy chủ bỏ qua ?page=2
    fetcher = ScriptedFetcher(
        {CATEGORY_URL: response(CATEGORY_URL, same), page2: response(page2, same)}
    )

    pages = [p async for p in NguyenKimScraper(fetcher).crawl_category(Category.phone, 5)]

    assert [(len(page.items), page.pagination_loop) for page in pages] == [(25, False), (0, True)]
    assert fetcher.requested == [CATEGORY_URL, page2]
