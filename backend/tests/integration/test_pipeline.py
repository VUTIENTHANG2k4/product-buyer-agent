"""ScrapePipeline (app/scrapers/pipeline.py): PostgreSQL thật + mock-shop qua ASGI, không mạng.

Mỗi test dùng `db_session` (rollback cuối test); pipeline mở session riêng trên cùng connection
nên `commit()` của nó chỉ giải phóng savepoint.
"""

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
import pytest
from sqlalchemy import func, text
from sqlmodel import Session, col, select

from app.config import Settings
from app.db.models import Offer, PriceHistory, Product, ScrapeRun
from app.db.repositories import OfferRepository, OfferUpsert, ScrapeRunRepository
from app.domain.dto import ListingPage
from app.domain.enums import (
    Category,
    ChallengeKind,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
)
from app.domain.errors import (
    ChallengeFailed,
    ChallengeNotPending,
    RunNotFound,
    ScrapeAlreadyRunning,
    SiteCooldown,
)
from app.mock_shop.main import create_app
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.errors import FetchFailed, HttpStatusError
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import (
    BLOCK_COOLDOWN,
    NEEDS_HUMAN_STALE_AFTER,
    RUNNING_STALE_AFTER,
    PipelineResult,
    ScrapePipeline,
)
from app.scrapers.registry import SCRAPERS, SiteNotAvailable
from tests.factories import make_offer, make_product
from tests.unit.test_mockshop_scraper import fixture as mockshop_fixture

BASE = "http://localhost:8100"
LAPTOP = f"{BASE}/c/laptop"
NOW = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeTime:
    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def mock_fetcher(captcha_after: int = 10_000) -> Fetcher:
    """Fetcher thật (robots, độ trễ 0) nói chuyện với một mock-shop mới qua ASGI."""
    fake = FakeTime()
    settings = Settings(
        scraper_offline_only=True,
        scraper_min_delay_seconds=0,
        mock_shop_url=BASE,
        mock_shop_delay_seconds=0,
    )
    return Fetcher(
        settings,
        mock_transport=httpx.ASGITransport(app=create_app(captcha_after=captcha_after)),
        clock=fake.clock,
        sleep=fake.sleep,
    )


def pipeline(
    factory: Callable[[], Session], fetcher: Any, clock: Clock, **kwargs: Any
) -> ScrapePipeline:
    kwargs.setdefault("default_max_pages", 5)
    return ScrapePipeline(factory, fetcher, now=clock, **kwargs)


def count(session: Session, model: type[Any]) -> int:
    session.expire_all()
    return int(session.exec(select(func.count()).select_from(model)).one())


def run_row(session: Session, result: PipelineResult) -> ScrapeRun:
    session.expire_all()
    run = session.get(ScrapeRun, result.run_id)
    assert run is not None
    return run


def active_offers(session: Session) -> list[Offer]:
    session.expire_all()
    return list(session.exec(select(Offer).where(col(Offer.is_active).is_(True))))


class ScriptedFetcher:
    """PageFetcher giả: trả trang/ném lỗi định sẵn theo URL; ghi lại request và form đã gửi."""

    def __init__(self, pages: dict[str, FetchResponse | Exception]) -> None:
        self.pages = pages
        self.requested: list[str] = []
        self.posted: list[tuple[str, dict[str, str]]] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        item = self.pages.get(url) or HttpStatusError("HTTP 404", url=url, status=404)
        if isinstance(item, Exception):
            raise item
        return item

    async def post_form(self, url: str, data: Any) -> FetchResponse:
        self.posted.append((url, dict(data)))
        return FetchResponse(url=url, final_url=url, status=200, text="ok")


def page(text_: str, url: str = LAPTOP, status: int = 200) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text_)


def card(
    slug: str,
    title: str,
    price: str = "1.000.000₫",
    *,
    specs: dict[str, str] | None = None,
    rating: str | None = None,
) -> str:
    mini = "".join(f"<li>{k}: {v}</li>" for k, v in (specs or {}).items())
    stars = f'<span class="rating" data-rating="{rating}" data-count="7">x</span>' if rating else ""
    return (
        f'<li class="product-card" data-slug="{slug}" data-sku="SKU-{slug}">'
        f'<a class="product-link" href="/p/{slug}"><h2 class="product-name">{title}</h2></a>'
        f'<span class="price">{price}</span>{stars}<ul class="mini-specs">{mini}</ul></li>'
    )


def listing(cards: list[str], *, ld_prices: dict[str, int] | None = None) -> str:
    ld = ""
    if ld_prices:
        elements = ",".join(
            '{"@type":"ListItem","item":{"@type":"Product","name":"x",'
            f'"url":"{BASE}/p/{slug}","offers":{{"@type":"Offer","price":{value}}}}}}}'
            for slug, value in ld_prices.items()
        )
        ld = (
            '<script type="application/ld+json">'
            f'{{"@type":"ItemList","itemListElement":[{elements}]}}</script>'
        )
    return f"<html><head>{ld}</head><body><ul>{''.join(cards)}</ul></body></html>"


