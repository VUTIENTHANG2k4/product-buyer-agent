"""QA "Chuẩn bị bảo vệ" (T4.7): giá gạch ngang, trần sitemap phụ kiện, chỉ mục sitemap thiếu."""

import logging

import pytest
from selectolax.lexbor import LexborHTMLParser

from app.domain.enums import Category
from app.scrapers.http.errors import SiteLayoutChanged
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.fptshop import (
    MAX_ACCESSORY_SITEMAPS,
    SITEMAP_INDEX_URL,
    FptShopScraper,
    _struck_price,
    select_sitemaps,
)

BASE = "https://fptshop.com.vn"
PRICE = 10_000_000
SHOWN = "10.000.000đ"


def struck(html: str, price: int = PRICE) -> int | None:
    return _struck_price(LexborHTMLParser(f"<body>{html}</body>"), price)


def deep(inner: str, levels: int = 5) -> str:
    return "<div>" * levels + inner + "</div>" * levels


# ---- _struck_price ----------------------------------------------------------------------------
def test_struck_price_next_to_the_first_selling_price_is_read() -> None:
    html = deep(f"<p>{SHOWN}</p><p class='line-through'>12.000.000đ</p>")
    assert struck(html) == 12_000_000


def test_a_related_card_with_the_same_price_and_a_strike_does_not_make_it_a_sale() -> None:
    main = deep(f"<p>{SHOWN}</p>")
    related = deep(f"<p>{SHOWN}</p><p class='line-through'>12.000.000đ</p>")
    assert struck(main + related) is None


def test_the_struck_block_before_the_main_price_still_counts_for_the_same_block() -> None:
    html = deep(f"<p class='line-through'>12.000.000đ</p><p>{SHOWN}</p>")
    assert struck(html) == 12_000_000


@pytest.mark.parametrize("old", ["10.000.000đ", "9.000.000đ", "0đ"])
def test_a_struck_price_not_above_the_selling_price_is_ignored(old: str) -> None:
    assert struck(deep(f"<p>{SHOWN}</p><p class='line-through'>{old}</p>")) is None


def test_without_a_visible_selling_price_nothing_is_struck() -> None:
    # JSON-LD nói 10 triệu nhưng trang không hiện chữ "10.000.000đ".
    assert struck(deep("<p>Liên hệ</p><p class='line-through'>12.000.000đ</p>")) is None


def test_selling_price_with_a_space_before_the_currency_sign_is_not_a_match() -> None:
    assert struck(deep("<p>10.000.000 đ</p><p class='line-through'>12.000.000đ</p>")) is None


def test_two_struck_prices_use_the_first_valid_one_in_the_block() -> None:
    html = deep(f"<p>{SHOWN}</p><p class='line-through'>11.000.000đ</p>")
    html = html.replace("</p></div>", "</p><p class='line-through'>13.000.000đ</p></div>", 1)
    assert struck(html) == 11_000_000


def test_a_flash_sale_block_with_another_price_is_ignored() -> None:
    flash = deep("<p>8.000.000đ</p><p class='line-through'>12.000.000đ</p>")
    assert struck(deep(f"<p>{SHOWN}</p>") + flash) is None


def test_struck_price_text_with_a_discount_suffix_is_not_accepted() -> None:
    assert struck(deep(f"<p>{SHOWN}</p><p class='line-through'>12.000.000đ -18%</p>")) is None


def test_bug_prep_5_shallow_related_card_does_not_borrow_the_main_price() -> None:
    html = (
        f"<main><header><p>{SHOWN}</p></header>"
        f"<section><div class='card'><p>{SHOWN}</p>"
        "<p class='line-through'>12.000.000đ</p></div></section></main>"
    )
    assert struck(html) is None


# ---- select_sitemaps --------------------------------------------------------------------------
def accessory(n: int) -> str:
    return f"{BASE}/products/sitemap-phu-kien{'' if n == 0 else f'-{n}'}.xml"


def test_exactly_the_cap_is_kept_without_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    locs = [accessory(n) for n in range(MAX_ACCESSORY_SITEMAPS)]

    with caplog.at_level(logging.WARNING):
        chosen = select_sitemaps(Category.keyboard, locs)

    assert chosen == locs
    assert not caplog.records


