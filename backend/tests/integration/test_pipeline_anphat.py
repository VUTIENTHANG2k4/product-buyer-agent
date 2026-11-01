"""Pipeline với AnPhatScraper trên fixture đã lưu (T4.4): PostgreSQL thật, không gọi mạng.

Luồng đầu-cuối trước khi chạy trang thật ở T4.5: thẻ danh sách → offer, trang chi tiết → thông số
có nhãn, kết cục khi chạm giới hạn trang và ở trang cuối.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer
from app.domain.enums import Category, PriceType, ScrapeStatus, ScrapeTrigger, SiteKey, StockStatus
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.scrapers.sites.anphat import AnPhatScraper
from tests.integration.test_pipeline import Clock, ScriptedFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "anphat"
BASE = "https://www.anphatpc.com.vn"
MOUSES = f"{BASE}/chuot-may-tinh_dm1291.html"
MOUSES_P2 = f"{MOUSES}?page=2"
DETAIL_URL = f"{BASE}/chuot-logitech-g102-lightsync.html"


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


async def test_first_mouse_page_is_stored_and_the_page_limit_makes_the_run_partial(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, html("listing_mouse_p1.html"))})
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.anphat, Category.mouse, ScrapeTrigger.test, max_pages=1)

    assert result.status is ScrapeStatus.PARTIAL  # còn trang sau nhưng chạm max_pages (06 §7)
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (1, 30, 0)
    assert result.offers_upserted == 30
    stored = offers(db_session)
    assert len(stored) == 30 and {offer.site for offer in stored} == {SiteKey.anphat}
    assert all(offer.url.startswith(f"{BASE}/") and offer.price > 0 for offer in stored)
    assert {offer.price_type for offer in stored} == {PriceType.sale, PriceType.regular}
    # Thẻ không có thông số nên pipeline thử tải trang chi tiết (ở đây hầu hết đều 404).
    assert [url for url in fetcher.requested if url != MOUSES][0].startswith(f"{BASE}/")


async def test_detail_page_adds_labelled_specs_to_the_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            MOUSES: served(MOUSES, html("listing_mouse_p1.html")),
            DETAIL_URL: served(DETAIL_URL, html("detail_chuot-logitech-g102-lightsync.html")),
        }
    )
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    await pipe.run(SiteKey.anphat, Category.mouse, ScrapeTrigger.test, max_pages=1)

    detailed = next(offer for offer in offers(db_session) if offer.url == DETAIL_URL)
    assert (detailed.price, detailed.list_price) == (389_000, 449_000)
    assert detailed.price_type is PriceType.sale and detailed.stock_status is StockStatus.in_stock
    assert (detailed.rating, detailed.rating_count, detailed.site_sku) == (5.0, 24, "MULG0093")
    assert detailed.raw_specs["Chuẩn giao tiếp"] == "USB"


async def test_last_page_ends_the_run_as_succeeded_with_out_of_stock_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    # Trang cuối nhóm chuột (12 thẻ, đều "Đặt hàng") được phục vụ làm trang 1.
    # Tổng đổi thành 12 để trang này là trang đầu và cũng là trang cuối của một nhóm nhỏ.
    listing = html("listing_mouse_p12.html").replace(
        '<span class="js-show-total">342</span>', '<span class="js-show-total">12</span>'
    )
    pages = {MOUSES: served(MOUSES, listing)}
    for item in (
        AnPhatScraper(ScriptedFetcher({})).parse_listing(listing, Category.mouse, MOUSES).items
    ):
        url = str(item.url)
        pages[url] = served(url, html("detail_chuot-logitech-g102-lightsync.html"))
    fetcher = ScriptedFetcher(dict(pages))
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.anphat, Category.mouse, ScrapeTrigger.test, max_pages=3)

    assert result.status is ScrapeStatus.SUCCEEDED
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (1, 12, 0)
    assert {offer.stock_status for offer in offers(db_session)} == {StockStatus.out_of_stock}
