"""Pipeline với GearVNScraper trên fixture HTML đã lưu (T3.2): PostgreSQL thật, không gọi mạng.

Chứng minh luồng đầu-cuối trước khi chạy trang thật ở T3.3: thẻ danh sách → offer, giá, trang chi
tiết → `raw_specs` có nhãn, trạng thái cuối khi chạm giới hạn trang.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer
from app.domain.enums import Category, PriceType, ScrapeStatus, ScrapeTrigger, SiteKey
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from tests.integration.test_pipeline import Clock, ScriptedFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"
BASE = "https://gearvn.com"
LAPTOPS = f"{BASE}/collections/laptop"
MOUSES = f"{BASE}/collections/chuot-may-tinh"
DETAIL_SLUG = "laptop-acer-aspire-lite-15-al15-53p-56qh"
DETAIL_URL = f"{BASE}/products/{DETAIL_SLUG}"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def served(url: str, text: str) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=200, text=text)


def offers(session: Session) -> list[Offer]:
    session.expire_all()
    return list(session.exec(select(Offer).order_by(col(Offer.id))))


async def test_first_laptop_page_is_stored_and_the_page_limit_makes_the_run_partial(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({LAPTOPS: served(LAPTOPS, html("listing_laptop_p1.html"))})
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test, max_pages=1)

    assert result.status is ScrapeStatus.PARTIAL  # còn trang sau nhưng chạm max_pages (06 §7)
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (1, 20, 0)
    assert result.offers_upserted == 20
    stored = offers(db_session)
    assert len(stored) == 20 and {offer.site for offer in stored} == {SiteKey.gearvn}
    assert all(offer.url.startswith(f"{BASE}/products/") and offer.price > 0 for offer in stored)
    assert {offer.price_type for offer in stored} == {PriceType.sale, PriceType.regular}
    # Thẻ không có thông số có nhãn → pipeline thử tải trang chi tiết (ở đây tất cả đều 404).
    assert [url for url in fetcher.requested if url != LAPTOPS][0].startswith(f"{BASE}/products/")


async def test_detail_page_adds_labelled_specs_and_the_brand_to_the_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            LAPTOPS: served(LAPTOPS, html("listing_laptop_p1.html")),
            DETAIL_URL: served(DETAIL_URL, html(f"detail_{DETAIL_SLUG}.html")),
        }
    )
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test, max_pages=1)

    detailed = next(offer for offer in offers(db_session) if offer.url == DETAIL_URL)
    assert detailed.price == 19_990_000 and detailed.list_price == 24_990_000
    assert detailed.price_type is PriceType.sale
    assert detailed.raw_specs["Card đồ họa"] == "Intel® UHD Graphics"
    assert detailed.raw_specs["Dung lượng RAM"] == "8 GB"
    assert detailed.stock_status.value == "unknown"


async def test_discontinued_cards_without_a_price_are_failed_items_and_not_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    # Trang cuối của nhóm chuột (19 thẻ, 18 thẻ "Liên hệ tư vấn") được phục vụ làm trang 1.
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, html("listing_mouse_p8.html"))})
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.gearvn, Category.mouse, ScrapeTrigger.test, max_pages=3)

    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (1, 19, 18)
    assert result.offers_upserted == 1
    assert result.status is ScrapeStatus.PARTIAL  # tỷ lệ lỗi > 20%
    assert len(offers(db_session)) == 1
