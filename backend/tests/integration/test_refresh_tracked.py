"""T9.3: làm mới giá offer đang theo dõi (`refresh_offers`, `refresh_tracked`).

Mock-shop qua ASGI + PostgreSQL thật; chỉ trang chi tiết của chính các offer được chọn bị tải.
"""

from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import Session, col, select

from app.config import Settings
from app.db.models import Offer, PriceHistory, Product, ScrapeRun
from app.db.repositories import OfferRepository, ScrapeRunRepository
from app.domain.enums import (
    AlertStatus,
    Category,
    PriceType,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)
from app.domain.errors import OfflineMode, ScrapeAlreadyRunning, SiteCooldown
from app.scrapers import registry
from app.scrapers.http.errors import HttpStatusError
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.services.scrape_service import ScrapeService
from tests.factories import make_offer, make_price_alert, make_product, make_shopping_list
from tests.integration.test_pipeline import (
    BASE,
    NOW,
    Clock,
    RealScraper,
    ScriptedFetcher,
    mock_fetcher,
    page,
)

ASUS = f"{BASE}/p/asus-mock-strix-15-x01-mk-la001"  # giá mock-shop: 15.750.000 ₫
LENOVO = f"{BASE}/p/lenovo-mock-legion-15-x10-mk-la010"  # giá bị che
SETTINGS = Settings(scraper_offline_only=True, scraper_max_listing_pages=5)


