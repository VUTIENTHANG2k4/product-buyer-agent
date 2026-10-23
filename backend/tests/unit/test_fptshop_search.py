"""Tìm kiếm tầng 2 của FPT Shop (`search_url`, `parse_search`, `live_search`), không gọi mạng."""

from pathlib import Path

import pytest

from app.domain.dto import ListingItem
from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.robots import parse_robots
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.fptshop import FptShopScraper

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "fptshop"
BASE = "https://fptshop.com.vn"
LOA_URL = f"{BASE}/tim-kiem?s=loa+bluetooth"
SSD_URL = f"{BASE}/tim-kiem?s=ssd+1tb"
NONE_URL = f"{BASE}/tim-kiem?s=zzqxnotfound"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class RecordingFetcher:
    """PageFetcher giả: trả phản hồi định sẵn theo URL và ghi lại các URL đã hỏi."""

    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return self.pages[url]


def page(url: str, name: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=fixture(name))


@pytest.fixture
def scraper() -> FptShopScraper:
    return FptShopScraper(RecordingFetcher({}))


def parse(scraper: FptShopScraper, name: str, url: str) -> list[ListingItem]:
    return scraper.parse_search(fixture(name), url)


# --- search_url ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("loa bluetooth", f"{BASE}/tim-kiem?s=loa+bluetooth"),
        ("  Loa   Bluetooth  ", f"{BASE}/tim-kiem?s=Loa+Bluetooth"),  # khoảng trắng gọn lại
        ("ổ cứng", f"{BASE}/tim-kiem?s=%E1%BB%95+c%E1%BB%A9ng"),
        ("ổ cứng", f"{BASE}/tim-kiem?s=%E1%BB%95+c%E1%BB%A9ng"),  # NFD → NFC
        ("a&b=c", f"{BASE}/tim-kiem?s=a%26b%3Dc"),  # ký tự điều khiển truy vấn bị mã hóa
    ],
)
def test_search_url_encodes_the_query_in_one_s_parameter(
    scraper: FptShopScraper, query: str, expected: str
) -> None:
    assert scraper.search_url(query) == expected


@pytest.mark.parametrize("query", ["loa bluetooth", "t=1", "máy chiếu t=", "ssd 1tb"])
def test_search_url_is_never_blocked_by_the_saved_robots_txt(
    scraper: FptShopScraper, query: str
) -> None:
    rules = parse_robots(fixture("robots.txt"), "ProductBuyerAgent/0.1")
    assert rules.allowed(scraper.search_url(query))


# --- parse_search ----------------------------------------------------------------------------


def test_parse_search_reads_every_card_of_the_speaker_page(scraper: FptShopScraper) -> None:
    items = parse(scraper, "search_loa_bluetooth.html", LOA_URL)

    assert len(items) == 24
    assert len({str(item.url) for item in items}) == 24
    assert all(item.site is SiteKey.fptshop for item in items)
    assert all(item.category_hint is Category.other for item in items)
    assert all(str(item.url).startswith(f"{BASE}/phu-kien/") for item in items)
    assert all(item.title and item.price is not None and item.price > 0 for item in items)


def test_parse_search_reads_a_regular_priced_card(scraper: FptShopScraper) -> None:
    first = parse(scraper, "search_loa_bluetooth.html", LOA_URL)[0]

    assert first.title == "Loa Bluetooth Marshall Stanmore IV"
    assert str(first.url) == f"{BASE}/phu-kien/loa-bluetooth-marshall-stanmore-iv"
    assert (first.price, first.list_price, first.price_type) == (
        12_990_000,
        None,
        PriceType.regular,
    )


@pytest.mark.parametrize(
    ("slug", "price", "list_price"),
    [
        ("loa-bluetooth-marshall-stockwell-iii", 6_690_000, 6_990_000),
        ("loa-bluetooth-marshall-emberton-iii", 4_400_000, 5_390_000),  # giá gốc kèm "-18%"
        ("loa-bluetooth-marshall-willen-ii", 2_550_000, 2_990_000),
    ],
)
def test_parse_search_takes_the_struck_price_as_list_price(
    scraper: FptShopScraper, slug: str, price: int, list_price: int
) -> None:
    by_url = {str(i.url): i for i in parse(scraper, "search_loa_bluetooth.html", LOA_URL)}
    item = by_url[f"{BASE}/phu-kien/{slug}"]

    assert (item.price, item.list_price, item.price_type) == (price, list_price, PriceType.sale)


def test_parse_search_ignores_discount_amount_and_countdown_text_as_prices(
    scraper: FptShopScraper,
) -> None:
    # Thẻ giảm giá có thêm "Giảm 300.000đ" (Stockwell) / "Giảm 990.000đ" (Emberton) và đồng hồ
    # "Còn 00 ngày 00:00:00": không ô nào trong số đó là giá bán.
    by_url = {str(i.url): i for i in parse(scraper, "search_loa_bluetooth.html", LOA_URL)}
    stockwell = by_url[f"{BASE}/phu-kien/loa-bluetooth-marshall-stockwell-iii"]
    emberton = by_url[f"{BASE}/phu-kien/loa-bluetooth-marshall-emberton-iii"]

    assert (stockwell.price, emberton.price) == (6_690_000, 4_400_000)
    assert stockwell.price != 300_000 and emberton.price != 990_000


def test_parse_search_reads_the_other_category_page(scraper: FptShopScraper) -> None:
    items = parse(scraper, "search_ssd_1tb.html", SSD_URL)

    assert len(items) == 13
    assert all(str(item.url).startswith(f"{BASE}/linh-kien/") for item in items)
    assert items[0].price == 2_590_000
    assert all(item.price_type is PriceType.regular for item in items)


