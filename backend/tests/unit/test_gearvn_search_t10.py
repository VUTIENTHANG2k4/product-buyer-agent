"""Tìm kiếm tầng 2 của GearVN với nhóm ngoài tầng 1 ("loa bluetooth"), trên fixture, không mạng."""

from pathlib import Path

from app.domain.enums import Category, PriceType, SiteKey
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.gearvn import GearVNScraper

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"
LOA_URL = "https://gearvn.com/search?q=loa+bluetooth"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class RecordingFetcher:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return FetchResponse(url=url, final_url=url, status=200, text=self.text)


def test_parse_search_reads_the_speaker_cards_as_other_category_items() -> None:
    scraper = GearVNScraper(RecordingFetcher(""))
    items = scraper.parse_search(fixture("search_loa_bluetooth.html"), LOA_URL)

    assert len(items) == 8
    assert all(item.site is SiteKey.gearvn for item in items)
    assert all(item.category_hint is Category.other for item in items)
    assert all(str(item.url).startswith("https://gearvn.com/products/loa-") for item in items)
    assert items[0].title == "Loa Bluetooth Edifier QD35"
    assert (items[0].price, items[0].list_price, items[0].price_type) == (
        2_390_000,
        4_350_000,
        PriceType.sale,
    )


def test_parse_search_reads_a_deep_discount_without_treating_it_as_masked() -> None:
    scraper = GearVNScraper(RecordingFetcher(""))
    items = scraper.parse_search(fixture("search_loa_bluetooth.html"), LOA_URL)
    mp85 = next(item for item in items if "MP85" in item.title)

    assert (mp85.price, mp85.list_price) == (150_000, 450_000)  # -67% thật trên trang


def test_parse_search_returns_nothing_for_a_query_without_results() -> None:
    scraper = GearVNScraper(RecordingFetcher(""))

    assert scraper.parse_search(fixture("search_khong_ket_qua.html"), LOA_URL) == []


async def test_live_search_asks_for_one_page_and_cuts_to_the_limit() -> None:
    fetcher = RecordingFetcher(fixture("search_loa_bluetooth.html"))
    items = await GearVNScraper(fetcher).live_search("loa bluetooth", 3)

    assert fetcher.requested == [LOA_URL]
    assert [item.title for item in items][:1] == ["Loa Bluetooth Edifier QD35"]
    assert len(items) == 3
