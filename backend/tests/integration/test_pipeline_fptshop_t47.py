"""T4.7: chỉ mục sitemap FPT Shop thiếu sitemap của nhóm là lượt lỗi, không phải bị chặn."""

from collections.abc import Callable

import pytest
from sqlmodel import Session

from app.domain.enums import Category, ChallengeKind, ScrapeStatus, ScrapeTrigger, SiteKey
from app.scrapers.challenge import ChallengeDetected
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.scrapers.sites.fptshop import (
    MAX_ACCESSORY_SITEMAPS,
    SITEMAP_INDEX_URL,
    FptShopScraper,
    select_sitemaps,
)
from tests.integration.test_pipeline import Clock, ScriptedFetcher

BASE = "https://fptshop.com.vn"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def _index_with(*locs: str) -> ScriptedFetcher:
    body = "<sitemapindex>" + "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    response = FetchResponse(
        url=SITEMAP_INDEX_URL,
        final_url=SITEMAP_INDEX_URL,
        status=200,
        text=body + "</sitemapindex>",
    )
    return ScriptedFetcher({SITEMAP_INDEX_URL: response})


async def test_a_missing_category_sitemap_fails_the_run_without_a_cooldown(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _index_with(f"{BASE}/products/sitemap-dien-thoai.xml")
    pipe = ScrapePipeline(factory, fetcher, now=clock, default_max_pages=5)

    first = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test)
    # Không bị chặn nên chạy lại ngay được (trước đây: BLOCKED + SITE_COOLDOWN 24 giờ).
    second = await pipe.run(SiteKey.fptshop, Category.laptop, ScrapeTrigger.test)

    assert first.status is ScrapeStatus.FAILED and first.challenge is None
    assert first.error_message is not None and "sitemap" in first.error_message
    assert second.status is ScrapeStatus.FAILED
    assert fetcher.requested == [SITEMAP_INDEX_URL, SITEMAP_INDEX_URL]


def test_accessory_sitemaps_are_capped_and_keep_the_index_order() -> None:
    locs = [f"{BASE}/products/sitemap-phu-kien.xml"] + [
        f"{BASE}/products/sitemap-phu-kien-{n}.xml" for n in range(1, 15)
    ]

    chosen = select_sitemaps(Category.mouse, locs)

    assert chosen == locs[:MAX_ACCESSORY_SITEMAPS]


def test_the_laptop_sitemap_is_unaffected_by_the_accessory_cap() -> None:
    laptop = f"{BASE}/products/sitemap-may-tinh-xach-tay.xml"
    locs = [f"{BASE}/products/sitemap-phu-kien-{n}.xml" for n in range(20)] + [laptop]

    assert select_sitemaps(Category.laptop, locs) == [laptop]


async def test_an_index_page_without_any_loc_is_still_treated_as_a_soft_block() -> None:
    """Trang 200 không phải sitemap (ví dụ trang chặn chỉ có chữ) vẫn là `soft_block` như trước
    T4.7 khi lượt trước có sản phẩm (`expect_items`), không phải `SiteLayoutChanged`."""
    page = "<html><body><p>Vui lòng thử lại sau</p></body></html>"
    response = FetchResponse(
        url=SITEMAP_INDEX_URL, final_url=SITEMAP_INDEX_URL, status=200, text=page
    )
    scraper = FptShopScraper(ScriptedFetcher({SITEMAP_INDEX_URL: response}))

    with pytest.raises(ChallengeDetected) as caught:
        async for _ in scraper.crawl_category(Category.laptop, 2, expect_items=True):
            pass

    assert caught.value.challenge.kind is ChallengeKind.soft_block
