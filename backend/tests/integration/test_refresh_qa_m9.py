"""QA M9: biên của lượt làm mới giá (`refresh_offers`, `refresh_tracked`) trên PostgreSQL thật."""

import asyncio
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import Session, col, select

from app.db.models import Offer, PriceHistory, ScrapeRun, ShoppingListItem
from app.db.repositories import ScrapeRunRepository
from app.domain.enums import (
    AlertChannel,
    AlertStatus,
    Category,
    MatchMethod,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)
from app.domain.errors import ScrapeAlreadyRunning
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import ScrapePipeline
from app.services.scrape_service import ScrapeService
from tests.factories import make_offer, make_price_alert, make_product, make_shopping_list
from tests.integration.test_pipeline import BASE, NOW, Clock, ScriptedFetcher, page
from tests.integration.test_refresh_tracked import SETTINGS

DETAIL_URL = f"{BASE}/p/mock-qa-1"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def detail_page(price: Any, availability: str | None = "https://schema.org/InStock") -> str:
    offer: dict[str, Any] = {"price": price}
    if availability is not None:
        offer["availability"] = availability
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Mock",
        "offers": offer,
    }
    return (
        f'<html><body><h1>Mock</h1><script type="application/ld+json">{json.dumps(payload)}'
        "</script></body></html>"
    )


def add_tracked_offer(
    session: Session,
    category: Category = Category.laptop,
    *,
    url: str = DETAIL_URL,
    **overrides: Any,
) -> Offer:
    product = make_product(category=category)
    session.add(product)
    session.flush()
    data: dict[str, Any] = {
        "site": SiteKey.mockshop,
        "url": url,
        "price": 20_000_000,
        "scraped_at": NOW - timedelta(days=2),
    }
    offer = make_offer(product.id or 0, **{**data, **overrides})
    session.add(offer)
    session.flush()
    # Cần lịch sử giá từ lần thu thập trước: lần ghi đầu tiên là "first", không phải "đổi giá".
    session.add(
        PriceHistory(offer_id=offer.id or 0, price=offer.price, scraped_at=offer.scraped_at)
    )
    session.flush()
    return offer


def runs(session: Session) -> list[ScrapeRun]:
    session.expire_all()
    return list(session.exec(select(ScrapeRun).order_by(col(ScrapeRun.id))))


class BlockingFetcher(ScriptedFetcher):
    """`get` chờ tới khi được thả: giữ lượt làm mới ở trạng thái RUNNING."""

    def __init__(self) -> None:
        super().__init__({})
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        self.started.set()
        await self.release.wait()
        return page(detail_page(19_000_000), url=url)


# ---- hủy giữa lượt, hai lượt đồng thời -----------------------------------------------------------
async def test_cancelling_a_refresh_closes_the_run_instead_of_leaving_it_running(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(db_session)
    fetcher = BlockingFetcher()
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    task = asyncio.create_task(
        pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])
    )
    await asyncio.wait_for(fetcher.started.wait(), timeout=5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (run,) = runs(db_session)
    assert (run.trigger, run.status) == (ScrapeTrigger.tracked_refresh, ScrapeStatus.FAILED)
    assert "huỷ" in (run.error_message or "")
    db_session.refresh(offer)
    assert offer.price == 20_000_000
    # Nhóm không bị kẹt: lượt kế tiếp chạy được ngay.
    fetcher.release.set()
    again = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])
    assert again.status is ScrapeStatus.SUCCEEDED and again.changed_offer_ids == (offer.id,)


async def test_two_simultaneous_refreshes_of_one_group_run_only_once(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(db_session)
    fetcher = BlockingFetcher()
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    first = asyncio.create_task(
        pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])
    )
    await asyncio.wait_for(fetcher.started.wait(), timeout=5)

    with pytest.raises(ScrapeAlreadyRunning):
        await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])

    fetcher.release.set()
    result = await first
    assert result.status is ScrapeStatus.SUCCEEDED
    assert fetcher.requested.count(DETAIL_URL) == 1
    assert len(runs(db_session)) == 1