def test_one_over_the_cap_drops_only_the_last_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    locs = [accessory(n) for n in range(MAX_ACCESSORY_SITEMAPS + 1)]

    with caplog.at_level(logging.WARNING):
        chosen = select_sitemaps(Category.headset, locs)

    assert chosen == locs[:MAX_ACCESSORY_SITEMAPS]
    assert len(caplog.records) == 1


def test_duplicates_and_foreign_urls_do_not_use_up_the_cap() -> None:
    locs: list[str] = []
    for n in range(MAX_ACCESSORY_SITEMAPS):
        locs += [accessory(n)] * 5 + [f"http://fptshop.com.vn/products/sitemap-phu-kien-{n}.xml"]
        locs.append(f"https://evil.example/products/sitemap-phu-kien-{n}.xml")
        locs.append(f"{BASE}/products/sitemap-phu-kien-gia-dung-{n}.xml")

    chosen = select_sitemaps(Category.mouse, locs)

    assert chosen == [accessory(n) for n in range(MAX_ACCESSORY_SITEMAPS)]


def test_unsupported_category_selects_nothing() -> None:
    assert select_sitemaps(Category.phone, [accessory(0)]) == []


def test_empty_index_selects_nothing() -> None:
    assert select_sitemaps(Category.laptop, []) == []


# ---- product_urls -----------------------------------------------------------------------------
class Scripted:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return FetchResponse(url=url, final_url=url, status=200, text=self.pages[url])


def index(*locs: str) -> str:
    return "<sitemapindex>" + "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<html><body>Vui lòng thử lại</body></html>",
        "<sitemapindex></sitemapindex>",
        "<sitemapindex><sitemap><loc></loc></sitemap></sitemapindex>",
        "<sitemapindex><sitemap><loc>   </loc></sitemap></sitemapindex>",
        "<sitemapindex><sitemap><image:loc>https://x/y.png</image:loc></sitemap></sitemapindex>",
    ],
)
async def test_an_index_without_any_loc_returns_empty_so_the_run_reports_soft_block(
    body: str,
) -> None:
    fetcher = Scripted({SITEMAP_INDEX_URL: body})

    assert await FptShopScraper(fetcher).product_urls(Category.laptop) == []
    assert fetcher.requested == [SITEMAP_INDEX_URL]


@pytest.mark.parametrize(
    "locs",
    [
        [f"{BASE}/products/sitemap-dien-thoai.xml"],
        ["https://evil.example/products/sitemap-may-tinh-xach-tay.xml"],  # cùng tên, khác máy chủ
    ],
)
async def test_an_index_with_locs_but_no_sitemap_of_the_group_is_a_layout_change(
    locs: list[str],
) -> None:
    fetcher = Scripted({SITEMAP_INDEX_URL: index(*locs)})

    with pytest.raises(SiteLayoutChanged, match="laptop"):
        await FptShopScraper(fetcher).product_urls(Category.laptop)

    assert fetcher.requested == [SITEMAP_INDEX_URL]


async def test_cdata_locs_count_as_locs() -> None:
    body = f"<sitemapindex><sitemap><loc><![CDATA[{BASE}/products/sitemap-x.xml]]></loc></sitemap>"
    fetcher = Scripted({SITEMAP_INDEX_URL: body})

    with pytest.raises(SiteLayoutChanged):
        await FptShopScraper(fetcher).product_urls(Category.laptop)


async def test_a_group_sitemap_without_products_gives_an_empty_list_not_an_error() -> None:
    sitemap = f"{BASE}/products/sitemap-may-tinh-xach-tay.xml"
    fetcher = Scripted({SITEMAP_INDEX_URL: index(sitemap), sitemap: "<urlset></urlset>"})

    assert await FptShopScraper(fetcher).product_urls(Category.laptop) == []


async def test_a_product_in_two_accessory_sitemaps_is_returned_once() -> None:
    first, second = accessory(0), accessory(1)
    url = f"{BASE}/phu-kien/chuot-mock-a"
    fetcher = Scripted(
        {
            SITEMAP_INDEX_URL: index(first, second),
            first: f"<urlset><url><loc>{url}</loc></url></urlset>",
            second: f"<urlset><url><loc>{url}</loc></url></urlset>",
        }
    )

    urls = await FptShopScraper(fetcher).product_urls(Category.mouse)

    assert urls == [url]
    assert fetcher.requested == [SITEMAP_INDEX_URL, first, second]
