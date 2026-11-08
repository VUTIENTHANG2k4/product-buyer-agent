"""FptShopScraper cho điện thoại (X1.3, ADR-0011) trên fixture đã lưu ở X1.1, không gọi mạng."""

from pathlib import Path

from app.domain.dto import ListingPage
from app.domain.enums import Category, PriceType, SiteKey, StockStatus
from app.normalize.extract import extract_specs
from app.scrapers.http.types import FetchResponse
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
PHONE_SITEMAP = f"{BASE}/products/sitemap-dien-thoai.xml"
A57_URL = f"{BASE}/dien-thoai/samsung-galaxy-a57"
IPHONE_URL = f"{BASE}/dien-thoai/iphone-16"
A57_PAGE = "detail_dien-thoai-samsung-galaxy-a57.html"
IPHONE_PAGE = "detail_dien-thoai-iphone-16.html"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def response(url: str, text: str) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=200, text=text)


class ScriptedFetcher:
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return self.pages[url]


def scraper() -> FptShopScraper:
    return FptShopScraper(ScriptedFetcher({}))


# --- sitemap ----------------------------------------------------------------------------------


def test_the_phone_sitemap_is_picked_from_the_saved_index_and_only_for_phones() -> None:
    locs = parse_sitemap_locs(fixture("sitemap_index.xml"))

    assert select_sitemaps(Category.phone, locs) == [PHONE_SITEMAP]
    assert PHONE_SITEMAP not in select_sitemaps(Category.laptop, locs)
    assert select_sitemaps(Category.mouse, locs) == [
        f"{BASE}/products/sitemap-phu-kien.xml",
        f"{BASE}/products/sitemap-phu-kien-1.xml",
        f"{BASE}/products/sitemap-phu-kien-2.xml",
    ]


def test_phone_product_urls_come_from_the_saved_sitemap() -> None:
    urls = select_product_urls(
        Category.phone, parse_sitemap_locs(fixture("sitemap_dien-thoai.xml"))
    )

    assert len(urls) == 221 == len(set(urls))
    assert all(url.startswith(f"{BASE}/dien-thoai/") for url in urls)
    assert A57_URL in urls and IPHONE_URL in urls


def test_phone_selection_ignores_other_sections_queries_and_other_categories() -> None:
    locs = [
        f"{BASE}/dien-thoai/xiaomi-redmi-17-5g",
        f"{BASE}/dien-thoai/xiaomi-redmi-17-5g?t=1",  # robots.txt chặn `/*t=`
        f"{BASE}/dien-thoai/honor-600s#reviews",
        f"{BASE}/may-tinh-xach-tay/laptop-a",
        f"{BASE}/phu-kien/chuot-a",
        f"{BASE}/dien-thoai/nothing/phone-4a",  # sai độ sâu
        "https://evil.example/dien-thoai/fake-phone",
    ]

    assert select_product_urls(Category.phone, locs) == [f"{BASE}/dien-thoai/xiaomi-redmi-17-5g"]
    assert select_product_urls(Category.laptop, locs) == [f"{BASE}/may-tinh-xach-tay/laptop-a"]


def test_phone_is_a_category_of_the_scraper() -> None:
    assert FptShopScraper.config.categories[Category.phone] == f"{BASE}/dien-thoai"


# --- trang sản phẩm ---------------------------------------------------------------------------


def test_samsung_galaxy_a57_page_is_a_discounted_phone_with_the_full_title() -> None:
    item = scraper().parse_product(fixture(A57_PAGE), A57_URL, Category.phone)

    assert item.site is SiteKey.fptshop
    assert str(item.url) == A57_URL
    assert item.title == "Samsung Galaxy A57 5G 8GB 128GB"  # h1 có đủ RAM và bộ nhớ trong
    assert (item.price, item.list_price, item.price_type) == (
        11_290_000,
        13_490_000,
        PriceType.sale,
    )
    assert item.stock_status is StockStatus.in_stock
    assert item.site_sku == "00926836"
    assert item.category_hint is Category.phone
    assert item.raw_specs["RAM"] == "8 GB"