class SpyFetcher:
    """Bọc Fetcher thật và ghi lại các URL đã tải (kể cả khi lỗi)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        response: FetchResponse = await self.inner.get(url)
        return response

    async def post_form(self, url: str, data: Any) -> FetchResponse:
        response: FetchResponse = await self.inner.post_form(url, data)
        return response


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def offer_by_url(session: Session, url: str) -> Offer:
    session.expire_all()
    return session.exec(select(Offer).where(col(Offer.url) == url)).one()


def history(session: Session, offer: Offer) -> list[int]:
    session.expire_all()
    rows = session.exec(
        select(PriceHistory).where(PriceHistory.offer_id == offer.id).order_by(col(PriceHistory.id))
    ).all()
    return [row.price for row in rows]


async def crawled(
    session: Session, factory: Callable[[], Session], clock: Clock
) -> tuple[ScrapePipeline, SpyFetcher]:
    """Pipeline + fetcher đã chạy đủ nhóm laptop của mock-shop một lần."""
    spy = SpyFetcher(mock_fetcher())
    pipe = ScrapePipeline(factory, spy, default_max_pages=5, now=clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    spy.requested.clear()
    return pipe, spy


def make_dearer(session: Session, offer: Offer, extra: int = 1_000_000) -> None:
    """Giả lập "lần trước shop bán đắt hơn": lần làm mới sẽ ghi nhận giảm giá."""
    offer.price += extra
    session.add(offer)
    last = session.exec(
        select(PriceHistory).where(PriceHistory.offer_id == offer.id).order_by(col(PriceHistory.id))
    ).all()[-1]
    last.price += extra
    session.flush()


# ---- pipeline.refresh_offers ---------------------------------------------------------------------
async def test_refresh_loads_only_the_detail_page_of_the_chosen_offer_and_records_the_drop(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, spy = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    make_dearer(db_session, asus)
    clock.now = NOW + timedelta(hours=6)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    assert [url for url in spy.requested if not url.endswith("robots.txt")] == [ASUS]
    assert (result.status, result.price_changes, result.changed_offer_ids) == (
        ScrapeStatus.SUCCEEDED,
        1,
        (asus.id,),
    )
    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (1, 0, 1)
    assert offer_by_url(db_session, ASUS).price == 15_750_000
    assert history(db_session, asus) == [16_750_000, 15_750_000]
    run = db_session.get_one(ScrapeRun, result.run_id)
    db_session.refresh(run)
    assert (run.trigger, run.status, run.price_changes) == (
        ScrapeTrigger.tracked_refresh,
        ScrapeStatus.SUCCEEDED,
        1,
    )


async def test_refresh_never_deactivates_or_touches_offers_it_was_not_asked_about(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    stranger = db_session.exec(
        select(Offer).where(col(Offer.url) != ASUS, col(Offer.site) == SiteKey.mockshop)
    ).first()
    assert stranger is not None
    stranger_scraped_at = stranger.scraped_at
    clock.now = NOW + timedelta(days=3)  # đủ lâu để lượt đầy đủ coi các offer khác là "cũ"

    await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    db_session.refresh(stranger)
    assert stranger.is_active is True and stranger.scraped_at == stranger_scraped_at
    assert all(offer.is_active for offer in db_session.exec(select(Offer)).all())


async def test_refresh_with_an_unchanged_price_adds_no_history_and_reports_no_change(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    clock.now = NOW + timedelta(hours=1)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    assert (result.price_changes, result.changed_offer_ids, result.offers_upserted) == (0, (), 1)
    assert history(db_session, asus) == [15_750_000]
    assert offer_by_url(db_session, ASUS).scraped_at == NOW + timedelta(hours=1)


async def test_refresh_keeps_list_price_and_price_type_when_the_page_does_not_tell(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    asus.price_type, asus.list_price = PriceType.sale, 18_000_000
    db_session.flush()

    await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    saved = offer_by_url(db_session, ASUS)
    assert (saved.price_type, saved.list_price, saved.price) == (
        PriceType.sale,
        18_000_000,
        15_750_000,
    )
    assert saved.stock_status is StockStatus.in_stock  # trang cho biết tồn kho


async def test_a_masked_price_keeps_the_old_price_and_counts_as_failed(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    lenovo = offer_by_url(db_session, LENOVO) if _has(db_session, LENOVO) else None
    if lenovo is None:  # sản phẩm giá bị che không được lưu ở lượt đầy đủ: tạo offer thủ công
        product = db_session.exec(select(Product)).first()
        assert product is not None and product.id is not None
        lenovo = make_offer(product.id, site=SiteKey.mockshop, url=LENOVO, price=30_000_000)
        db_session.add(lenovo)
        db_session.flush()

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [lenovo.id or 0])

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (1, 1, 0)
    assert offer_by_url(db_session, LENOVO).price == 30_000_000
    assert offer_by_url(db_session, LENOVO).is_active is True


def _has(session: Session, url: str) -> bool:
    return session.exec(select(Offer).where(col(Offer.url) == url)).first() is not None


async def test_a_gone_product_is_counted_as_failed_but_never_deactivated(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    product = db_session.get_one(Product, asus.product_id)
    ghost = make_offer(product.id or 0, site=SiteKey.mockshop, url=f"{BASE}/p/no-such-product")
    db_session.add(ghost)
    db_session.flush()

    result = await pipe.refresh_offers(
        SiteKey.mockshop, Category.laptop, [ghost.id or 0, asus.id or 0]
    )

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (2, 1, 1)
    assert result.status is ScrapeStatus.PARTIAL  # 1/2 mục lỗi: vượt ngưỡng chất lượng 20%
    db_session.refresh(ghost)
    assert ghost.is_active is True


async def test_three_consecutive_fetch_failures_stop_the_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    product = make_product(category=Category.laptop)
    db_session.add(product)
    db_session.flush()
    offers = [
        make_offer(product.id or 0, site=SiteKey.mockshop, url=f"{BASE}/p/down-{n}")
        for n in range(5)
    ]
    db_session.add_all(offers)
    db_session.flush()
    fetcher = ScriptedFetcher(
        {f"{BASE}/p/down-{n}": HttpStatusError("HTTP 500", url="x", status=500) for n in range(5)}
    )
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(
        SiteKey.mockshop, Category.laptop, [offer.id or 0 for offer in offers]
    )

    assert len(fetcher.requested) == 3
    assert (result.items_parsed, result.items_failed) == (3, 3)
    assert result.status is ScrapeStatus.FAILED
    assert "liên tiếp" in (result.error_message or "")


async def test_only_active_offers_of_the_right_site_and_category_are_refreshed(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, spy = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    product = db_session.get_one(Product, asus.product_id)
    mouse = make_product(category=Category.mouse)
    db_session.add(mouse)
    db_session.flush()
    inactive = make_offer(
        product.id or 0, site=SiteKey.mockshop, url=f"{BASE}/p/off", is_active=False
    )
    other_site = make_offer(
        product.id or 0, site=SiteKey.gearvn, url="https://gearvn.com/products/x"
    )
    other_category = make_offer(mouse.id or 0, site=SiteKey.mockshop, url=f"{BASE}/p/mouse")
    db_session.add_all([inactive, other_site, other_category])
    db_session.flush()
    ids = [inactive.id or 0, other_site.id or 0, other_category.id or 0, 0, 2**40]

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, ids)

    assert (result.items_parsed, result.offers_upserted, result.status) == (
        0,
        0,
        ScrapeStatus.SUCCEEDED,
    )
    assert [url for url in spy.requested if not url.endswith("robots.txt")] == []


async def test_refresh_is_refused_while_a_run_of_the_same_site_and_category_is_active(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.manual)  # RUNNING

    with pytest.raises(ScrapeAlreadyRunning):
        await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])


async def test_a_refresh_run_blocks_a_concurrent_full_run_of_the_same_group(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    ScrapeRunRepository(db_session).create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.tracked_refresh, now=clock.now
    )
    db_session.flush()

    with pytest.raises(ScrapeAlreadyRunning):
        await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.manual)


async def test_a_refresh_run_is_not_the_baseline_for_the_next_full_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, _ = await crawled(db_session, factory, clock)
    full = ScrapeRunRepository(db_session).latest_succeeded(SiteKey.mockshop, Category.laptop)
    assert full is not None and full.items_parsed > 1
    asus = offer_by_url(db_session, ASUS)
    clock.now = NOW + timedelta(hours=1)
    await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [asus.id or 0])

    latest = ScrapeRunRepository(db_session).latest_succeeded(SiteKey.mockshop, Category.laptop)

    assert latest is not None and latest.id == full.id
    assert latest.trigger is ScrapeTrigger.test


async def test_unknown_category_for_the_site_is_rejected_before_a_run_is_created(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = ScrapePipeline(factory, mock_fetcher(), now=clock)

    with pytest.raises(Exception, match="has no category"):
        await pipe.refresh_offers(SiteKey.mockshop, Category.other, [1])

    assert db_session.exec(select(ScrapeRun)).all() == []


async def test_a_challenge_on_a_real_site_blocks_the_run_and_starts_the_cooldown(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.gearvn, RealScraper)
    product = make_product(category=Category.laptop)
    db_session.add(product)
    db_session.flush()
    offer = make_offer(
        product.id or 0, site=SiteKey.gearvn, url="https://shop.example/p/x", price=20_000_000
    )
    db_session.add(offer)
    db_session.flush()
    url = "https://shop.example/p/x"
    fetcher = ScriptedFetcher({url: page("Access denied", url=url, status=403)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(SiteKey.gearvn, Category.laptop, [offer.id or 0])

    assert result.status is ScrapeStatus.BLOCKED
    db_session.refresh(offer)
    assert (offer.price, offer.is_active) == (20_000_000, True)
    with pytest.raises(SiteCooldown):
        await pipe.refresh_offers(SiteKey.gearvn, Category.laptop, [offer.id or 0])


# ---- OfferRepository.list_tracked ----------------------------------------------------------------
def test_list_tracked_returns_active_offers_of_products_with_live_alerts_or_in_a_list(
    db_session: Session,
) -> None:
    alerted, listed, paused, nobody, both = (make_product() for _ in range(5))
    db_session.add_all([alerted, listed, paused, nobody, both])
    db_session.flush()
    offers = {
        name: make_offer(product.id or 0, site=SiteKey.mockshop)
        for name, product in {
            "alerted": alerted,
            "listed": listed,
            "paused": paused,
            "nobody": nobody,
            "both": both,
        }.items()
    }
    inactive = make_offer(alerted.id or 0, site=SiteKey.mockshop, is_active=False)
    other_site = make_offer(alerted.id or 0, site=SiteKey.gearvn)
    db_session.add_all([*offers.values(), inactive, other_site])
    shopping_list = make_shopping_list()
    db_session.add(shopping_list)
    db_session.flush()
    from tests.factories import make_shopping_list_item

    db_session.add_all(
        [
            make_price_alert(alerted.id or 0),
            make_price_alert(paused.id or 0, status=AlertStatus.paused),
            make_price_alert(both.id or 0, status=AlertStatus.triggered),
            make_shopping_list_item(shopping_list.id or 0, listed.id or 0),
            make_shopping_list_item(shopping_list.id or 0, both.id or 0),
        ]
    )
    db_session.flush()

    tracked = OfferRepository(db_session).list_tracked(SiteKey.mockshop)

    assert [t.offer_id for t in tracked] == sorted(
        [offers["alerted"].id or 0, offers["listed"].id or 0, offers["both"].id or 0]
    )
    assert {t.category for t in tracked} == {Category.laptop}


# ---- ScrapeService.refresh_tracked ---------------------------------------------------------------
def service(
    factory: Callable[[], Session],
    fetcher: Any,
    clock: Clock,
    hook: Callable[[Sequence[int]], Any] | None = None,
) -> ScrapeService:
    pipe = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    return ScrapeService(factory, fetcher, SETTINGS, on_price_changes=hook, pipeline=pipe)


async def test_refresh_tracked_touches_only_tracked_offers_and_feeds_the_alert_hook(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, spy = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    other = db_session.exec(
        select(Offer).where(col(Offer.url) != ASUS, col(Offer.site) == SiteKey.mockshop)
    ).first()
    assert other is not None
    make_dearer(db_session, asus)
    make_dearer(db_session, other)
    other_price = other.price
    db_session.add(make_price_alert(asus.product_id, target_price=16_000_000))
    db_session.flush()
    calls: list[tuple[int, ...]] = []

    async def hook(ids: Sequence[int]) -> None:
        calls.append(tuple(ids))

    svc = service(factory, spy, clock, hook)
    clock.now = NOW + timedelta(hours=6)

    results = await svc.refresh_tracked(SiteKey.mockshop)

    assert [(r.site, r.category, r.status) for r in results] == [
        (SiteKey.mockshop, Category.laptop, ScrapeStatus.SUCCEEDED)
    ]
    assert calls == [(asus.id,)]
    assert [url for url in spy.requested if not url.endswith("robots.txt")] == [ASUS]
    assert offer_by_url(db_session, ASUS).price == 15_750_000
    assert offer_by_url(db_session, other.url).price == other_price  # không được theo dõi


async def test_refresh_tracked_with_nothing_tracked_makes_no_request(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    _, spy = await crawled(db_session, factory, clock)

    results = await service(factory, spy, clock).refresh_tracked(SiteKey.mockshop)

    assert results == []
    assert spy.requested == []


async def test_refresh_tracked_refuses_real_sites_in_offline_mode(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry.SCRAPERS, SiteKey.gearvn, RealScraper)
    fetcher = ScriptedFetcher({})

    with pytest.raises(OfflineMode):
        await service(factory, fetcher, clock).refresh_tracked(SiteKey.gearvn)

    assert fetcher.requested == []


async def test_refresh_tracked_skips_a_group_that_is_already_running(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe, spy = await crawled(db_session, factory, clock)
    asus = offer_by_url(db_session, ASUS)
    db_session.add(make_price_alert(asus.product_id))
    db_session.flush()
    await pipe.start(SiteKey.mockshop, Category.laptop, ScrapeTrigger.manual)

    results = await service(factory, spy, clock).refresh_tracked(SiteKey.mockshop)

    assert results == []
    assert spy.requested == []