def detail_html(specs: dict[str, str], sku: str = "MPN-1") -> str:
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in specs.items())
    return (
        '<script type="application/ld+json">'
        f'{{"@type":"Product","sku":"{sku}","brand":{{"@type":"Brand","name":"ASUS"}}}}</script>'
        f'<table class="specs">{rows}</table>'
    )


class RealScraper(BaseScraper):
    """Trang "thật" (không phải mock) để thử BLOCKED và thời gian nghỉ."""

    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.gearvn,
        base_url="https://shop.example",
        min_delay_s=5.0,
        categories={
            Category.laptop: "https://shop.example/c/laptop",
            Category.mouse: "https://shop.example/c/mouse",
        },
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


# --- Lượt đầy đủ ------------------------------------------------------------------------------


async def test_full_run_saves_every_priced_item_and_reports_exact_counters(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    result = await pipeline(factory, mock_fetcher(), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.SUCCEEDED
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (3, 26, 1)
    assert (result.offers_upserted, result.price_changes) == (25, 0)
    assert result.changed_offer_ids == () and result.challenge is None
    run = run_row(db_session, result)
    assert run.status is ScrapeStatus.SUCCEEDED
    assert (run.pages_fetched, run.items_parsed, run.items_failed) == (3, 26, 1)
    assert (run.offers_upserted, run.price_changes) == (25, 0)
    assert run.started_at == NOW and run.finished_at == NOW
    assert run.challenge is None and run.error_message is None
    assert count(db_session, Offer) == 25
    assert count(db_session, Product) == 25
    assert count(db_session, PriceHistory) == 25


async def test_saved_offers_and_products_carry_the_scraped_data(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    await pipeline(factory, mock_fetcher(), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    db_session.expire_all()
    offer = db_session.exec(
        select(Offer).where(col(Offer.url) == f"{BASE}/p/asus-mock-strix-15-x01-mk-la001")
    ).one()
    product = db_session.get(Product, offer.product_id)
    assert product is not None
    assert (offer.site, offer.price, offer.title) == (
        SiteKey.mockshop,
        15_750_000,
        "Laptop ASUS Mock Strix 15 X01",
    )
    assert offer.site_sku == "MK-LA001" and offer.is_active is True
    assert offer.raw_specs["CPU"].startswith("Intel")
    assert (product.category, product.brand, product.model_code) == (Category.laptop, "ASUS", None)
    assert product.canonical_name == "Laptop ASUS Mock Strix 15 X01"
    # Thông số trích bằng luật từ thẻ danh sách (thẻ mock-shop không có GPU nên còn thiếu 1/4).
    assert product.specs == {
        "cpu_model": "i5-13500H",
        "cpu_vendor": "intel",
        "ram_gb": 8,
        "storage_gb": 512,
        "storage_type": "ssd",
    }
    assert product.specs_confidence == pytest.approx(0.37)


async def test_rerun_is_idempotent_and_adds_no_duplicate_rows(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    first = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    second = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert second.run_id != first.run_id
    assert second.status is ScrapeStatus.SUCCEEDED
    assert (second.items_parsed, second.offers_upserted, second.price_changes) == (26, 25, 0)
    assert count(db_session, Offer) == 25
    assert count(db_session, Product) == 25
    assert count(db_session, PriceHistory) == 25  # giá không đổi → không thêm dòng lịch sử
    assert count(db_session, ScrapeRun) == 2


async def test_price_change_adds_history_and_returns_the_offer_id(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    offer = db_session.exec(
        select(Offer).where(col(Offer.url) == f"{BASE}/p/asus-mock-strix-15-x01-mk-la001")
    ).one()
    assert offer.id is not None
    history = db_session.exec(select(PriceHistory).where(PriceHistory.offer_id == offer.id)).one()
    history.price += 1_000_000  # lần trước shop bán đắt hơn → lần này giá giảm
    db_session.flush()

    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert result.price_changes == 1
    assert result.changed_offer_ids == (offer.id,)
    rows = db_session.exec(
        select(PriceHistory).where(PriceHistory.offer_id == offer.id).order_by(col(PriceHistory.id))
    ).all()
    assert [row.price for row in rows] == [16_750_000, 15_750_000]
    assert run_row(db_session, result).price_changes == 1


async def test_a_full_run_deactivates_offers_that_are_no_longer_listed(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    product = make_product(category=Category.laptop)
    db_session.add(product)
    db_session.flush()
    assert product.id is not None
    gone = make_offer(product.id, site=SiteKey.mockshop, scraped_at=NOW - timedelta(days=1))
    other_site = make_offer(product.id, site=SiteKey.gearvn, scraped_at=NOW - timedelta(days=1))
    db_session.add_all([gone, other_site])
    db_session.flush()
    clock.now = NOW + timedelta(hours=1)

    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    db_session.refresh(gone)
    db_session.refresh(other_site)
    assert gone.is_active is False
    assert other_site.is_active is True  # trang khác không bị đụng tới
    assert len(active_offers(db_session)) == 26  # 25 vừa thấy + offer trang khác


async def test_page_limit_makes_the_run_partial_and_keeps_unseen_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    clock.now = NOW + timedelta(hours=1)

    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, max_pages=1)

    assert result.status is ScrapeStatus.PARTIAL
    assert (result.pages_fetched, result.items_parsed) == (1, 12)
    assert result.error_message is not None and "giới hạn số trang" in result.error_message
    assert len(active_offers(db_session)) == 25  # lượt bị cắt không tắt offer nào


async def test_default_page_limit_comes_from_the_pipeline_setting(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock, default_max_pages=2)
    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert (result.status, result.pages_fetched) == (ScrapeStatus.PARTIAL, 2)


async def test_invalid_page_limit_is_rejected_before_any_run_is_created(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    with pytest.raises(ValueError, match="max_pages"):
        await pipeline(factory, mock_fetcher(), clock).run(
            SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, max_pages=0
        )
    assert count(db_session, ScrapeRun) == 0


async def test_unregistered_site_raises_and_creates_no_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    with pytest.raises(SiteNotAvailable):
        await pipeline(factory, mock_fetcher(), clock).run(
            SiteKey.viettelstore, Category.laptop, ScrapeTrigger.test
        )
    assert count(db_session, ScrapeRun) == 0


async def test_empty_category_on_a_first_run_succeeds_with_zero_items(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({LAPTOP: page(mockshop_fixture("listing_empty.html"))})
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert (result.status, result.items_parsed, result.offers_upserted) == (
        ScrapeStatus.SUCCEEDED,
        0,
        0,
    )


async def test_brand_is_detected_with_unknown_as_fallback(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    html = listing([card("a", "Laptop Acer Mock A"), card("b", "Máy lạ không rõ hãng")])
    await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    brands = {p.brand for p in db_session.exec(select(Product)).all()}
    assert brands == {"Acer", "Unknown"}


# --- Lỗi từng mục -----------------------------------------------------------------------------


async def test_a_database_error_on_one_item_only_counts_as_failed_and_leaves_no_orphans(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = listing(
        [
            card("a", "Laptop Acer Mock A"),
            card("b", "Laptop Acer Mock B"),
            card("c", "Laptop Acer Mock C"),
        ]
    )
    original = OfferRepository.upsert

    def flaky(self: OfferRepository, data: OfferUpsert, *, now: datetime | None = None) -> Any:
        if data.title.endswith("B"):
            self._session.execute(text("SELECT 1/0"))  # lỗi PostgreSQL thật trong savepoint
        return original(self, data, now=now)

    monkeypatch.setattr(OfferRepository, "upsert", flaky)

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (3, 1, 2)
    assert result.status is ScrapeStatus.PARTIAL  # 1/3 > 20%
    assert {o.title for o in active_offers(db_session)} == {
        "Laptop Acer Mock A",
        "Laptop Acer Mock C",
    }
    assert count(db_session, Product) == 2  # sản phẩm của mục lỗi được rollback cùng savepoint


@pytest.mark.parametrize(
    ("price_html", "ld_price"),
    [
        ("0₫", None),  # giá 0 (HTML) → parse_price None
        ("5.000₫", None),  # dưới 10.000
        ("600.000.000₫", None),  # trên 500.000.000
        ("Liên hệ", None),
        ("***.000đ", None),  # giá bị che
        ("1.000.000₫", 0),  # JSON-LD ghi giá 0 (repo chấp nhận 0, pipeline phải chặn)
        ("1.000.000₫", 700_000_000),
    ],
)
async def test_unreadable_or_out_of_range_prices_are_never_stored(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    price_html: str,
    ld_price: int | None,
) -> None:
    html = listing(
        [card("ok", "Laptop Acer Mock OK"), card("bad", "Laptop Acer Mock Bad", price_html)],
        ld_prices={"bad": ld_price} if ld_price is not None else None,
    )
    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (2, 1, 1)
    assert [o.title for o in active_offers(db_session)] == ["Laptop Acer Mock OK"]
    assert all(o.price >= 10_000 for o in active_offers(db_session))


async def test_unreadable_cards_count_as_failed_and_too_many_failures_make_it_partial(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    html = listing(
        [
            card("a", "Laptop Acer Mock A"),
            card("b", "Laptop Acer Mock B", "Liên hệ"),
            card("c", "Laptop Acer Mock C", "Liên hệ"),
            card("d", "Laptop Acer Mock D"),
            card("e", "Laptop Acer Mock E", "Liên hệ"),
        ]
    ).replace('<a class="product-link" href="/p/e">', '<a class="broken" href="/p/e">')

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.items_parsed, result.items_failed) == (5, 3)  # 2 hết giá + 1 thẻ hỏng
    assert result.status is ScrapeStatus.PARTIAL
    assert result.error_message is not None and "chất lượng" in result.error_message
    assert len(active_offers(db_session)) == 2


async def test_a_sharp_drop_in_item_count_is_flagged_in_the_run_message(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    runs = ScrapeRunRepository(db_session)
    previous = runs.create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=NOW - timedelta(days=1)
    )
    runs.update_counters(previous, items_parsed=100)
    runs.set_status(previous, ScrapeStatus.SUCCEEDED, now=NOW - timedelta(days=1))
    html = listing([card("a", "Laptop Acer Mock A"), card("b", "Laptop Acer Mock B")])

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.SUCCEEDED
    assert result.error_message is not None and "giảm từ 100 xuống 2" in result.error_message


# --- Trang chi tiết ---------------------------------------------------------------------------


async def test_items_without_specs_get_them_from_the_detail_page(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    detail_url = f"{BASE}/p/a"
    fetcher = ScriptedFetcher(
        {
            LAPTOP: page(listing([card("a", "Laptop Acer Mock A")])),
            detail_url: page(detail_html({"CPU": "Intel i5", "RAM": "16GB"}), detail_url),
        }
    )

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.offers_upserted == 1
    assert fetcher.requested == [LAPTOP, detail_url]
    assert active_offers(db_session)[0].raw_specs == {"CPU": "Intel i5", "RAM": "16GB"}


async def test_items_that_already_have_specs_do_not_trigger_a_detail_request(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    html = listing([card("a", "Laptop Acer Mock A", specs={"CPU": "i5"})])
    fetcher = ScriptedFetcher({LAPTOP: page(html)})
    await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert fetcher.requested == [LAPTOP]


async def test_detail_requests_are_capped_per_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    slugs = ["a", "b", "c", "d"]
    pages: dict[str, FetchResponse | Exception] = {
        LAPTOP: page(listing([card(s, f"Laptop Acer Mock {s}") for s in slugs]))
    }
    pages.update({f"{BASE}/p/{s}": page(detail_html({"CPU": s})) for s in slugs})
    fetcher = ScriptedFetcher(pages)

    result = await pipeline(factory, fetcher, clock, max_detail_requests=2).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.offers_upserted == 4
    assert len(fetcher.requested) == 3  # 1 trang danh sách + 2 trang chi tiết
    with_specs = [o for o in active_offers(db_session) if o.raw_specs]
    assert len(with_specs) == 2


async def test_a_failed_detail_request_does_not_fail_the_item(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            LAPTOP: page(listing([card("a", "Laptop Acer Mock A")])),
            f"{BASE}/p/a": HttpStatusError("HTTP 404", url=f"{BASE}/p/a", status=404),
        }
    )
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert (result.status, result.offers_upserted, result.items_failed) == (
        ScrapeStatus.SUCCEEDED,
        1,
        0,
    )


async def test_a_rerun_without_detail_keeps_specs_rating_and_sku_from_before(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    detail_url = f"{BASE}/p/a"
    first = ScriptedFetcher(
        {
            LAPTOP: page(listing([card("a", "Laptop Acer Mock A", rating="4.5")])),
            detail_url: page(detail_html({"CPU": "Intel i5"})),
        }
    )
    await pipeline(factory, first, clock).run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    bare = card("a", "Laptop Acer Mock A", "900.000₫").replace('data-sku="SKU-a"', "")
    second = ScriptedFetcher({LAPTOP: page(listing([bare]))})
    clock.now = NOW + timedelta(hours=1)

    await pipeline(factory, second, clock, max_detail_requests=0).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    offer = active_offers(db_session)[0]
    assert offer.price == 900_000
    assert offer.raw_specs == {"CPU": "Intel i5"}
    assert (offer.rating, offer.rating_count, offer.site_sku) == (4.5, 7, "SKU-a")


async def test_a_challenge_on_a_detail_page_pauses_the_run_before_saving_the_page(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            LAPTOP: page(listing([card("a", "Laptop Acer Mock A")])),
            f"{BASE}/p/a": page(mockshop_fixture("captcha.html")),
        }
    )
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert result.status is ScrapeStatus.NEEDS_HUMAN
    assert (result.pages_fetched, result.offers_upserted) == (0, 0)
    assert active_offers(db_session) == []


# --- Captcha: NEEDS_HUMAN → resume ------------------------------------------------------------


async def test_captcha_pauses_the_run_and_the_right_answer_finishes_it(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)

    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert paused.status is ScrapeStatus.NEEDS_HUMAN
    assert (paused.pages_fetched, paused.items_parsed, paused.offers_upserted) == (1, 12, 11)
    challenge = paused.challenge
    assert challenge is not None and challenge.kind is ChallengeKind.captcha
    assert challenge.token and challenge.prompt
    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.NEEDS_HUMAN and run.finished_at is None
    assert run.challenge is not None
    assert run.challenge["kind"] == "captcha" and run.challenge["token"] == challenge.token
    assert len(active_offers(db_session)) == 11  # trang 1 đã lưu trước khi dừng

    match = re.search(r"[A-Z2-9]{5}$", challenge.prompt)
    assert match
    done = await pipe.resume(paused.run_id, match.group(0).lower())

    assert done.run_id == paused.run_id
    assert done.status is ScrapeStatus.SUCCEEDED
    assert (done.pages_fetched, done.items_parsed, done.items_failed) == (3, 26, 1)
    assert done.offers_upserted == 25
    run = run_row(db_session, done)
    assert run.status is ScrapeStatus.SUCCEEDED and run.challenge is None
    assert run.finished_at == NOW
    assert (run.pages_fetched, run.items_parsed, run.offers_upserted) == (3, 26, 25)
    assert len(active_offers(db_session)) == 25
    assert count(db_session, ScrapeRun) == 1


async def test_a_wrong_answer_keeps_the_run_waiting_and_can_be_retried(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.challenge is not None and paused.challenge.prompt is not None

    for wrong in ("ZZZZZ", ""):
        with pytest.raises(ChallengeFailed):
            await pipe.resume(paused.run_id, wrong)

    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.NEEDS_HUMAN
    assert run.challenge is not None and run.challenge["token"] == paused.challenge.token
    right = re.search(r"[A-Z2-9]{5}$", paused.challenge.prompt)
    assert right
    assert (await pipe.resume(paused.run_id, right.group(0))).status is ScrapeStatus.SUCCEEDED


async def test_resume_rejects_unknown_and_not_waiting_runs(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    with pytest.raises(RunNotFound):
        await pipe.resume(999_999, "ABCDE")

    done = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    with pytest.raises(ChallengeNotPending) as error:
        await pipe.resume(done.run_id, "ABCDE")
    assert error.value.details["status"] == "SUCCEEDED"


async def test_after_the_captcha_is_solved_later_runs_with_the_same_fetcher_need_no_captcha(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.challenge is not None and paused.challenge.prompt is not None
    code = re.search(r"[A-Z2-9]{5}$", paused.challenge.prompt)
    assert code

    # Giải xong mock-shop cho đi tiếp mà không đếm lại; chạy lại cũng không cần captcha nữa.
    done = await pipe.resume(paused.run_id, code.group(0))
    again = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert done.status is ScrapeStatus.SUCCEEDED
    assert again.status is ScrapeStatus.SUCCEEDED  # cookie còn hiệu lực trong Fetcher này


# --- BLOCKED, thời gian nghỉ, chặn mềm ---------------------------------------------------------


@pytest.fixture
def real_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(SCRAPERS, SiteKey.gearvn, RealScraper)


REAL_LAPTOP = "https://shop.example/c/laptop"


@pytest.mark.parametrize("status", [403, 429])
async def test_a_real_site_that_blocks_is_marked_blocked_and_rests_for_24_hours(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    real_site: None,
    status: int,
) -> None:
    fetcher = ScriptedFetcher({REAL_LAPTOP: page("denied", REAL_LAPTOP, status)})
    pipe = pipeline(factory, fetcher, clock)

    blocked = await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)

    assert blocked.status is ScrapeStatus.BLOCKED
    assert blocked.challenge is not None
    assert blocked.challenge.kind.value == f"http_{status}"
    run = run_row(db_session, blocked)
    assert run.status is ScrapeStatus.BLOCKED and run.finished_at == NOW
    assert run.challenge is not None and run.challenge["kind"] == f"http_{status}"

    clock.now = NOW + timedelta(hours=1)
    requests_before = len(fetcher.requested)
    with pytest.raises(SiteCooldown) as error:
        await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)
    assert error.value.details["retry_after"] == NOW + BLOCK_COOLDOWN
    assert len(fetcher.requested) == requests_before  # không gửi request nào trong lúc nghỉ

    clock.now = NOW + BLOCK_COOLDOWN
    assert (await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)).status is (
        ScrapeStatus.BLOCKED
    )


async def test_cooldown_applies_to_the_whole_site_not_just_one_category(
    db_session: Session, factory: Callable[[], Session], clock: Clock, real_site: None
) -> None:
    fetcher = ScriptedFetcher({REAL_LAPTOP: page("denied", REAL_LAPTOP, 403)})
    pipe = pipeline(factory, fetcher, clock)
    await pipe.run(SiteKey.gearvn, Category.laptop, ScrapeTrigger.test)
    with pytest.raises(SiteCooldown):
        await pipe.run(SiteKey.gearvn, Category.mouse, ScrapeTrigger.test)


async def test_a_captcha_on_a_real_site_is_blocked_never_waiting_for_a_human(
    db_session: Session, factory: Callable[[], Session], clock: Clock, real_site: None
) -> None:
    fetcher = ScriptedFetcher(
        {REAL_LAPTOP: page("<div>Please solve this captcha</div>", REAL_LAPTOP)}
    )
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.gearvn, Category.laptop, ScrapeTrigger.test
    )
    assert result.status is ScrapeStatus.BLOCKED
    assert fetcher.posted == []


async def test_the_mock_shop_is_blocked_by_http_errors_but_has_no_cooldown(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({LAPTOP: page("denied", LAPTOP, 403)})
    pipe = pipeline(factory, fetcher, clock)

    first = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    second = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)

    assert (first.status, second.status) == (ScrapeStatus.BLOCKED, ScrapeStatus.BLOCKED)


async def test_an_empty_first_page_after_a_good_run_is_a_soft_block(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    runs = ScrapeRunRepository(db_session)
    previous = runs.create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=NOW - timedelta(days=1)
    )
    runs.update_counters(previous, items_parsed=26)
    runs.set_status(previous, ScrapeStatus.SUCCEEDED, now=NOW - timedelta(days=1))
    fetcher = ScriptedFetcher({LAPTOP: page(mockshop_fixture("listing_empty.html"))})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.BLOCKED
    assert result.challenge is not None and result.challenge.kind is ChallengeKind.soft_block


# --- Lượt đang chạy ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status", [ScrapeStatus.PENDING, ScrapeStatus.RUNNING, ScrapeStatus.NEEDS_HUMAN]
)
async def test_a_fresh_active_run_blocks_a_new_run_of_the_same_site_and_category(
    db_session: Session, factory: Callable[[], Session], clock: Clock, status: ScrapeStatus
) -> None:
    existing = ScrapeRunRepository(db_session).create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, status=status, now=NOW
    )
    clock.now = NOW + timedelta(minutes=5)
    fetcher = ScriptedFetcher({})

    with pytest.raises(ScrapeAlreadyRunning) as error:
        await pipeline(factory, fetcher, clock).run(
            SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
        )

    assert error.value.details == {"run_id": existing.id, "status": status.value}
    assert fetcher.requested == []
    assert count(db_session, ScrapeRun) == 1


async def test_other_categories_and_sites_are_not_blocked_by_an_active_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    ScrapeRunRepository(db_session).create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=NOW
    )
    html = listing([card("a", "Chuột Logitech Mock A")])
    fetcher = ScriptedFetcher({f"{BASE}/c/mouse": page(html, f"{BASE}/c/mouse")})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.mouse, ScrapeTrigger.test
    )
    assert result.status is ScrapeStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("status", "age"),
    [
        (ScrapeStatus.RUNNING, RUNNING_STALE_AFTER),
        (ScrapeStatus.NEEDS_HUMAN, NEEDS_HUMAN_STALE_AFTER),
        (ScrapeStatus.PENDING, RUNNING_STALE_AFTER),
    ],
)
async def test_a_stale_active_run_no_longer_blocks(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    status: ScrapeStatus,
    age: timedelta,
) -> None:
    ScrapeRunRepository(db_session).create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, status=status, now=NOW
    )
    clock.now = NOW + age  # đúng ngưỡng: coi là đã chết
    fetcher = ScriptedFetcher({LAPTOP: page(mockshop_fixture("listing_empty.html"))})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert result.status is ScrapeStatus.SUCCEEDED


async def test_finished_runs_never_block(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    runs = ScrapeRunRepository(db_session)
    for status in (ScrapeStatus.FAILED, ScrapeStatus.PARTIAL, ScrapeStatus.SUCCEEDED):
        run = runs.create(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=NOW)
        runs.set_status(run, status, now=NOW)
    fetcher = ScriptedFetcher({LAPTOP: page(mockshop_fixture("listing_empty.html"))})
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert result.status is not ScrapeStatus.BLOCKED


# --- Lỗi tải, lỗi bất ngờ ---------------------------------------------------------------------


async def test_a_fetch_error_on_the_second_page_leaves_a_partial_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    page1 = listing([card("a", "Laptop Acer Mock A")]).replace(
        "</ul>", '</ul><a rel="next" href="/c/laptop?page=2">Trang sau</a>'
    )
    fetcher = ScriptedFetcher(
        {
            LAPTOP: page(page1),
            f"{LAPTOP}?page=2": HttpStatusError("HTTP 404", url=f"{LAPTOP}?page=2", status=404),
        }
    )

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.PARTIAL
    assert (result.pages_fetched, result.offers_upserted) == (1, 1)
    assert result.error_message is not None and "HttpStatusError" in result.error_message
    assert len(active_offers(db_session)) == 1


async def test_a_fetch_error_on_the_first_page_fails_the_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({LAPTOP: HttpStatusError("HTTP 404", url=LAPTOP, status=404)})
    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )
    assert result.status is ScrapeStatus.FAILED
    run = run_row(db_session, result)
    assert run.status is ScrapeStatus.FAILED and run.finished_at == NOW
    assert run.error_message is not None and "404" in run.error_message


async def test_an_unexpected_exception_fails_the_run_without_leaking_its_message(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fetcher = ScriptedFetcher({LAPTOP: RuntimeError("mat-khau-bi-mat")})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.FAILED
    assert result.error_message == "Lỗi không lường trước: RuntimeError"
    run = run_row(db_session, result)
    assert run.status is ScrapeStatus.FAILED  # không bị bỏ lại ở RUNNING
    assert "mat-khau-bi-mat" not in (run.error_message or "")


async def test_a_run_is_serialised_per_site_and_category_even_with_the_same_fetcher(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(), clock)
    for _ in range(2):  # lần lượt, cùng pipeline: không bị coi là "đang chạy"
        result = await pipe.run(SiteKey.mockshop, Category.mouse, ScrapeTrigger.test)
        assert result.status is ScrapeStatus.SUCCEEDED


# --- Bổ sung sau review M2 ---------------------------------------------------------------------


def _stale_offer(db_session: Session, **overrides: Any) -> Offer:
    product = make_product(category=Category.laptop)
    db_session.add(product)
    db_session.flush()
    assert product.id is not None
    offer = make_offer(
        product.id, site=SiteKey.mockshop, scraped_at=NOW - timedelta(days=1), **overrides
    )
    db_session.add(offer)
    db_session.flush()
    return offer


async def test_unpriced_only_failures_still_allow_deactivating_the_gone_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    stale = _stale_offer(db_session)
    cards = [card(s, f"Laptop Acer Mock {s}") for s in "abcdefghi"]
    cards.append(card("z", "Laptop Acer Mock Z", "Liên hệ"))  # 1/10 = 10% ≤ 20%

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(listing(cards))}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.status, result.items_failed) == (ScrapeStatus.SUCCEEDED, 1)
    db_session.refresh(stale)
    assert stale.is_active is False


async def test_a_save_error_blocks_deactivation_because_the_failed_item_may_still_be_listed(
    db_session: Session,
    factory: Callable[[], Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _stale_offer(db_session)
    cards = [card(s, f"Laptop Acer Mock {s}") for s in "abcdefghij"]
    original = OfferRepository.upsert

    def flaky(self: OfferRepository, data: OfferUpsert, *, now: datetime | None = None) -> Any:
        if data.title.endswith("j"):
            self._session.execute(text("SELECT 1/0"))
        return original(self, data, now=now)

    monkeypatch.setattr(OfferRepository, "upsert", flaky)

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(listing(cards))}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.status, result.items_failed) == (ScrapeStatus.SUCCEEDED, 1)  # 10% ≤ 20%
    db_session.refresh(stale)
    assert stale.is_active is True


async def test_an_unreadable_card_blocks_deactivation(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    stale = _stale_offer(db_session)
    cards = [card(s, f"Laptop Acer Mock {s}") for s in "abcdefghij"]
    html = listing(cards).replace(
        '<a class="product-link" href="/p/j">', '<a class="broken" href="/p/j">'
    )

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.status, result.items_failed) == (ScrapeStatus.SUCCEEDED, 1)
    db_session.refresh(stale)
    assert stale.is_active is True


async def test_an_empty_first_page_never_deactivates_existing_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    existing = _stale_offer(db_session)
    fetcher = ScriptedFetcher({LAPTOP: page(mockshop_fixture("listing_empty.html"))})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert (result.status, result.items_parsed) == (ScrapeStatus.SUCCEEDED, 0)
    db_session.refresh(existing)
    assert existing.is_active is True


async def test_a_sharp_drop_in_item_count_never_deactivates_existing_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    existing = _stale_offer(db_session)
    runs = ScrapeRunRepository(db_session)
    previous = runs.create(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, now=NOW - timedelta(days=1)
    )
    runs.update_counters(previous, items_parsed=100)
    runs.set_status(previous, ScrapeStatus.SUCCEEDED, now=NOW - timedelta(days=1))
    html = listing([card("a", "Laptop Acer Mock A"), card("b", "Laptop Acer Mock B")])

    result = await pipeline(factory, ScriptedFetcher({LAPTOP: page(html)}), clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.SUCCEEDED
    db_session.refresh(existing)
    assert existing.is_active is True


async def test_a_resumed_run_with_earlier_failures_does_not_deactivate(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.items_failed == 1  # thẻ "Liên hệ" ở trang 1
    stale = _stale_offer(db_session)
    assert paused.challenge is not None and paused.challenge.prompt is not None
    code = re.search(r"[A-Z2-9]{5}$", paused.challenge.prompt)
    assert code

    done = await pipe.resume(paused.run_id, code.group(0))

    assert done.status is ScrapeStatus.SUCCEEDED
    db_session.refresh(stale)
    assert stale.is_active is True  # không biết lỗi cũ là loại nào → thận trọng


# --- resume: chiếm lượt, hết hạn, đáp án ------------------------------------------------------


class RecordingFetcher(ScriptedFetcher):
    """ScriptedFetcher có thể chạy mã tùy ý khi nhận form (để quan sát trạng thái lượt)."""

    def __init__(self, pages: dict[str, FetchResponse | Exception]) -> None:
        super().__init__(pages)
        self.on_post: Callable[[], FetchResponse | Exception] | None = None

    async def post_form(self, url: str, data: Any) -> FetchResponse:
        self.posted.append((url, dict(data)))
        if self.on_post is None:
            return FetchResponse(url=url, final_url=url, status=200, text="ok")
        outcome = self.on_post()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _paused(
    factory: Callable[[], Session], clock: Clock, fetcher: RecordingFetcher
) -> tuple[ScrapePipeline, PipelineResult]:
    pipe = pipeline(factory, fetcher, clock)
    result = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert result.status is ScrapeStatus.NEEDS_HUMAN
    return pipe, result


def _captcha_fetcher() -> RecordingFetcher:
    return RecordingFetcher({LAPTOP: page(mockshop_fixture("captcha.html"))})


async def test_resume_claims_the_run_before_sending_the_answer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _captcha_fetcher()
    pipe, paused = await _paused(factory, clock, fetcher)
    seen: list[ScrapeStatus] = []

    def observe() -> FetchResponse:
        seen.append(run_row(db_session, paused).status)
        return FetchResponse(url="u", final_url="u", status=400, text="sai")

    fetcher.on_post = observe
    with pytest.raises(ChallengeFailed):
        await pipe.resume(paused.run_id, "ZZZZZ")

    assert seen == [ScrapeStatus.RUNNING]  # lúc đó resume thứ hai sẽ bị từ chối
    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.NEEDS_HUMAN and run.finished_at is None
    assert run.challenge is not None and run.challenge["kind"] == "captcha"


async def test_a_run_already_claimed_by_another_resume_is_rejected(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _captcha_fetcher()
    pipe, paused = await _paused(factory, clock, fetcher)
    ScrapeRunRepository(db_session).set_status(run_row(db_session, paused), ScrapeStatus.RUNNING)

    with pytest.raises(ChallengeNotPending) as error:
        await pipe.resume(paused.run_id, "AAAAA")

    assert error.value.details["status"] == "RUNNING"
    assert fetcher.posted == []  # đáp án không được gửi khi không chiếm được lượt


async def test_resume_of_a_stale_waiting_run_is_rejected_without_sending_the_answer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _captcha_fetcher()
    pipe, paused = await _paused(factory, clock, fetcher)
    clock.now = NOW + NEEDS_HUMAN_STALE_AFTER  # đúng ngưỡng: lượt mới được phép chạy

    with pytest.raises(ChallengeNotPending):
        await pipe.resume(paused.run_id, "AAAAA")

    assert fetcher.posted == []
    assert run_row(db_session, paused).status is ScrapeStatus.NEEDS_HUMAN


async def test_resume_with_a_page_limit_below_the_resume_page_is_rejected_untouched(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    pipe = pipeline(factory, mock_fetcher(captcha_after=1), clock)
    paused = await pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test)
    assert paused.pages_fetched == 1

    with pytest.raises(ValueError, match="max_pages"):
        await pipe.resume(paused.run_id, "ABCDE", max_pages=1)  # cần ít nhất trang 2

    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.NEEDS_HUMAN and run.challenge is not None


async def test_a_network_error_while_sending_the_answer_keeps_the_run_waiting(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _captcha_fetcher()
    pipe, paused = await _paused(factory, clock, fetcher)
    fetcher.on_post = lambda: FetchFailed("down", url="u")

    with pytest.raises(FetchFailed):
        await pipe.resume(paused.run_id, "AAAAA")

    run = run_row(db_session, paused)
    assert run.status is ScrapeStatus.NEEDS_HUMAN and run.challenge is not None


async def test_a_server_error_from_the_challenge_endpoint_is_not_a_wrong_answer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = _captcha_fetcher()
    pipe, paused = await _paused(factory, clock, fetcher)
    fetcher.on_post = lambda: FetchResponse(url="u", final_url="u", status=500, text="oops")

    with pytest.raises(FetchFailed):
        await pipe.resume(paused.run_id, "AAAAA")

    assert run_row(db_session, paused).status is ScrapeStatus.NEEDS_HUMAN


async def test_cancelling_a_run_closes_it_instead_of_leaving_it_running(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    started = asyncio.Event()

    class Hanging(ScriptedFetcher):
        async def get(self, url: str) -> FetchResponse:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    pipe = pipeline(factory, Hanging({}), clock)
    task = asyncio.create_task(pipe.run(SiteKey.mockshop, Category.laptop, ScrapeTrigger.test))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    db_session.expire_all()
    run = db_session.exec(select(ScrapeRun)).one()
    assert run.status is ScrapeStatus.FAILED
    assert run.error_message == "Lượt thu thập bị huỷ."
    assert run.finished_at is not None
