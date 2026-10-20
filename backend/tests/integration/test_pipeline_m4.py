"""QA M4: pipeline với FptShopScraper/AnPhatScraper ở các ca biên (PostgreSQL thật, không mạng).

Test `xfail(strict=True)` là lỗi đã tái hiện; khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer
from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.scrapers.sites.fptshop import SITEMAP_INDEX_URL
from tests.integration.test_pipeline import Clock, ScriptedFetcher
from tests.unit.test_anphat_scraper import MOUSE_PAGE, card
from tests.unit.test_fptshop_scraper import ld_page, product_ld

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fptshop"
FPT = "https://fptshop.com.vn"
LAPTOP_SITEMAP = f"{FPT}/products/sitemap-may-tinh-xach-tay.xml"
ACCESSORY_SITEMAP = f"{FPT}/products/sitemap-phu-kien.xml"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def served(url: str, body: str) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=200, text=body)


def sitemap(*urls: str) -> str:
    return "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"


def offer_by_url(session: Session, url: str) -> Offer:
    session.expire_all()
    return session.exec(select(Offer).where(col(Offer.url) == url)).one()


def fpt_fetcher(
    sitemap_url: str, urls: list[str], bodies: dict[str, str] | None = None
) -> ScriptedFetcher:
    """Chỉ mục thật đã lưu + một sitemap + trang sản phẩm; URL thiếu trong `bodies` trả 404."""
    index = (FIXTURES / "sitemap_index.xml").read_text(encoding="utf-8")
    pages: dict[str, FetchResponse | Exception] = {
        SITEMAP_INDEX_URL: served(SITEMAP_INDEX_URL, index),
        sitemap_url: served(sitemap_url, sitemap(*urls)),
    }
    for url, body in (bodies or {}).items():
        pages[url] = served(url, body)
    return ScriptedFetcher(pages)


def product_page(**changes: object) -> str:
    return ld_page(product_ld(**changes))


# --- FPT Shop -----------------------------------------------------------------------------------


async def test_product_that_now_returns_404_is_deactivated_by_a_full_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    urls = [f"{FPT}/may-tinh-xach-tay/laptop-{i}" for i in range(10)]
    bodies = {url: product_page() for url in urls}
    pipe = ScrapePipeline(factory, fpt_fetcher(LAPTOP_SITEMAP, urls, bodies), now=clock)
    first = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=5)
    assert first.status is ScrapeStatus.SUCCEEDED and first.offers_upserted == 10

    clock.now += timedelta(hours=1)
    bodies.pop(urls[9])  # trang sản phẩm đã gỡ: 404, nhưng sitemap chưa cập nhật
    second = await ScrapePipeline(
        factory, fpt_fetcher(LAPTOP_SITEMAP, urls, bodies), now=clock
    ).run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=5)

    assert second.status is ScrapeStatus.SUCCEEDED
    assert offer_by_url(db_session, urls[0]).is_active is True
    assert offer_by_url(db_session, urls[9]).is_active is False


async def test_absurd_review_count_does_not_make_the_whole_offer_fail(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    url = f"{FPT}/may-tinh-xach-tay/laptop-x"
    body = product_page(aggregateRating={"ratingValue": 4, "reviewCount": 3_000_000_000})
    pipe = ScrapePipeline(factory, fpt_fetcher(LAPTOP_SITEMAP, [url], {url: body}), now=clock)

    result = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test, max_pages=2)

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (1, 0, 1)


async def test_accessory_runs_share_one_sitemap_but_never_deactivate_each_others_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    mouse, keyboard = f"{FPT}/phu-kien/chuot-a", f"{FPT}/phu-kien/ban-phim-b"
    bodies = {mouse: product_page(), keyboard: product_page()}
    for number in range(3):
        for category in (Category.mouse, Category.keyboard, Category.mouse):
            fetcher = fpt_fetcher(ACCESSORY_SITEMAP, [mouse, keyboard], bodies)
            for extra in (1, 2):
                url = f"{FPT}/products/sitemap-phu-kien-{extra}.xml"
                fetcher.pages[url] = served(url, sitemap())
            pipe = ScrapePipeline(factory, fetcher, now=clock)
            result = await pipe.run(SiteKey.fptshop, category, ScrapeTrigger.test, max_pages=2)
            assert result.status is ScrapeStatus.SUCCEEDED, (number, category)
            clock.now += timedelta(hours=1)

    assert offer_by_url(db_session, mouse).is_active is True
    assert offer_by_url(db_session, keyboard).is_active is True


# --- An Phát ------------------------------------------------------------------------------------


def anphat_listing(*cards: str) -> str:
    total = f'<a>Xem <span class="js-show-total">{len(cards)}</span> kết quả</a>'
    return f"<body>{total}{''.join(cards)}</body>"


async def test_anphat_price_drop_is_recorded_and_a_contact_for_price_card_is_taken_off_sale(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    hrefs = [f"/chuot-{i}.html" for i in range(6)]
    first_cards = [card(href=href, title=f"Chuột {i}") for i, href in enumerate(hrefs)]
    fetcher = ScriptedFetcher({MOUSE_PAGE: served(MOUSE_PAGE, anphat_listing(*first_cards))})
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    first = await pipe.run(SiteKey.anphat, Category.mouse, ScrapeTrigger.test, max_pages=3)
    assert (first.status, first.items_failed) == (ScrapeStatus.SUCCEEDED, 0)

    clock.now += timedelta(hours=1)
    second_cards = list(first_cards)
    second_cards[0] = card(
        href=hrefs[0], title="Chuột 0", price_block='<span class="p-price">349.000 đ</span>'
    )
    second_cards[5] = card(
        href=hrefs[5], title="Chuột 5", price_block='<span class="p-price">Liên hệ</span>'
    )
    fetcher2 = ScriptedFetcher({MOUSE_PAGE: served(MOUSE_PAGE, anphat_listing(*second_cards))})
    second = await ScrapePipeline(factory, fetcher2, now=clock).run(
        SiteKey.anphat, Category.mouse, ScrapeTrigger.test, max_pages=3
    )

    assert second.status is ScrapeStatus.SUCCEEDED
    assert second.price_changes == 1
    base = "https://www.anphatpc.com.vn"
    assert offer_by_url(db_session, f"{base}{hrefs[0]}").price == 349_000
    assert offer_by_url(db_session, f"{base}{hrefs[1]}").is_active is True
    assert offer_by_url(db_session, f"{base}{hrefs[5]}").is_active is False
