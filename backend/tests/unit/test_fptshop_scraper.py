"""FptShopScraper (app/scrapers/sites/fptshop.py) trên fixture đã lưu ở T4.1, không gọi mạng."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.dto import ListingItem
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.errors import FetchFailed, HttpStatusError
from app.scrapers.http.robots import parse_robots
from app.scrapers.http.types import FetchResponse
from app.scrapers.registry import SCRAPERS, get_scraper
from app.scrapers.sites.fptshop import (
    BATCH_SIZE,
    SITEMAP_INDEX_URL,
    FptShopScraper,
    parse_sitemap_locs,
    select_product_urls,
    select_sitemaps,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "fptshop"
BASE = "https://fptshop.com.vn"
LAPTOP_SITEMAP = f"{BASE}/products/sitemap-may-tinh-xach-tay.xml"
ACCESSORY_SITEMAPS = [
    f"{BASE}/products/sitemap-phu-kien.xml",
    f"{BASE}/products/sitemap-phu-kien-1.xml",
    f"{BASE}/products/sitemap-phu-kien-2.xml",
]
ACER = "laptop-acer-aspire-lite-14-al14-44p-r0sp-r7-7730u"
TUF = "laptop-asus-tuf-gaming-16-fx610jh-tu008w-i5-14450hx"
MOUSE = "chuot-khong-day-elecom-m-ir07dr"
KEYBOARD = "ban-phim-co-khong-day-mchose-g75-pro-v2"
HEADSET = "tai-nghe-corsair-hs50-pro-stereo"
SECTION = {ACER: "may-tinh-xach-tay", TUF: "may-tinh-xach-tay"}


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def detail(slug: str) -> str:
    return fixture(f"detail_{slug}.html")


def product_url(slug: str) -> str:
    return f"{BASE}/{SECTION.get(slug, 'phu-kien')}/{slug.removeprefix('laptop-')}"


def response(url: str, text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text)


class ScriptedFetcher:
    """PageFetcher giả: trả trang hoặc ném lỗi định sẵn theo URL, ghi lại thứ tự request."""

    def __init__(self, pages: dict[str, FetchResponse | Exception]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        item = self.pages[url]
        if isinstance(item, Exception):
            raise item
        return item


def sitemap_xml(*urls: str) -> str:
    entries = "".join(
        f"<url><loc>{url}</loc><image:image><image:loc>{url}.jpg</image:loc></image:image></url>"
        for url in urls
    )
    return f'<?xml version="1.0"?><urlset xmlns:image="x">{entries}</urlset>'


def index_xml(*urls: str) -> str:
    entries = "".join(f"<sitemap><loc>{url}</loc></sitemap>" for url in urls)
    return f'<?xml version="1.0"?><sitemapindex>{entries}</sitemapindex>'


def ld_page(
    product: dict[str, Any] | None, *, h1: str | None = "Sản phẩm thử", extra: str = ""
) -> str:
    ld = (
        f'<script type="application/ld+json">{json.dumps(product, ensure_ascii=False)}</script>'
        if product is not None
        else ""
    )
    heading = f"<h1>{h1}</h1>" if h1 is not None else ""
    return f"<html><head>{ld}</head><body>{heading}{extra}</body></html>"


def product_ld(**changes: Any) -> dict[str, Any]:
    product: dict[str, Any] = {
        "@type": "Product",
        "name": "Chuột thử X",
        "sku": "123",
        "offers": {"@type": "Offer", "price": 299000, "availability": "https://schema.org/InStock"},
    }
    product.update(changes)
    return product


def parse(scraper: FptShopScraper, html: str, category: Category = Category.mouse) -> ListingItem:
    return scraper.parse_product(html, f"{BASE}/phu-kien/chuot-thu-x", category)


def struck(price: str, struck_price: str) -> str:
    """Khối giá gạch ngang giống trang thật: giá bán và giá gốc là hai phần tử gần nhau."""
    return (
        f'<div><span><p>{price}</p></span><span><p class="line-through">{struck_price}</p>'
        "<p>-6%</p></span></div>"
    )


@pytest.fixture
def scraper() -> FptShopScraper:
    return FptShopScraper(ScriptedFetcher({}))


# --- Cấu hình, đăng ký ------------------------------------------------------------------------


def test_config_describes_fptshop() -> None:
    config = FptShopScraper.config
    assert (config.key, config.base_url, config.min_delay_s) == (SiteKey.fptshop, BASE, 5.0)
    assert (config.requires_js, config.supports_live_search, config.is_mock) == (
        False,
        False,
        False,
    )
    assert config.enabled is True
    assert set(config.categories) == {
        Category.laptop,
        Category.mouse,
        Category.keyboard,
        Category.headset,
    }


def test_scraper_is_registered_and_buildable() -> None:
    assert SCRAPERS[SiteKey.fptshop] is FptShopScraper
    assert isinstance(get_scraper(SiteKey.fptshop, ScriptedFetcher({})), FptShopScraper)


def test_category_pages_are_not_parsed_because_fpt_shop_lists_load_through_an_api(
    scraper: FptShopScraper,
) -> None:
    with pytest.raises(NotImplementedError):
        scraper.parse_listing("<html></html>", Category.laptop, f"{BASE}/may-tinh-xach-tay")


def test_every_url_the_scraper_requests_is_allowed_by_the_saved_robots_txt() -> None:
    rules = parse_robots(fixture("robots.txt"), "ProductBuyerAgent/0.1")
    urls = [SITEMAP_INDEX_URL, LAPTOP_SITEMAP, *ACCESSORY_SITEMAPS]
    urls += [product_url(ACER), product_url(MOUSE), product_url(KEYBOARD), product_url(HEADSET)]
    assert all(rules.allowed(url) for url in urls)
    assert not rules.allowed(f"{BASE}/ajax/products")  # chứng minh bộ kiểm tra thật sự chặn


# --- Sitemap ----------------------------------------------------------------------------------


def test_sitemap_locs_skip_image_locs_and_unescape_entities() -> None:
    xml = sitemap_xml(f"{BASE}/phu-kien/a-b", f"{BASE}/phu-kien/c?x=1&amp;y=2")
    assert parse_sitemap_locs(xml) == [f"{BASE}/phu-kien/a-b", f"{BASE}/phu-kien/c?x=1&y=2"]


def test_sitemap_locs_of_garbage_is_empty() -> None:
    assert parse_sitemap_locs("") == []
    assert parse_sitemap_locs("<html>no sitemap here</html>") == []


def test_saved_index_lists_laptop_and_three_accessory_sitemaps() -> None:
    locs = parse_sitemap_locs(fixture("sitemap_index.xml"))
    assert select_sitemaps(Category.laptop, locs) == [LAPTOP_SITEMAP]
    for category in (Category.mouse, Category.keyboard, Category.headset):
        assert select_sitemaps(category, locs) == ACCESSORY_SITEMAPS
    assert f"{BASE}/products/sitemap-phu-kien-gia-dung.xml" in locs  # có trong chỉ mục nhưng bỏ


def test_sitemap_selection_ignores_other_hosts_duplicates_and_unrelated_categories() -> None:
    locs = [
        "https://evil.example/products/sitemap-may-tinh-xach-tay.xml",
        "http://fptshop.com.vn/products/sitemap-may-tinh-xach-tay.xml",
        f"{BASE}/products/sitemap-dien-thoai.xml",
        f"{BASE}/products/sitemap-phu-kien-gia-dung.xml",
        f"{BASE}/sitemap-phu-kien.xml",
        LAPTOP_SITEMAP,
        LAPTOP_SITEMAP,
    ]
    assert select_sitemaps(Category.laptop, locs) == [LAPTOP_SITEMAP]
    assert select_sitemaps(Category.mouse, locs) == []
    assert select_sitemaps(Category.phone, locs) == []


def test_laptop_product_urls_come_from_the_laptop_sitemap() -> None:
    urls = select_product_urls(Category.laptop, parse_sitemap_locs(fixture("sitemap_laptop.xml")))
    assert len(urls) == 80 == len(set(urls))
    assert all(url.startswith(f"{BASE}/may-tinh-xach-tay/") for url in urls)


@pytest.mark.parametrize(
    ("category", "prefix"),
    [
        (Category.mouse, "chuot-"),
        (Category.keyboard, "ban-phim-"),
        (Category.headset, "tai-nghe-"),
    ],
)
def test_accessory_product_urls_are_split_by_slug_prefix(category: Category, prefix: str) -> None:
    locs = parse_sitemap_locs(fixture("sitemap_phu-kien.xml"))
    locs += parse_sitemap_locs(fixture("sitemap_phu-kien-2.xml"))
    urls = select_product_urls(category, locs)
    assert urls
    assert all(url.startswith(f"{BASE}/phu-kien/{prefix}") for url in urls)


def test_accessory_categories_do_not_overlap() -> None:
    locs = parse_sitemap_locs(fixture("sitemap_phu-kien.xml"))
    groups = [
        set(select_product_urls(category, locs))
        for category in (Category.mouse, Category.keyboard, Category.headset)
    ]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])


def test_product_url_selection_drops_foreign_hosts_deep_paths_and_duplicates() -> None:
    locs = [
        f"{BASE}/phu-kien/chuot-a",
        f"{BASE}/phu-kien/chuot-a",
        f"{BASE}/phu-kien/chuot-a?utm_source=x",
        f"{BASE}/phu-kien/chuot-b/extra",
        f"{BASE}/phu-kien/chuot-",
        f"{BASE}/dien-thoai/chuot-c",
        "https://other.example/phu-kien/chuot-d",
        "http://fptshop.com.vn/phu-kien/chuot-e",
        "not a url",
    ]
    assert select_product_urls(Category.mouse, locs) == [
        f"{BASE}/phu-kien/chuot-a",
        f"{BASE}/phu-kien/chuot-",
    ]


def test_product_urls_for_a_category_without_source_are_empty() -> None:
    assert select_product_urls(Category.phone, [f"{BASE}/phu-kien/chuot-a"]) == []


# --- Trang sản phẩm ---------------------------------------------------------------------------


def test_laptop_with_a_discount_reads_public_price_struck_price_and_full_title(
    scraper: FptShopScraper,
) -> None:
    item = scraper.parse_product(detail(ACER), product_url(ACER), Category.laptop)
    assert item.site is SiteKey.fptshop
    assert str(item.url) == product_url(ACER)
    assert (
        item.title == 'Laptop Acer Aspire Lite 14 AL14-44P-R0SP R7 7730U/8GB/512GB/14.5" FHD/Win11'
    )
    # Giá công khai 19.990.000đ; giá flash sale 19.490.000đ (theo suất) không được lưu.
    assert (item.price, item.list_price, item.price_type) == (
        19_990_000,
        21_990_000,
        PriceType.sale,
    )
    assert item.stock_status is StockStatus.in_stock
    assert (item.rating, item.rating_count, item.site_sku) == (4.9, 6, "00930661")
    assert item.category_hint is Category.laptop
    assert str(item.image_url).startswith("https://cdn2.fptshop.com.vn/")
    assert item.raw_specs == {
        "CPU": "Ryzen 7",
        "RAM": "8 GB",
        "Card đồ hoạ": "AMD Radeon 680M Graphics",
        "Kích thước màn hình": "14.5 inch",
        "Tấm nền": "IPS",
    }  # "Thời lượng Pin" có giá trị rỗng nên bị bỏ


def test_gaming_laptop_discount(scraper: FptShopScraper) -> None:
    item = scraper.parse_product(detail(TUF), product_url(TUF), Category.laptop)
    assert (item.price, item.list_price, item.price_type) == (
        38_990_000,
        43_990_000,
        PriceType.sale,
    )
    assert "RTX5050" in item.title and item.raw_specs["RAM"] == "16 GB"


def test_mouse_ignores_the_flash_sale_block(scraper: FptShopScraper) -> None:
    item = scraper.parse_product(detail(MOUSE), product_url(MOUSE), Category.mouse)
    # Khối flash sale "Đã bán 0/20 suất" có giá 219.000đ gạch 319.000đ: không phải giá công khai.
    assert (item.price, item.list_price, item.price_type) == (299_000, 319_000, PriceType.sale)
    assert item.title == "Chuột không dây Elecom M-IR07DR"
    assert item.raw_specs == {
        "Trọng lượng": "52 g",
        "Chuẩn kết nối": "Bluetooth",
        "Độ phân giải": "1200 dpi",
    }


def test_keyboard_without_a_struck_price_is_regular_and_drops_empty_specs(
    scraper: FptShopScraper,
) -> None:
    item = scraper.parse_product(detail(KEYBOARD), product_url(KEYBOARD), Category.keyboard)
    assert (item.price, item.list_price, item.price_type) == (1_690_000, None, PriceType.regular)
    assert item.raw_specs == {"Khoảng cách kết nối": "10", "Kiểu kết nối": "Bluetooth"}


def test_headset_reads_price_and_specs(scraper: FptShopScraper) -> None:
    item = scraper.parse_product(detail(HEADSET), product_url(HEADSET), Category.headset)
    assert (item.price, item.list_price, item.price_type) == (1_290_000, 1_390_000, PriceType.sale)
    assert item.raw_specs["Tính năng"] == "Chống ồn"


def test_parse_product_never_stores_reviewer_names() -> None:
    for slug in (ACER, TUF, MOUSE, KEYBOARD, HEADSET):
        item = FptShopScraper(ScriptedFetcher({})).parse_product(
            detail(slug), product_url(slug), Category.other
        )
        assert "[đã ẩn]" not in item.model_dump_json()


@pytest.mark.parametrize(
    ("offers", "expected"),
    [
        ({"price": 299000}, 299_000),
        ({"price": 299000.0}, 299_000),
        ({"price": "299000"}, 299_000),
        ({"price": 299000.5}, None),
        ({"price": 0}, None),
        ({"price": -5}, None),
        ({"price": 9_999}, None),
        ({"price": 600_000_000}, None),
        ({"price": True}, None),
        ({"price": None}, None),
        ({"price": "Liên hệ"}, None),
        ({}, None),
    ],
)
def test_json_ld_price_is_a_positive_integer_or_none(
    scraper: FptShopScraper, offers: dict[str, Any], expected: int | None
) -> None:
    item = parse(scraper, ld_page(product_ld(offers=offers)))
    assert item.price == expected
    assert item.price_type is (PriceType.regular if expected else PriceType.unknown)


def test_offers_may_be_a_list_and_missing_offers_means_no_price(scraper: FptShopScraper) -> None:
    listed = product_ld(offers=[{"price": 150000}, {"price": 999000}])
    assert parse(scraper, ld_page(listed)).price == 150_000
    no_offers = product_ld()
    del no_offers["offers"]
    item = parse(scraper, ld_page(no_offers))
    assert (item.price, item.price_type, item.stock_status) == (
        None,
        PriceType.unknown,
        StockStatus.unknown,
    )


@pytest.mark.parametrize(
    ("price_html", "struck_html", "expected"),
    [
        ("299.000đ", "319.000đ", 319_000),  # cạnh giá bán, lớn hơn
        ("299.000đ", "299.000đ", None),  # bằng giá bán
        ("299.000đ", "199.000đ", None),  # thấp hơn giá bán
        ("299.000đ", "Liên hệ", None),  # không phải giá
        ("219.000đ", "319.000đ", None),  # khối flash sale: giá bán của khối khác giá công khai
    ],
)
def test_struck_price_must_sit_next_to_the_public_price(
    scraper: FptShopScraper, price_html: str, struck_html: str, expected: int | None
) -> None:
    html = ld_page(product_ld(), extra=struck(price_html, struck_html))
    item = parse(scraper, html)
    assert item.list_price == expected
    assert item.price_type is (PriceType.sale if expected else PriceType.regular)


def test_struck_price_is_none_when_the_public_price_is_unknown(scraper: FptShopScraper) -> None:
    html = ld_page(product_ld(offers={}), extra=struck("299.000đ", "319.000đ"))
    item = parse(scraper, html)
    assert (item.price, item.list_price, item.price_type) == (None, None, PriceType.unknown)


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ("https://schema.org/InStock", StockStatus.in_stock),
        ("http://schema.org/OutOfStock", StockStatus.out_of_stock),
        ("https://schema.org/SoldOut", StockStatus.out_of_stock),
        ("https://schema.org/PreOrder", StockStatus.preorder),
        ("https://schema.org/Whatever", StockStatus.unknown),
        (None, StockStatus.unknown),
        (7, StockStatus.unknown),
    ],
)
def test_availability_maps_to_stock_status(
    scraper: FptShopScraper, availability: object, expected: StockStatus
) -> None:
    offers = {"price": 299000, "availability": availability}
    assert parse(scraper, ld_page(product_ld(offers=offers))).stock_status is expected


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ({"ratingValue": "4.5", "reviewCount": 12}, (4.5, 12)),
        ({"ratingValue": 5, "reviewCount": "7"}, (5.0, 7)),
        ({"ratingValue": "abc", "reviewCount": -1}, (None, None)),
        ({"ratingValue": 9, "reviewCount": True}, (None, None)),
        ("4.5", (None, None)),
        (None, (None, None)),
    ],
)
def test_rating_is_read_only_when_valid(
    scraper: FptShopScraper, block: object, expected: tuple[float | None, int | None]
) -> None:
    item = parse(scraper, ld_page(product_ld(aggregateRating=block)))
    assert (item.rating, item.rating_count) == expected


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("https://cdn.example/a.jpg", "https://cdn.example/a.jpg"),
        ("/img/a.jpg", f"{BASE}/img/a.jpg"),
        (["data:image/png;base64,AAA", "https://cdn.example/b.jpg"], "https://cdn.example/b.jpg"),
        ({"url": "https://cdn.example/c.jpg"}, "https://cdn.example/c.jpg"),
        ("javascript:alert(1)", None),
        ("", None),
        (None, None),
        ([], None),
    ],
)
def test_image_url_is_absolute_http_or_none(
    scraper: FptShopScraper, image: object, expected: str | None
) -> None:
    item = parse(scraper, ld_page(product_ld(image=image)))
    assert (str(item.image_url) if item.image_url else None) == expected


def test_title_falls_back_to_json_ld_name_and_is_normalised(scraper: FptShopScraper) -> None:
    item = parse(scraper, ld_page(product_ld(name="  Chuột\x00 thử  "), h1=None))
    assert item.title == "Chuột thử"
    assert parse(scraper, ld_page(product_ld(), h1="  Chuột \n  hay  ")).title == "Chuột hay"


def test_page_without_json_ld_product_or_title_is_rejected(scraper: FptShopScraper) -> None:
    with pytest.raises(ValueError, match="JSON-LD"):
        parse(scraper, ld_page(None))
    with pytest.raises(ValueError, match="JSON-LD"):
        parse(scraper, ld_page({"@type": "Organization", "name": "FPT"}))
    with pytest.raises(ValidationError):
        parse(scraper, ld_page({"@type": "Product"}, h1=None))


def test_product_type_may_be_a_list_or_sit_in_a_graph(scraper: FptShopScraper) -> None:
    listed = product_ld()
    listed["@type"] = ["Thing", "Product"]
    assert parse(scraper, ld_page(listed)).price == 299_000
    graph = {"@graph": [{"@type": "WebSite"}, product_ld()]}
    assert parse(scraper, ld_page(graph)).price == 299_000  # type: ignore[arg-type]


def test_sku_is_kept_as_site_sku_and_never_as_a_model_code(scraper: FptShopScraper) -> None:
    item = parse(scraper, ld_page(product_ld(sku="  00930661 ", mpn="00930661")))
    assert item.site_sku == "00930661"
    assert parse(scraper, ld_page(product_ld(sku=None))).site_sku is None
    detail_result = scraper.parse_detail(detail(ACER), product_url(ACER))
    assert detail_result.model_code_hint is None


def test_parse_detail_reads_brand_and_specs(scraper: FptShopScraper) -> None:
    result = scraper.parse_detail(detail(ACER), product_url(ACER))
    assert result.brand_hint == "Acer"
    assert result.raw_specs["CPU"] == "Ryzen 7"
    assert str(result.url) == product_url(ACER)


def test_parse_detail_of_a_page_without_product_is_empty(scraper: FptShopScraper) -> None:
    result = scraper.parse_detail(ld_page(None), f"{BASE}/phu-kien/x")
    assert (result.raw_specs, result.brand_hint, result.model_code_hint) == ({}, None, None)


def test_additional_properties_join_repeated_labels_and_skip_bad_entries(
    scraper: FptShopScraper,
) -> None:
    props = [
        {"name": "Màu", "value": "Đen"},
        {"name": "Màu", "value": "Trắng"},
        {"name": "Màu", "value": "Đen"},
        {"name": "Trọng lượng", "value": 52},
        {"name": "Cờ", "value": True},
        {"name": "Rỗng", "value": "   "},
        {"name": 5, "value": "x"},
        {"name": "Danh sách", "value": ["a"]},
        "bad",
    ]
    result = scraper.parse_detail(ld_page(product_ld(additionalProperty=props)), f"{BASE}/p/x")
    assert result.raw_specs == {"Màu": "Đen; Trắng", "Trọng lượng": "52"}
    not_a_list = scraper.parse_detail(
        ld_page(product_ld(additionalProperty={"name": "x"})), f"{BASE}/p/x"
    )
    assert not_a_list.raw_specs == {}


# --- Điều phối --------------------------------------------------------------------------------


def laptop_urls(count: int) -> list[str]:
    return [f"{BASE}/may-tinh-xach-tay/laptop-{i}" for i in range(count)]


def crawl_fetcher(
    urls: list[str], category_sitemap: str = LAPTOP_SITEMAP, **overrides: FetchResponse | Exception
) -> ScriptedFetcher:
    pages: dict[str, FetchResponse | Exception] = {
        SITEMAP_INDEX_URL: response(SITEMAP_INDEX_URL, fixture("sitemap_index.xml")),
        category_sitemap: response(category_sitemap, sitemap_xml(*urls)),
    }
    for url in urls:
        pages[url] = response(url, detail(ACER))
    pages.update(overrides)
    return ScriptedFetcher(pages)


async def collect(scraper: FptShopScraper, **kwargs: Any) -> list[Any]:
    return [page async for page in scraper.crawl_category(Category.laptop, **kwargs)]


async def test_crawl_reads_index_then_sitemap_then_product_pages_in_batches() -> None:
    urls = laptop_urls(BATCH_SIZE + 5)
    fetcher = crawl_fetcher(urls)
    pages = await collect(FptShopScraper(fetcher), max_pages=5)

    assert [len(page.items) for page in pages] == [BATCH_SIZE, 5]
    assert [page.has_next for page in pages] == [True, False]
    assert all(page.next_url is None and page.skipped == 0 for page in pages)
    assert fetcher.requested == [SITEMAP_INDEX_URL, LAPTOP_SITEMAP, *urls]
    assert all(item.site is SiteKey.fptshop for page in pages for item in page.items)


async def test_crawl_stops_at_max_pages_and_reports_that_more_remain() -> None:
    urls = laptop_urls(BATCH_SIZE * 3)
    fetcher = crawl_fetcher(urls)
    pages = await collect(FptShopScraper(fetcher), max_pages=1)

    assert len(pages) == 1 and pages[0].has_next is True
    assert fetcher.requested[2:] == urls[:BATCH_SIZE]  # không tải trang của lô sau


async def test_crawl_can_resume_from_a_later_batch() -> None:
    urls = laptop_urls(BATCH_SIZE + 3)
    fetcher = crawl_fetcher(urls)
    pages = await collect(FptShopScraper(fetcher), max_pages=2, start_page=2)

    assert [len(page.items) for page in pages] == [3]
    assert fetcher.requested[2:] == urls[BATCH_SIZE:]


async def test_crawl_exactly_one_full_batch_has_no_next_page() -> None:
    pages = await collect(FptShopScraper(crawl_fetcher(laptop_urls(BATCH_SIZE))), max_pages=3)
    assert [(len(page.items), page.has_next) for page in pages] == [(BATCH_SIZE, False)]


@pytest.mark.parametrize("category", [Category.mouse, Category.keyboard, Category.headset])
async def test_crawl_reads_the_accessory_sitemaps_and_keeps_only_the_category(
    category: Category,
) -> None:
    prefix = {
        Category.mouse: "chuot-",
        Category.keyboard: "ban-phim-",
        Category.headset: "tai-nghe-",
    }
    mine = [f"{BASE}/phu-kien/{prefix[category]}x{i}" for i in range(2)]
    others = [f"{BASE}/phu-kien/sac-du-phong-{i}" for i in range(3)]
    pages: dict[str, FetchResponse | Exception] = {
        SITEMAP_INDEX_URL: response(SITEMAP_INDEX_URL, fixture("sitemap_index.xml")),
        ACCESSORY_SITEMAPS[0]: response(ACCESSORY_SITEMAPS[0], sitemap_xml(mine[0], *others)),
        ACCESSORY_SITEMAPS[1]: response(ACCESSORY_SITEMAPS[1], sitemap_xml(mine[1])),
        ACCESSORY_SITEMAPS[2]: response(ACCESSORY_SITEMAPS[2], sitemap_xml()),
    }
    pages.update({url: response(url, detail(MOUSE)) for url in mine})
    fetcher = ScriptedFetcher(pages)

    result = [p async for p in FptShopScraper(fetcher).crawl_category(category, 2)]

    assert [str(item.url) for item in result[0].items] == mine
    assert fetcher.requested == [SITEMAP_INDEX_URL, *ACCESSORY_SITEMAPS, *mine]
    assert all(item.category_hint is category for item in result[0].items)


async def test_removed_products_are_skipped_but_other_http_errors_stop_the_run() -> None:
    urls = laptop_urls(3)
    gone = HttpStatusError("HTTP 404", url=urls[1], status=404)
    pages = await collect(FptShopScraper(crawl_fetcher(urls, **{urls[1]: gone})), max_pages=1)
    assert (len(pages[0].items), pages[0].skipped) == (2, 1)

    teapot = HttpStatusError("HTTP 418", url=urls[1], status=418)
    with pytest.raises(HttpStatusError):
        await collect(FptShopScraper(crawl_fetcher(urls, **{urls[1]: teapot})), max_pages=1)
    failed = FetchFailed("HTTP 500 after 3 retries", url=urls[1])
    with pytest.raises(FetchFailed):
        await collect(FptShopScraper(crawl_fetcher(urls, **{urls[1]: failed})), max_pages=1)


async def test_unreadable_product_pages_are_counted_as_skipped() -> None:
    urls = laptop_urls(3)
    broken = response(urls[0], ld_page(None))
    pages = await collect(FptShopScraper(crawl_fetcher(urls, **{urls[0]: broken})), max_pages=1)
    assert (len(pages[0].items), pages[0].skipped) == (2, 1)


async def test_a_challenge_on_a_product_page_raises_challenge_detected() -> None:
    urls = laptop_urls(2)
    blocked = response(urls[0], "forbidden", status=403)
    with pytest.raises(ChallengeDetected) as caught:
        await collect(FptShopScraper(crawl_fetcher(urls, **{urls[0]: blocked})), max_pages=1)
    assert caught.value.challenge.kind is ChallengeKind.http_403


async def test_a_challenge_on_the_sitemap_raises_challenge_detected() -> None:
    blocked = response(SITEMAP_INDEX_URL, "slow down", status=429)
    fetcher = ScriptedFetcher({SITEMAP_INDEX_URL: blocked})
    with pytest.raises(ChallengeDetected) as caught:
        await collect(FptShopScraper(fetcher), max_pages=1)
    assert caught.value.challenge.kind is ChallengeKind.http_429


async def test_an_empty_first_batch_is_a_soft_block_only_when_items_were_expected() -> None:
    urls = laptop_urls(2)
    empty = {url: response(url, ld_page(None)) for url in urls}
    with pytest.raises(ChallengeDetected) as caught:
        await collect(FptShopScraper(crawl_fetcher(urls, **empty)), max_pages=1, expect_items=True)
    assert caught.value.challenge.kind is ChallengeKind.soft_block
    pages = await collect(FptShopScraper(crawl_fetcher(urls, **empty)), max_pages=1)
    assert (len(pages[0].items), pages[0].skipped) == (0, 2)


async def test_an_empty_sitemap_yields_a_single_empty_page() -> None:
    pages = await collect(FptShopScraper(crawl_fetcher([])), max_pages=3)
    assert [(len(page.items), page.has_next) for page in pages] == [(0, False)]


async def test_invalid_arguments_and_unsupported_categories_are_rejected() -> None:
    scraper = FptShopScraper(crawl_fetcher(laptop_urls(1)))
    with pytest.raises(ValueError, match="max_pages"):
        await collect(scraper, max_pages=0)
    with pytest.raises(ValueError, match="max_pages"):
        await collect(scraper, max_pages=1, start_page=0)
    with pytest.raises(ValueError, match="no source"):
        _ = [p async for p in scraper.crawl_category(Category.phone, 1)]


async def test_product_pages_are_read_from_the_final_url_after_redirects() -> None:
    url = laptop_urls(1)[0]
    moved = FetchResponse(
        url=url, final_url=f"{BASE}/may-tinh-xach-tay/new-slug", status=200, text=detail(ACER)
    )
    pages = await collect(FptShopScraper(crawl_fetcher([url], **{url: moved})), max_pages=1)
    assert str(pages[0].items[0].url) == f"{BASE}/may-tinh-xach-tay/new-slug"


async def test_fetch_detail_goes_through_the_fetcher_and_rejects_foreign_hosts() -> None:
    url = product_url(ACER)
    fetcher = ScriptedFetcher({url: response(url, detail(ACER))})
    scraper = FptShopScraper(fetcher)
    result = await scraper.fetch_detail(url)
    assert result.brand_hint == "Acer" and fetcher.requested == [url]
    with pytest.raises(ValueError, match="outside"):
        await scraper.fetch_detail("https://other.example/x")


@pytest.mark.parametrize(
    "name", [f"detail_{slug}.html" for slug in (ACER, TUF, MOUSE, KEYBOARD, HEADSET)]
)
def test_real_pages_are_not_flagged_as_challenges(scraper: FptShopScraper, name: str) -> None:
    """Chữ `captcha` trong script nội tuyến của Next.js không phải challenge (T4.0b)."""
    assert scraper.detect_challenge(response(f"{BASE}/x", fixture(name))) is None