def test_parse_search_returns_nothing_for_a_query_without_results(scraper: FptShopScraper) -> None:
    assert parse(scraper, "search_khong_ket_qua.html", NONE_URL) == []


def _card(href: str, title: str, price_block: str) -> str:
    return f'<a href="{href}"><div>{price_block}</div><h3>{title}</h3></a>'


@pytest.mark.parametrize(
    ("price_block", "expected"),
    [
        ("<p>1.290.000đ</p>", 1_290_000),
        ("<p>Liên hệ</p>", None),  # không có ô giá hợp lệ: không đoán
        ("<p>***.000đ</p>", None),  # giá bị che
        ("", None),
        ("<p>9đ</p><p>Giảm 5.000đ</p>", None),  # số không đúng dạng nghìn
    ],
)
def test_parse_search_price_is_none_when_the_card_shows_no_readable_price(
    scraper: FptShopScraper, price_block: str, expected: int | None
) -> None:
    html = _card("/phu-kien/loa-thu", "Loa thử", price_block)
    (item,) = scraper.parse_search(html, LOA_URL)

    assert item.price == expected
    assert item.price_type is (PriceType.regular if expected else PriceType.unknown)


def test_parse_search_ignores_a_struck_price_that_is_not_higher_than_the_sale_price(
    scraper: FptShopScraper,
) -> None:
    block = '<p class="line-through">1.000.000đ</p><p>1.000.000đ</p>'
    (item,) = scraper.parse_search(_card("/phu-kien/loa-thu", "Loa thử", block), LOA_URL)

    assert (item.price, item.list_price, item.price_type) == (1_000_000, None, PriceType.regular)


def test_parse_search_skips_links_that_are_not_product_cards(scraper: FptShopScraper) -> None:
    html = (
        _card("/ho-tro/gioi-thieu/them", "Nhiều cấp", "<p>1.000.000đ</p>")  # đường dẫn 3 cấp
        + _card("https://khac.example/phu-kien/x", "Ngoài trang", "<p>1.000.000đ</p>")
        + _card("/phu-kien/loa-thu?x=1", "Có query", "<p>1.000.000đ</p>")
        + '<a href="/phu-kien/khong-co-h3"><p>2.000.000đ</p></a>'
        + _card("/phu-kien/loa-that", "Loa thật", "<p>3.000.000đ</p>")
    )
    items = scraper.parse_search(html, LOA_URL)

    assert [str(item.url) for item in items] == [f"{BASE}/phu-kien/loa-that"]


def test_parse_search_drops_a_card_with_an_empty_title_and_keeps_the_rest(
    scraper: FptShopScraper,
) -> None:
    html = _card("/phu-kien/trong", "   ", "<p>1.000.000đ</p>") + _card(
        "/phu-kien/con-lai", "Còn lại", "<p>2.000.000đ</p>"
    )
    items = scraper.parse_search(html, LOA_URL)

    assert [item.title for item in items] == ["Còn lại"]


def test_parse_search_lists_a_repeated_product_link_once(scraper: FptShopScraper) -> None:
    card = _card("/phu-kien/loa-thu", "Loa thử", "<p>1.000.000đ</p>")
    assert len(scraper.parse_search(card + card, LOA_URL)) == 1


def test_parse_search_cleans_nul_and_unicode_form_in_the_title(scraper: FptShopScraper) -> None:
    card = _card("/phu-kien/loa-thu", "Loạ\x00 thử", "<p>1.000.000đ</p>")
    (item,) = scraper.parse_search(card, LOA_URL)

    assert item.title == "Loạ thử"
    assert "\x00" not in item.title


def test_parse_search_on_empty_or_garbage_html_returns_nothing(scraper: FptShopScraper) -> None:
    assert scraper.parse_search("", LOA_URL) == []
    assert scraper.parse_search("<html><body>không có gì</body></html>", LOA_URL) == []


# --- live_search -----------------------------------------------------------------------------


async def test_live_search_requests_one_search_page_and_cuts_to_the_limit() -> None:
    fetcher = RecordingFetcher({LOA_URL: page(LOA_URL, "search_loa_bluetooth.html")})
    items = await FptShopScraper(fetcher).live_search("loa bluetooth", 5)

    assert fetcher.requested == [LOA_URL]
    assert len(items) == 5
    assert items[0].title == "Loa Bluetooth Marshall Stanmore IV"


async def test_live_search_returns_an_empty_list_when_nothing_matches() -> None:
    fetcher = RecordingFetcher({NONE_URL: page(NONE_URL, "search_khong_ket_qua.html")})

    assert await FptShopScraper(fetcher).live_search("zzqxnotfound", 10) == []


async def test_live_search_raises_challenge_for_a_blocking_status() -> None:
    blocked = FetchResponse(url=LOA_URL, final_url=LOA_URL, status=403, text="Access denied")
    fetcher = RecordingFetcher({LOA_URL: blocked})

    with pytest.raises(ChallengeDetected) as caught:
        await FptShopScraper(fetcher).live_search("loa bluetooth", 5)

    assert caught.value.challenge.kind is ChallengeKind.http_403


@pytest.mark.parametrize(("query", "limit"), [("   ", 5), ("", 5), ("loa", 0)])
async def test_live_search_rejects_a_blank_query_or_bad_limit_without_a_request(
    query: str, limit: int
) -> None:
    fetcher = RecordingFetcher({})

    with pytest.raises(ValueError):
        await FptShopScraper(fetcher).live_search(query, limit)

    assert fetcher.requested == []