@pytest.mark.parametrize(
    ("age", "blocked"),
    [(timedelta(hours=1, minutes=59), True), (timedelta(hours=2, seconds=1), False)],
)
async def test_a_stale_running_refresh_stops_blocking_only_after_two_hours(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    age: timedelta,
    blocked: bool,
) -> None:
    offer = add_tracked_offer(db_session)
    ScrapeRunRepository(db_session).create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.tracked_refresh, now=clock.now - age
    )
    db_session.flush()
    fetcher = ScriptedFetcher({DETAIL_URL: page(detail_page(19_000_000), url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    if blocked:
        with pytest.raises(ScrapeAlreadyRunning):
            await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])
    else:
        result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])
        assert result.status is ScrapeStatus.SUCCEEDED


# ---- danh sách offer_ids ----------------------------------------------------------------------
async def test_duplicate_offer_ids_are_fetched_once_and_counted_once(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(db_session)
    fetcher = ScriptedFetcher({DETAIL_URL: page(detail_page(19_000_000), url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0] * 5)

    assert fetcher.requested == [DETAIL_URL]
    assert (result.items_parsed, result.offers_upserted, result.price_changes) == (1, 1, 1)


async def test_an_empty_id_list_makes_no_request_and_does_not_disturb_the_next_full_run_baseline(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [])

    assert fetcher.requested == []
    assert (result.status, result.items_parsed, result.changed_offer_ids) == (
        ScrapeStatus.SUCCEEDED,
        0,
        (),
    )
    baseline = ScrapeRunRepository(db_session).latest_succeeded(SiteKey.mockshop, Category.laptop)
    assert baseline is None


# ---- trang chi tiết bất thường ----------------------------------------------------------------
async def test_an_offer_whose_url_left_the_site_is_a_failed_item_not_a_request(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    moved = [
        add_tracked_offer(db_session, url=f"https://elsewhere.example/p/{n}") for n in range(4)
    ]
    fetcher = ScriptedFetcher({})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(
        SiteKey.mockshop, Category.laptop, [offer.id or 0 for offer in moved]
    )

    assert fetcher.requested == []  # không bao giờ tải trang ngoài domain của trang
    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (3, 3, 0)
    assert result.status is ScrapeStatus.FAILED
    assert all(db_session.get_one(Offer, offer.id).is_active for offer in moved)


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html></html>",
        detail_page(None),
        detail_page("Liên hệ"),
        detail_page(0),
        detail_page(-5),
        detail_page(9_999),
        detail_page(500_000_001),
        detail_page([]),
        detail_page({"value": 1}),
    ],
)
async def test_an_unreadable_price_on_the_page_keeps_the_stored_offer_untouched(
    db_session: Session, factory: Callable[[], Session], clock: Clock, html: str
) -> None:
    offer = add_tracked_offer(db_session, stock_status=StockStatus.in_stock)
    fetcher = ScriptedFetcher({DETAIL_URL: page(html, url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])

    assert (result.items_parsed, result.items_failed, result.changed_offer_ids) == (1, 1, ())
    db_session.refresh(offer)
    assert (offer.price, offer.stock_status, offer.is_active) == (
        20_000_000,
        StockStatus.in_stock,
        True,
    )
    rows = db_session.exec(select(PriceHistory).where(PriceHistory.offer_id == offer.id)).all()
    assert len(rows) == 1  # chỉ dòng lịch sử có sẵn: không ghi thêm gì


async def test_a_saving_error_on_one_offer_does_not_prevent_the_next_one(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = add_tracked_offer(db_session, url=f"{BASE}/p/mock-qa-a")
    second = add_tracked_offer(db_session, url=f"{BASE}/p/mock-qa-b")
    fetcher = ScriptedFetcher(
        {
            first.url: page(detail_page(19_000_000), url=first.url),
            second.url: page(detail_page(18_000_000), url=second.url),
        }
    )
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    real = ScrapePipeline._save_refresh

    def flaky(self: ScrapePipeline, offer_id: int, detail: Any) -> bool:
        if offer_id == first.id:
            raise ValueError("cannot save")
        return real(self, offer_id, detail)

    monkeypatch.setattr(ScrapePipeline, "_save_refresh", flaky)

    result = await pipe.refresh_offers(
        SiteKey.mockshop, Category.laptop, [first.id or 0, second.id or 0]
    )

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (2, 1, 1)
    assert result.changed_offer_ids == (second.id,)
    db_session.expire_all()
    assert db_session.get_one(Offer, first.id).price == 20_000_000
    assert db_session.get_one(Offer, second.id).price == 18_000_000


async def test_refresh_changes_only_price_and_time_never_the_rest_of_the_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(
        db_session,
        title="Tên đầy đủ có dấu 🔥",
        site_sku="SKU-9",
        rating=4.5,
        rating_count=12,
        raw_specs={"CPU": "Intel Core i7"},
        match_method=MatchMethod.model_code,
        match_score=0.97,
        stock_status=StockStatus.in_stock,
    )
    first_seen = offer.first_seen_at
    clock.now = NOW + timedelta(hours=6)
    fetcher = ScriptedFetcher({DETAIL_URL: page(detail_page(19_000_000), url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])

    db_session.expire_all()
    saved = db_session.get_one(Offer, offer.id)
    assert (saved.title, saved.site_sku, saved.rating, saved.rating_count) == (
        "Tên đầy đủ có dấu 🔥",
        "SKU-9",
        4.5,
        12,
    )
    assert saved.raw_specs == {"CPU": "Intel Core i7"}
    assert (saved.match_method, saved.match_score) == (MatchMethod.model_code, 0.97)
    assert saved.first_seen_at == first_seen and saved.product_id == offer.product_id
    assert (saved.price, saved.scraped_at) == (19_000_000, clock.now)


async def test_a_stock_only_change_is_recorded_but_is_not_reported_as_a_price_change(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(db_session, stock_status=StockStatus.in_stock)
    clock.now = NOW + timedelta(hours=6)
    fetcher = ScriptedFetcher(
        {DETAIL_URL: page(detail_page(20_000_000, "https://schema.org/OutOfStock"), url=DETAIL_URL)}
    )
    pipe = ScrapePipeline(factory, fetcher, now=clock)

    result = await pipe.refresh_offers(SiteKey.mockshop, Category.laptop, [offer.id or 0])

    assert (result.price_changes, result.changed_offer_ids) == (0, ())
    db_session.expire_all()
    saved = db_session.get_one(Offer, offer.id)
    assert saved.stock_status is StockStatus.out_of_stock
    rows = db_session.exec(select(PriceHistory).where(PriceHistory.offer_id == offer.id)).all()
    assert len(rows) == 2
    assert (rows[-1].price, rows[-1].stock_status) == (20_000_000, StockStatus.out_of_stock)


# ---- ScrapeService.refresh_tracked ------------------------------------------------------------
class ExplodingPipeline:
    """Thay `ScrapePipeline`: nhóm laptop ném lỗi không lường trước, nhóm khác thành công."""

    def __init__(self, failing: Category) -> None:
        self.failing = failing
        self.calls: list[Category] = []

    async def refresh_offers(self, site: SiteKey, category: Category, offer_ids: Any) -> Any:
        self.calls.append(category)
        if category is self.failing:
            raise RuntimeError("database connection lost")
        from app.scrapers.pipeline import PipelineResult

        return PipelineResult(
            run_id=1,
            site=site,
            category=category,
            status=ScrapeStatus.SUCCEEDED,
            pages_fetched=1,
            items_parsed=1,
            items_failed=0,
            offers_upserted=1,
            price_changes=0,
            changed_offer_ids=(),
        )


async def test_an_unexpected_error_in_one_category_does_not_skip_the_other_categories(
    db_session: Session, factory: Callable[[], Session]
) -> None:
    """BUG-M9-8: lỗi bất ngờ của nhóm đầu (mất kết nối CSDL khi tạo lượt...) làm bỏ cả các nhóm sau,
    trong khi job `catalog_refresh` cách ly lỗi từng nhóm."""
    laptop = add_tracked_offer(db_session, Category.laptop, url=f"{BASE}/p/mock-qa-l")
    mouse = add_tracked_offer(db_session, Category.mouse, url=f"{BASE}/p/mock-qa-m")
    for offer in (laptop, mouse):
        db_session.add(make_price_alert(offer.product_id, target_price=10_000_000))
    db_session.flush()
    pipeline = ExplodingPipeline(failing=Category.laptop)
    service = ScrapeService(
        factory,
        ScriptedFetcher({}),
        SETTINGS,
        pipeline=pipeline,  # type: ignore[arg-type]
    )

    results = await service.refresh_tracked(SiteKey.mockshop)

    assert set(pipeline.calls) == {Category.laptop, Category.mouse}
    assert [r.category for r in results] == [Category.mouse]


async def test_refresh_tracked_visits_a_product_in_both_an_alert_and_a_list_once(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    offer = add_tracked_offer(db_session)
    db_session.add(make_price_alert(offer.product_id, target_price=10_000_000))
    db_session.add(
        make_price_alert(offer.product_id, target_price=11_000_000, destination="b@x.co")
    )
    shopping = make_shopping_list()
    db_session.add(shopping)
    db_session.flush()
    db_session.add(ShoppingListItem(list_id=shopping.id or 0, product_id=offer.product_id))
    db_session.flush()
    fetcher = ScriptedFetcher({DETAIL_URL: page(detail_page(19_000_000), url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    service = ScrapeService(factory, fetcher, SETTINGS, pipeline=pipe)

    results = await service.refresh_tracked(SiteKey.mockshop)

    assert fetcher.requested == [DETAIL_URL]
    assert [r.items_parsed for r in results] == [1]


async def test_refresh_tracked_ignores_paused_alerts_and_inactive_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    paused = add_tracked_offer(db_session, url=f"{BASE}/p/mock-qa-p")
    retired = add_tracked_offer(db_session, url=f"{BASE}/p/mock-qa-r", is_active=False)
    db_session.add(make_price_alert(paused.product_id, status=AlertStatus.paused))
    db_session.add(make_price_alert(retired.product_id))
    db_session.flush()
    fetcher = ScriptedFetcher({})
    service = ScrapeService(
        factory, fetcher, SETTINGS, pipeline=ScrapePipeline(factory, fetcher, now=clock)
    )

    assert await service.refresh_tracked(SiteKey.mockshop) == []
    assert fetcher.requested == []


# ---- thông báo giá đi cùng lượt làm mới -------------------------------------------------------
async def test_a_failed_send_is_retried_by_the_next_refresh_even_when_the_price_stays_the_same(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    from app.services.alert_evaluation import AlertEvaluator
    from tests.integration.test_alert_evaluation import FakeNotifier
    from tests.service_support import make_settings

    offer = add_tracked_offer(db_session)
    alert = make_price_alert(offer.product_id, target_price=19_500_000)
    db_session.add(alert)
    db_session.flush()
    fetcher = ScriptedFetcher({DETAIL_URL: page(detail_page(19_000_000), url=DETAIL_URL)})
    pipe = ScrapePipeline(factory, fetcher, now=clock)
    notifier = FakeNotifier(fail=True)
    evaluator = AlertEvaluator(factory, {AlertChannel.email: notifier}, make_settings())
    service = ScrapeService(factory, fetcher, SETTINGS, on_price_changes=evaluator, pipeline=pipe)

    first = await service.refresh_tracked(SiteKey.mockshop)
    notifier.fail = False
    clock.now = NOW + timedelta(hours=6)
    second = await service.refresh_tracked(SiteKey.mockshop)
    third = await service.refresh_tracked(SiteKey.mockshop)

    # Giá không đổi ở lượt 2 và 3 nên hook không chạy: gửi lại là việc của lượt quét ở worker.
    assert [r.price_changes for r in first + second + third] == [1, 0, 0]
    assert notifier.sent == []
    assert (await evaluator.evaluate(None)).sent == 1
    assert len(notifier.sent) == 1
    db_session.expire_all()
    assert db_session.get_one(type(alert), alert.id).status is AlertStatus.triggered
