"""Pipeline với FptShopScraper trên fixture đã lưu (T4.2): PostgreSQL thật, không gọi mạng.

Luồng đầu-cuối trước khi chạy trang thật ở T4.5: sitemap → trang sản phẩm → offer (giá, giá gốc,
thông số), và kết cục khi chạm giới hạn trang.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer
from app.domain.enums import Category, PriceType, ScrapeStatus, ScrapeTrigger, SiteKey, StockStatus
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.scrapers.sites.fptshop import BATCH_SIZE, SITEMAP_INDEX_URL
from tests.integration.test_pipeline import Clock, ScriptedFetcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fptshop"
BASE = "https://fptshop.com.vn"
LAPTOP_SITEMAP = f"{BASE}/products/sitemap-may-tinh-xach-tay.xml"
ACER_SLUG = "laptop-acer-aspire-lite-14-al14-44p-r0sp-r7-7730u"
TUF_SLUG = "laptop-asus-tuf-gaming-16-fx610jh-tu008w-i5-14450hx"
ACER_URL = f"{BASE}/may-tinh-xach-tay/acer-aspire-lite-14-al14-44p-r0sp-r7-7730u"
TUF_URL = f"{BASE}/may-tinh-xach-tay/asus-tuf-gaming-16-fx610jh-tu008w-i5-14450hx"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def served(url: str, body: str) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=200, text=body)


def sitemap(*urls: str) -> str:
    return "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"


def offers(session: Session) -> list[Offer]:
    session.expire_all()
    return list(session.exec(select(Offer).order_by(col(Offer.id))))


def fetcher_for(*urls: str) -> ScriptedFetcher:
    pages = {
        SITEMAP_INDEX_URL: served(SITEMAP_INDEX_URL, text("sitemap_index.xml")),
        LAPTOP_SITEMAP: served(LAPTOP_SITEMAP, sitemap(*urls)),
    }
    bodies = {ACER_URL: text(f"detail_{ACER_SLUG}.html"), TUF_URL: text(f"detail_{TUF_SLUG}.html")}
    for url in urls:
        pages[url] = served(url, bodies.get(url, bodies[ACER_URL]))
    return ScriptedFetcher(dict(pages))


async def test_laptop_run_stores_offers_with_prices_and_specs_without_extra_detail_requests(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = fetcher_for(ACER_URL, TUF_URL)
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=5)

    assert result.status is ScrapeStatus.SUCCEEDED
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (1, 2, 0)
    assert result.offers_upserted == 2
    # Thông số đã có trên mục nên pipeline không tải lại trang chi tiết.
    assert fetcher.requested == [SITEMAP_INDEX_URL, LAPTOP_SITEMAP, ACER_URL, TUF_URL]
    stored = {offer.url: offer for offer in offers(db_session)}
    acer = stored[ACER_URL]
    assert (acer.site, acer.price, acer.list_price) == (SiteKey.fptshop, 19_990_000, 21_990_000)
    assert acer.price_type is PriceType.sale and acer.stock_status is StockStatus.in_stock
    assert acer.raw_specs["CPU"] == "Ryzen 7"
    assert (acer.rating, acer.rating_count, acer.site_sku) == (4.9, 6, "00930661")
    assert stored[TUF_URL].price == 38_990_000


async def test_page_limit_makes_the_run_partial_and_fetches_only_the_first_batch(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    urls = [f"{BASE}/may-tinh-xach-tay/laptop-{i}" for i in range(BATCH_SIZE + 2)]
    fetcher = fetcher_for(*urls)
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    result = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=1)

    assert result.status is ScrapeStatus.PARTIAL  # còn lô sau nhưng chạm max_pages
    assert (result.pages_fetched, result.items_parsed) == (1, BATCH_SIZE)
    assert len(offers(db_session)) == BATCH_SIZE
    assert fetcher.requested[2:] == urls[:BATCH_SIZE]


async def test_second_run_updates_the_same_offers_without_duplicates(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = ScrapePipeline(factory, fetcher_for(ACER_URL), now=clock, default_max_pages=5)
    await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=5)
    second = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=5)

    assert second.status is ScrapeStatus.SUCCEEDED and second.price_changes == 0
    assert len(offers(db_session)) == 1