def test_iphone_16_page_has_the_memory_and_chip_in_the_table() -> None:
    item = scraper().parse_product(fixture(IPHONE_PAGE), IPHONE_URL, Category.phone)

    assert item.title == "iPhone 16 128GB"
    assert (item.price, item.list_price, item.price_type) == (
        24_490_000,
        25_690_000,
        PriceType.sale,
    )
    assert item.raw_specs["Bộ nhớ trong"] == "128 GB"
    assert item.raw_specs["Chip xử lý (CPU)"] == "Apple A18"
    assert "Tần số quét" not in item.raw_specs  # giá trị rỗng bị bỏ
    assert all(name != "author" for name in item.raw_specs)  # không lưu tên người đánh giá


def test_page_titles_and_tables_give_complete_phone_specs() -> None:
    a57 = scraper().parse_product(fixture(A57_PAGE), A57_URL, Category.phone)
    iphone = scraper().parse_product(fixture(IPHONE_PAGE), IPHONE_URL, Category.phone)

    a57_specs = extract_specs(Category.phone, a57.title, a57.raw_specs)
    iphone_specs = extract_specs(Category.phone, iphone.title, iphone.raw_specs)

    assert (a57_specs.specs, a57_specs.missing) == (
        {"ram_gb": 8, "storage_gb": 128, "screen_in": 6.7},
        (),
    )
    assert (iphone_specs.specs, iphone_specs.missing) == (
        {"chipset": "Apple A18", "ram_gb": 8, "storage_gb": 128, "screen_in": 6.1},
        (),
    )
    assert a57_specs.confidence == iphone_specs.confidence == 1.0


def test_phone_detail_page_keeps_price_specs_and_brand() -> None:
    detail = scraper().parse_detail(fixture(IPHONE_PAGE), IPHONE_URL)

    assert (detail.price, detail.list_price) == (24_490_000, 25_690_000)
    assert detail.brand_hint == "Apple"
    assert detail.model_code_hint is None  # `mpn` là mã nội bộ của FPT Shop


# --- điều phối --------------------------------------------------------------------------------


async def test_crawl_reads_index_then_the_phone_sitemap_then_product_pages() -> None:
    fetcher = ScriptedFetcher(
        {
            SITEMAP_INDEX_URL: response(SITEMAP_INDEX_URL, fixture("sitemap_index.xml")),
            PHONE_SITEMAP: response(
                PHONE_SITEMAP,
                "<urlset>"
                f"<url><loc>{A57_URL}</loc></url><url><loc>{IPHONE_URL}</loc></url>"
                f"<url><loc>{BASE}/phu-kien/chuot-x</loc></url>"
                "</urlset>",
            ),
            A57_URL: response(A57_URL, fixture(A57_PAGE)),
            IPHONE_URL: response(IPHONE_URL, fixture(IPHONE_PAGE)),
        }
    )

    pages: list[ListingPage] = [
        page async for page in FptShopScraper(fetcher).crawl_category(Category.phone, 3)
    ]

    assert fetcher.requested == [SITEMAP_INDEX_URL, PHONE_SITEMAP, A57_URL, IPHONE_URL]
    assert [(len(page.items), page.has_next, page.skipped) for page in pages] == [(2, False, 0)]
    assert [item.title for item in pages[0].items] == [
        "Samsung Galaxy A57 5G 8GB 128GB",
        "iPhone 16 128GB",
    ]
    assert all(item.category_hint is Category.phone for item in pages[0].items)


def test_a_full_phone_sitemap_needs_twelve_batches() -> None:
    urls = select_product_urls(
        Category.phone, parse_sitemap_locs(fixture("sitemap_dien-thoai.xml"))
    )
    assert -(-len(urls) // BATCH_SIZE) == 12
