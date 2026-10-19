"""QA M3: hợp đồng ScrapePipeline + GearVNScraper trên HTML dựng sẵn/fixture (PostgreSQL thật).

Không gọi mạng: `ScriptedFetcher` trả trang định sẵn và ghi lại mọi URL đã yêu cầu. Các ca
Các ca cuối file là lỗi QA M3 tìm thấy; test viết đỏ trước, nay đã sửa mã và xanh.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func
from sqlmodel import Session, select

from app.db.models import Offer, PriceHistory, Product
from app.domain.dto import Challenge
from app.domain.enums import (
    Category,
    ChallengeKind,
    PriceType,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
)
from app.domain.errors import SiteCooldown
from app.scrapers.http.types import FetchResponse
from app.scrapers.pipeline import PipelineResult, ScrapePipeline
from tests.integration.test_pipeline import Clock, ScriptedFetcher
from tests.unit.test_gearvn_scraper import card
from tests.unit.test_gearvn_scraper_m3 import listing_html, priced

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"
BASE = "https://gearvn.com"
MOUSES = f"{BASE}/collections/chuot-may-tinh"
MOUSES_P2 = f"{MOUSES}?page=2"
LAPTOPS = f"{BASE}/collections/laptop"
DETAIL_SLUG = "laptop-acer-aspire-lite-15-al15-53p-56qh"
DETAIL_URL = f"{BASE}/products/{DETAIL_SLUG}"
EMPTY_PAGE = "<html><head></head><body></body></html>"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


def served(url: str, text: str, status: int = 200, **headers: str) -> FetchResponse:
    return FetchResponse(url=url, final_url=url, status=status, text=text, headers=headers)


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def unpriced(slug: str) -> str:
    body = '<span data-slot="product-discontinued-price">Liên hệ tư vấn</span>'
    return card(href=f"/products/{slug}", title=f"Chuột {slug}", body=body)


def sale(slug: str, old: str, new: str) -> str:
    body = f"<span>{old}</span><span>-20%</span><span>{new}</span>"
    return card(href=f"/products/{slug}", title=f"Chuột {slug}", body=body)


def detail_page(properties: list[dict[str, Any]] | None = None, raw: str | None = None) -> str:
    payload = raw or json.dumps(
        {"@type": "Product", "brand": {"name": "Acer"}, "additionalProperty": properties or []}
    )
    return f'<html><head><script type="application/ld+json">{payload}</script></head></html>'


def pipe(
    factory: Callable[[], Session], fetcher: ScriptedFetcher, clock: Clock, **kwargs: Any
) -> ScrapePipeline:
    kwargs.setdefault("default_max_pages", 5)
    kwargs.setdefault("max_detail_requests", 0)  # tách khỏi việc tải trang chi tiết
    return ScrapePipeline(factory, fetcher, now=clock, **kwargs)


async def crawl(
    pipeline: ScrapePipeline, category: Category = Category.mouse, max_pages: int | None = None
) -> PipelineResult:
    return await pipeline.run(SiteKey.gearvn, category, ScrapeTrigger.test, max_pages=max_pages)


def count(session: Session, model: type[Any]) -> int:
    session.expire_all()
    return int(session.exec(select(func.count()).select_from(model)).one())


def by_slug(session: Session) -> dict[str, Offer]:
    session.expire_all()
    return {offer.url.rsplit("/", 1)[1]: offer for offer in session.exec(select(Offer))}


# --- Trùng URL, nhiều trang, chạy lại ----------------------------------------------------------


async def test_a_url_repeated_within_and_across_pages_makes_one_offer_and_the_first_price_wins(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    page_one = listing_html(
        priced("a"), card(href="/products/a", title="Chuột a", body="<span>1.000.000đ</span>"),
        priced("b"), next_href="?page=2",
    )  # fmt: skip
    page_two = listing_html(
        card(href="/products/b", title="Chuột b", body="<span>1.000.000đ</span>"), priced("c")
    )
    fetcher = ScriptedFetcher(
        {MOUSES: served(MOUSES, page_one), MOUSES_P2: served(MOUSES_P2, page_two)}
    )

    result = await crawl(pipe(factory, fetcher, clock))

    assert result.status is ScrapeStatus.SUCCEEDED
    assert (result.pages_fetched, result.items_parsed, result.items_failed) == (2, 5, 0)
    assert result.offers_upserted == 3
    offers = by_slug(db_session)
    assert {slug: offer.price for slug, offer in offers.items()} == {
        "a": 1_990_000,
        "b": 1_990_000,
        "c": 1_990_000,
    }
    assert count(db_session, Product) == 3


async def test_rerunning_an_unchanged_listing_changes_nothing(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({LAPTOPS: served(LAPTOPS, fixture_html("listing_laptop_p1.html"))})
    pipeline = pipe(factory, fetcher, clock, default_max_pages=1)

    first = await crawl(pipeline, Category.laptop)
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline, Category.laptop)

    assert (first.offers_upserted, first.price_changes) == (20, 0)
    assert (second.offers_upserted, second.price_changes, second.changed_offer_ids) == (20, 0, ())
    assert (count(db_session, Offer), count(db_session, Product)) == (20, 20)
    assert count(db_session, PriceHistory) == 20  # chưa quá 24 giờ: không thêm dòng lịch sử


async def test_a_changed_price_adds_exactly_one_history_row_and_reports_that_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    html = fixture_html("listing_laptop_p1.html")
    first_slug = "laptop-acer-swift-air-14-ai-sfa14-i31-55nr-core-5-320-12gb-512gb-14-fhd-ips"
    assert html.index(">24.990.000đ<") < html.index("/products/laptop-gaming-acer-aspire-7-a715")
    fetcher = ScriptedFetcher({LAPTOPS: served(LAPTOPS, html)})
    pipeline = pipe(factory, fetcher, clock, default_max_pages=1)
    await crawl(pipeline, Category.laptop)

    fetcher.pages[LAPTOPS] = served(LAPTOPS, html.replace(">24.990.000đ<", ">23.490.000đ<", 1))
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline, Category.laptop)

    assert (second.offers_upserted, second.price_changes) == (20, 1)
    changed = db_session.get(Offer, second.changed_offer_ids[0])
    assert changed is not None and first_slug in changed.url
    assert (changed.price, changed.price_type) == (23_490_000, PriceType.regular)
    assert count(db_session, PriceHistory) == 21
    assert count(db_session, Product) == 20


async def test_sale_ending_updates_price_type_and_list_price_and_adds_a_history_row(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {MOUSES: served(MOUSES, listing_html(sale("a", "2.490.000đ", "1.990.000đ"), priced("b")))}
    )
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)
    assert (by_slug(db_session)["a"].price_type, by_slug(db_session)["a"].list_price) == (
        PriceType.sale,
        2_490_000,
    )

    fetcher.pages[MOUSES] = served(MOUSES, listing_html(priced("a"), priced("b")))
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline)

    offer = by_slug(db_session)["a"]
    assert (offer.price, offer.list_price, offer.price_type) == (1_990_000, None, PriceType.regular)
    assert second.price_changes == 0  # giá bán không đổi
    assert count(db_session, PriceHistory) == 3  # 2 dòng đầu + dòng đổi price_type


async def test_an_offer_that_vanished_and_comes_back_is_active_again_without_a_price_change(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    slugs = ["a", "b", "c", "d"]
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(*map(priced, slugs)))})
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)

    fetcher.pages[MOUSES] = served(MOUSES, listing_html(*map(priced, slugs[1:])))
    clock.now += timedelta(hours=1)
    await crawl(pipeline)
    assert by_slug(db_session)["a"].is_active is False

    fetcher.pages[MOUSES] = served(MOUSES, listing_html(*map(priced, slugs)))
    clock.now += timedelta(hours=1)
    third = await crawl(pipeline)

    assert by_slug(db_session)["a"].is_active is True
    assert (third.price_changes, count(db_session, Product)) == (0, 4)


# --- Thẻ ngừng kinh doanh, định dạng giá đổi ---------------------------------------------------


async def test_a_card_turning_discontinued_deactivates_only_its_own_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    slugs = ["a", "b", "c", "d", "e", "f"]
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(*map(priced, slugs)))})
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)

    fetcher.pages[MOUSES] = served(MOUSES, listing_html(unpriced("a"), *map(priced, slugs[1:])))
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline)

    assert (second.status, second.items_parsed, second.items_failed) == (
        ScrapeStatus.SUCCEEDED,
        6,
        1,
    )
    offers = by_slug(db_session)
    assert {slug: offer.is_active for slug, offer in offers.items()} == {
        "a": False,
        **dict.fromkeys(slugs[1:], True),
    }


async def test_a_page_of_mostly_discontinued_cards_is_partial_and_keeps_every_offer_active(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    slugs = ["a", "b", "c", "d", "e"]
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(*map(priced, slugs)))})
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)

    fetcher.pages[MOUSES] = served(MOUSES, listing_html(priced("a"), *map(unpriced, slugs[1:])))
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline)

    assert second.status is ScrapeStatus.PARTIAL
    assert (second.items_failed, second.offers_upserted) == (4, 1)
    assert all(offer.is_active for offer in by_slug(db_session).values())


async def test_a_price_format_change_on_every_card_is_partial_and_does_not_touch_stored_offers(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    slugs = [f"m{i}" for i in range(10)]
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(*map(priced, slugs)))})
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)

    changed = [
        card(href=f"/products/{slug}", title=f"Chuột {slug}", body="<span>1.990.000 ₫</span>")
        for slug in slugs
    ]
    fetcher.pages[MOUSES] = served(MOUSES, listing_html(*changed))
    clock.now += timedelta(hours=1)
    second = await crawl(pipeline)

    assert second.status is ScrapeStatus.PARTIAL
    assert (second.items_parsed, second.items_failed, second.offers_upserted) == (10, 10, 0)
    assert second.error_message is not None and "Cảnh báo chất lượng" in second.error_message
    offers = by_slug(db_session).values()
    assert all(offer.is_active and offer.price == 1_990_000 for offer in offers)


# --- Trang rỗng, chặn mềm, chặn CDN ------------------------------------------------------------


async def test_page_two_with_200_and_no_cards_ends_partial_keeps_page_one_and_deactivates_nothing(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    html = fixture_html("listing_laptop_p1.html")
    fetcher = ScriptedFetcher({LAPTOPS: served(LAPTOPS, html)})
    pipeline = pipe(factory, fetcher, clock, default_max_pages=1)
    await crawl(pipeline, Category.laptop)

    page_two = f"{LAPTOPS}?page=2"
    fetcher.pages[page_two] = served(page_two, EMPTY_PAGE)
    clock.now += timedelta(hours=1)
    result = await crawl(pipe(factory, fetcher, clock), Category.laptop, max_pages=5)

    assert result.status is ScrapeStatus.PARTIAL
    assert (result.pages_fetched, result.offers_upserted) == (1, 20)
    assert result.error_message is not None and "Trang 2" in result.error_message
    assert fetcher.requested[-2:] == [LAPTOPS, page_two]
    assert sum(offer.is_active for offer in by_slug(db_session).values()) == 20


async def test_an_empty_first_page_after_a_good_run_is_a_soft_block_with_a_site_cooldown(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(priced("a"), priced("b")))})
    pipeline = pipe(factory, fetcher, clock)
    await crawl(pipeline)

    fetcher.pages[MOUSES] = served(MOUSES, EMPTY_PAGE)
    clock.now += timedelta(hours=1)
    blocked = await crawl(pipeline)

    assert blocked.status is ScrapeStatus.BLOCKED
    assert blocked.challenge is not None and blocked.challenge.kind is ChallengeKind.soft_block
    assert all(offer.is_active for offer in by_slug(db_session).values())
    clock.now += timedelta(hours=23)
    with pytest.raises(SiteCooldown):
        await crawl(pipeline, Category.keyboard)  # mọi nhóm của trang bị nghỉ 24 giờ


async def test_cloudflare_503_on_a_detail_page_blocks_the_run_and_stops_further_requests(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    first_detail = f"{BASE}/products/a"
    fetcher = ScriptedFetcher(
        {
            MOUSES: served(MOUSES, listing_html(priced("a"), priced("b"), priced("c"))),
            first_detail: served(first_detail, "", 503, **{"cf-mitigated": "challenge"}),
        }
    )

    result = await crawl(pipe(factory, fetcher, clock, max_detail_requests=20))

    assert result.status is ScrapeStatus.BLOCKED
    assert (
        isinstance(result.challenge, Challenge) and result.challenge.kind is ChallengeKind.captcha
    )
    assert fetcher.requested == [MOUSES, first_detail]  # không tải thêm trang chi tiết nào
    with pytest.raises(SiteCooldown):
        await crawl(pipe(factory, fetcher, clock))


# --- Liên kết lạ trong thẻ ---------------------------------------------------------------------


async def test_cards_linking_off_site_are_failed_items_and_never_requested(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    cards = [
        priced("ok"),
        card(href="https://evil.example/products/x", title="Chuột x"),
        card(href="//evil.example/products/y", title="Chuột y"),
        card(href="https://www.gearvn.com/products/z", title="Chuột z"),
    ]
    fetcher = ScriptedFetcher({MOUSES: served(MOUSES, listing_html(*cards))})

    result = await crawl(pipe(factory, fetcher, clock, max_detail_requests=20))

    assert (result.items_parsed, result.items_failed, result.offers_upserted) == (4, 3, 1)
    assert list(by_slug(db_session)) == ["ok"]
    assert [url for url in fetcher.requested if "evil.example" in url or "www." in url] == []


# --- Thông số có nhãn qua các lượt -------------------------------------------------------------


async def test_a_later_run_without_detail_requests_keeps_the_labelled_specs_from_an_earlier_one(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            LAPTOPS: served(LAPTOPS, fixture_html("listing_laptop_p1.html")),
            DETAIL_URL: served(DETAIL_URL, fixture_html(f"detail_{DETAIL_SLUG}.html")),
        }
    )
    await crawl(
        pipe(factory, fetcher, clock, default_max_pages=1, max_detail_requests=20),
        Category.laptop,
    )
    assert by_slug(db_session)[DETAIL_SLUG].raw_specs["Dung lượng RAM"] == "8 GB"

    clock.now += timedelta(hours=1)
    fetcher.requested.clear()
    await crawl(
        pipe(factory, fetcher, clock, default_max_pages=1, max_detail_requests=0), Category.laptop
    )

    assert fetcher.requested == [LAPTOPS]
    assert by_slug(db_session)[DETAIL_SLUG].raw_specs["Dung lượng RAM"] == "8 GB"


async def test_a_nul_character_in_a_detail_spec_does_not_lose_the_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    detail_url = f"{BASE}/products/a"
    fetcher = ScriptedFetcher(
        {
            MOUSES: served(MOUSES, listing_html(priced("a"))),
            detail_url: served(detail_url, detail_page([{"name": "Màu", "value": "Đen\x00"}])),
        }
    )

    result = await crawl(pipe(factory, fetcher, clock, max_detail_requests=20))

    assert (result.offers_upserted, result.items_failed) == (1, 0)
    assert by_slug(db_session)["a"].price == 1_990_000


async def test_deeply_nested_json_ld_on_a_detail_page_does_not_fail_the_whole_run(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    detail_url = f"{BASE}/products/a"
    nested = "[" * 5000 + "]" * 5000
    fetcher = ScriptedFetcher(
        {
            MOUSES: served(MOUSES, listing_html(priced("a"), priced("b"))),
            detail_url: served(detail_url, detail_page(raw=nested)),
        }
    )

    result = await crawl(pipe(factory, fetcher, clock, max_detail_requests=20))

    assert result.status is not ScrapeStatus.FAILED
    assert result.offers_upserted == 2


async def test_card_linking_to_the_products_root_is_not_stored_as_an_offer(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = ScriptedFetcher(
        {
            MOUSES: served(
                MOUSES,
                listing_html(
                    priced("a"),
                    card(href="/products/", title="Chuột", body="<span>1.990.000đ</span>"),
                ),
            )
        }
    )

    await crawl(pipe(factory, fetcher, clock))

    assert list(by_slug(db_session)) == ["a"]
