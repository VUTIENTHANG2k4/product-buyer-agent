"""QA M10: LiveSearchService với đầu vào cực trị, cache hỏng/biên, đồng thời, múi giờ.

Test `xfail(strict=True)` mã `BUG-M10-n` giữ lỗi đã biết: XPASS báo đỏ, gỡ dấu khi sửa.
"""

import asyncio
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from sqlmodel import Session

from app.db.repositories import LiveSearchCacheRepository
from app.domain.dto import ListingItem, ListingPage
from app.domain.enums import Category, SiteKey
from app.domain.errors import ValidationFailed
from app.mock_shop.main import create_app
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.errors import (
    FetchError,
    FetchFailed,
    FormNotAllowed,
    HttpStatusError,
    OfflineModeError,
    RedirectError,
    ResponseTooLarge,
    RobotsBlocked,
    RobotsDisallowed,
    RobotsUnavailable,
)
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.mockshop import MockShopScraper
from app.services.live_search_service import (
    MAX_PER_SITE,
    REASON_BLOCKED,
    REASON_FAILED,
    REASON_OFFLINE,
    REASON_ROBOTS,
    LiveSearchService,
    normalize_query,
)
from scripts.run_eval import MockShopFetcher
from tests.integration.services.test_svc_live_search import (
    FPT,
    GEARVN,
    URL,
    AsgiFetcher,
    Clock,
    NoFetcher,
    fake_scraper,
    listing,
    service,
)
from tests.service_support import NOW, make_settings

INT8_MAX = 2**63 - 1


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


@pytest.fixture
def clock() -> Clock:
    return Clock()


def key_for(site: SiteKey, query: str) -> str:
    return f"live:v1:{site.value}:{query}"


def cached(db_session: Session, site: SiteKey, query: str, *, now: datetime = NOW) -> Any:
    return LiveSearchCacheRepository(db_session).get(
        key_for(site, query), max_age=timedelta(hours=6), now=now
    )


# --- Từ khóa lạ -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "a=b",
        "a&b",
        "x#y",
        "100%",
        "%zz",
        "loa?q=1",
        "'; DROP TABLE offer;--",
        "<b>loa</b>",
        "💥 loa",
    ],
)
async def test_hostile_characters_in_a_query_are_cached_literally_and_hit_the_cache(
    factory: Callable[[], Session], clock: Clock, db_session: Session, query: str
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)})

    first = await svc.search(query)
    again = await svc.search(query)

    assert (first.from_cache, again.from_cache) == (False, True)
    assert log == [f"gearvn:{query}:{MAX_PER_SITE}"]
    assert cached(db_session, GEARVN, query.casefold()) is not None


async def test_decomposed_and_composed_vietnamese_queries_share_one_cache_entry(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)})
    composed = "Ổ Cứng SSD"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed

    first = await svc.search(composed)
    second = await svc.search(decomposed)

    assert (first.from_cache, second.from_cache) == (False, True)
    assert len(log) == 1


def test_normalize_query_folds_case_whitespace_and_unicode_form() -> None:
    assert normalize_query("  Ổ CỨNG \t SSD\n") == "ổ cứng ssd"
    assert normalize_query(unicodedata.normalize("NFD", "ổ cứng")) == "ổ cứng"


BLANK_QUERIES = ["", " ", chr(0xA0) + chr(0x2003), chr(9) + chr(10) + chr(13)]


@pytest.mark.parametrize("query", BLANK_QUERIES)
async def test_query_without_visible_text_is_rejected_before_any_request(
    factory: Callable[[], Session], clock: Clock, query: str
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})

    with pytest.raises(ValidationFailed):
        await svc.search(query)

    assert log == []


async def test_a_query_of_exactly_two_hundred_characters_is_accepted(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)])})

    result = await svc.search("ổ" * 200)

    assert len(result.items) == 1


async def test_a_query_that_grows_past_the_limit_when_case_folded_is_a_validation_error(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [])})

    with pytest.raises(ValidationFailed):
        await svc.search("ß" * 150)  # casefold: "ß" -> "ss", 300 ký tự


@pytest.mark.parametrize(
    "query",
    [
        "loa" + chr(0) + "bluetooth",
        chr(0),
        "loa " + chr(0xD800) + " bluetooth",
        "loa" + chr(1),
        chr(0x7F),
    ],
)
async def test_control_characters_and_lone_surrogates_in_a_query_are_a_validation_error(
    factory: Callable[[], Session], clock: Clock, query: str
) -> None:
    """NUL / surrogate lẻ làm khóa cache PostgreSQL lỗi (DataError): phải chặn từ đầu."""
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)})

    with pytest.raises(ValidationFailed):
        await svc.search(query)

    assert log == []


async def test_a_raw_query_padded_with_spaces_beyond_the_limit_still_finds_mock_shop_products(
    factory: Callable[[], Session], clock: Clock
) -> None:
    padded = "loa" + " " * 300 + "bluetooth"  # chuẩn hóa chỉ còn 13 ký tự
    transport = httpx.ASGITransport(app=create_app(captcha_after=1000))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as client:
        svc = LiveSearchService(
            factory,
            make_settings(scraper_offline_only=True),
            AsgiFetcher(client),
            clock,
            {SiteKey.mockshop: MockShopScraper},
        )

        result = await svc.search(padded)

    assert len(result.items) >= 4, "mock-shop trả 422 vì từ khóa gốc quá 200 ký tự"


# --- Giá cực trị và lọc -----------------------------------------------------------------------


async def test_a_price_at_the_bigint_limit_survives_the_cache_round_trip(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, INT8_MAX)])})

    first = await svc.search("loa")
    again = await svc.search("loa")

    assert [i.price for i in first.items] == [INT8_MAX] == [i.price for i in again.items]
    assert again.from_cache is True


async def test_price_filter_with_bigint_bounds_keeps_every_priced_item(
    factory: Callable[[], Session], clock: Clock
) -> None:
    items = [listing(GEARVN, 1, 0), listing(GEARVN, 2, INT8_MAX), listing(GEARVN, 3, None)]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    result = await svc.search("loa", price_min=0, price_max=INT8_MAX)

    assert [i.price for i in result.items] == [0, INT8_MAX]  # mục không giá bị bỏ khi có cận


async def test_price_bounds_equal_keep_only_the_exact_price(
    factory: Callable[[], Session], clock: Clock
) -> None:
    items = [listing(GEARVN, n, p) for n, p in enumerate([999_999, 1_000_000, 1_000_001], 1)]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    result = await svc.search("loa", price_min=1_000_000, price_max=1_000_000)

    assert [i.price for i in result.items] == [1_000_000]


async def test_price_min_alone_and_price_max_zero_filter_correctly(
    factory: Callable[[], Session], clock: Clock
) -> None:
    items = [listing(GEARVN, 1, 0), listing(GEARVN, 2, 5), listing(GEARVN, 3, None)]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    only_min = await svc.search("loa", price_min=1)
    max_zero = await svc.search("loa", price_max=0)

    assert [i.price for i in only_min.items] == [5]
    assert [i.price for i in max_zero.items] == [0]


async def test_filter_that_removes_everything_still_reports_the_site_as_searched(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 5_000_000)])})

    result = await svc.search("loa", price_max=1_000_000)

    assert result.items == [] and result.sites_searched == [GEARVN]
    assert result.sites_skipped == []


@pytest.mark.parametrize("limit", [1, 9, 10, 11, 24, 25, 50, 10**9])
async def test_limit_per_site_is_bounded_by_the_cached_results(
    factory: Callable[[], Session], clock: Clock, limit: int
) -> None:
    items = [listing(GEARVN, n, 1_000 * n) for n in range(1, MAX_PER_SITE + 7)]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    result = await svc.search("loa", limit_per_site=limit)

    assert len(result.items) == min(limit, MAX_PER_SITE)


async def test_limit_is_applied_per_site_not_overall(
    factory: Callable[[], Session], clock: Clock
) -> None:
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, n, 10 * n) for n in range(1, 6)]),
        FPT: fake_scraper(FPT, [listing(FPT, n, 10 * n) for n in range(1, 6)]),
    }

    result = await service(factory, clock, scrapers).search("loa", limit_per_site=2)

    assert [i.site for i in result.items] == [GEARVN, GEARVN, FPT, FPT]


@pytest.mark.parametrize("limit", [0, -1, -(10**9)])
async def test_non_positive_limit_is_a_validation_error(
    factory: Callable[[], Session], clock: Clock, limit: int
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [])})

    with pytest.raises(ValidationFailed):
        await svc.search("loa", limit_per_site=limit)


# --- Dữ liệu từ scraper -----------------------------------------------------------------------


async def test_an_item_whose_url_cannot_be_cleaned_is_dropped_and_the_rest_is_kept(
    factory: Callable[[], Session], clock: Clock
) -> None:
    too_long = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/" + "x" * 2010, "title": "Dài", "price": 1}
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [too_long, listing(GEARVN, 2, 2)])})

    result = await svc.search("loa")

    assert [i.title for i in result.items] == ["Loa gearvn 2"]


async def test_tracking_parameters_are_stripped_from_result_urls(
    factory: Callable[[], Session], clock: Clock
) -> None:
    tracked = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/p?utm_source=x&id=7#frag", "title": "Loa", "price": 5}
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [tracked])})

    result = await svc.search("loa")

    assert [i.url for i in result.items] == [f"{URL}/p?id=7"]


async def test_the_same_product_url_listed_twice_is_returned_once(
    factory: Callable[[], Session], clock: Clock
) -> None:
    first = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/p/loa", "title": "Loa", "price": 5}
    )
    again = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/p/loa?utm_campaign=x", "title": "Loa", "price": 5}
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [first, again])})

    result = await svc.search("loa", limit_per_site=5)

    assert [i.url for i in result.items] == [f"{URL}/p/loa"]


async def test_titles_are_stored_in_nfc_without_nul_or_repeated_spaces(
    factory: Callable[[], Session], clock: Clock
) -> None:
    messy = "  Lo" + chr(0x323) + "a  Blue" + chr(0) + "tooth" + chr(10) + "  Ổ  "
    decomposed = unicodedata.normalize("NFD", messy.replace(chr(0), ""))
    entries = [
        ListingItem.model_validate(
            {"site": GEARVN, "url": f"{URL}/p/{n}", "title": title, "price": 5}
        )
        for n, title in enumerate([messy, decomposed], start=1)
    ]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, entries)})

    first = await svc.search("loa")
    again = await svc.search("loa")

    expected = unicodedata.normalize("NFC", "Lọa Bluetooth Ổ")
    assert [i.title for i in first.items] == [expected, expected]
    assert [i.title for i in again.items] == [expected, expected] and again.from_cache is True


async def test_an_item_whose_title_is_only_nul_is_dropped_instead_of_crashing_the_cache(
    factory: Callable[[], Session], clock: Clock
) -> None:
    blank = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/p/blank", "title": chr(0) * 3, "price": 5}
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [blank, listing(GEARVN, 2, 2)])})

    result = await svc.search("loa")

    assert [i.title for i in result.items] == ["Loa gearvn 2"]


async def test_a_very_long_title_is_stored_and_read_back_intact(
    factory: Callable[[], Session], clock: Clock
) -> None:
    long_item = ListingItem.model_validate(
        {"site": GEARVN, "url": f"{URL}/p/loa", "title": "Loa " + "ê" * 20_000, "price": 5}
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [long_item])})

    first = await svc.search("loa")
    again = await svc.search("loa")

    assert again.from_cache is True
    assert first.items[0].title == again.items[0].title and len(again.items[0].title) == 20_004


async def test_no_results_are_cached_as_an_empty_hit_for_the_ttl(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})

    first = await svc.search("zzz")
    second = await svc.search("zzz")

    assert first.items == second.items == []
    assert (first.from_cache, second.from_cache) == (False, True) and len(log) == 1


# --- Cache: biên TTL, múi giờ, mục hỏng -------------------------------------------------------


async def test_cache_is_still_valid_at_exactly_six_hours_and_expired_a_microsecond_later(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)})
    await svc.search("loa")

    clock.moment = NOW + timedelta(hours=6)
    on_edge = await svc.search("loa")
    clock.moment = NOW + timedelta(hours=6, microseconds=1)
    after = await svc.search("loa")

    assert (on_edge.from_cache, after.from_cache) == (True, False)
    assert len(log) == 2


async def test_cache_written_by_a_later_search_restarts_the_ttl_from_that_search(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)})
    await svc.search("loa")
    clock.advance(hours=7)
    await svc.search("loa")  # tìm lại, ghi cache mới lúc T+7h
    clock.advance(hours=5, minutes=59)

    hit = await svc.search("loa")

    assert hit.from_cache is True and len(log) == 2


async def test_a_clock_in_another_timezone_gives_the_same_instants(
    factory: Callable[[], Session],
) -> None:
    vn = timezone(timedelta(hours=7))
    moment = [NOW.astimezone(vn)]
    log: list[str] = []
    svc = LiveSearchService(
        factory,
        make_settings(scraper_offline_only=False),
        NoFetcher(),
        lambda: moment[0],
        {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)},
    )

    first = await svc.search("loa")
    moment[0] = (NOW + timedelta(hours=5, minutes=59)).astimezone(vn)
    hit = await svc.search("loa")
    moment[0] = (NOW + timedelta(hours=6, minutes=1)).astimezone(timezone(timedelta(hours=-5)))
    expired = await svc.search("loa")

    assert (first.from_cache, hit.from_cache, expired.from_cache) == (False, True, False)
    assert hit.items[0].scraped_at == NOW and hit.items[0].scraped_at.utcoffset() is not None
    assert len(log) == 2


@pytest.mark.parametrize(
    "bad_entry",
    [
        {"title": "Loa", "price": -1, "url": f"{URL}/p/a"},
        {"title": "Loa", "price": 1.5, "url": f"{URL}/p/a"},
        {"title": "Loa", "price": "5.000", "url": f"{URL}/p/a"},
        {"title": "Loa", "price": INT8_MAX + 1, "url": f"{URL}/p/a"},
        {"title": "Loa", "price": True, "url": f"{URL}/p/a"},
        {"title": "", "price": 5, "url": f"{URL}/p/a"},
        {"title": "   ", "price": 5, "url": f"{URL}/p/a"},
        {"title": "Loa", "price": 5, "url": ""},
        {"title": "Loa", "price": 5},
        {"price": 5, "url": f"{URL}/p/a"},
        {"title": None, "price": 5, "url": f"{URL}/p/a"},
        {"title": "Loa", "price": 5, "url": 123},
        {},
    ],
    ids=lambda entry: str(sorted(entry))[:40] + str(entry.get("price")),
)
async def test_a_cache_entry_with_one_bad_item_is_discarded_and_replaced_by_a_fresh_search(
    factory: Callable[[], Session],
    clock: Clock,
    db_session: Session,
    bad_entry: dict[str, Any],
) -> None:
    good = {"title": "Tốt", "price": 1, "url": f"{URL}/p/good"}
    LiveSearchCacheRepository(db_session).put(key_for(GEARVN, "loa"), [good, bad_entry], now=NOW)
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 7)], log=log)})

    result = await svc.search("loa")

    assert len(log) == 1 and result.from_cache is False
    assert [i.price for i in result.items] == [7]
    healed = cached(db_session, GEARVN, "loa")
    assert [row["price"] for row in healed.results] == [7]


@pytest.mark.parametrize("results", [["text"], [1, 2], [None], [[("title", "x")]], [["a"]]])
async def test_a_cache_entry_that_is_not_a_list_of_objects_is_a_miss(
    factory: Callable[[], Session], clock: Clock, db_session: Session, results: list[Any]
) -> None:
    from app.db.models import LiveSearchCache

    db_session.add(
        LiveSearchCache(cache_key=key_for(GEARVN, "loa"), results=results, created_at=NOW)
    )
    db_session.flush()
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 7)], log=log)})

    result = await svc.search("loa")

    assert len(log) == 1 and [i.price for i in result.items] == [7]


async def test_cache_entry_dated_in_the_future_is_still_served(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    """Đồng hồ lùi (NTP): mục cache có created_at tương lai không bị coi là hết hạn ngay."""
    LiveSearchCacheRepository(db_session).put(
        key_for(GEARVN, "loa"),
        [{"title": "Cũ", "price": 1, "url": f"{URL}/p/old"}],
        now=NOW + timedelta(hours=1),
    )
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})

    result = await svc.search("loa")

    assert result.from_cache is True and log == []


async def test_blocked_marker_of_one_site_does_not_leak_into_other_sites_or_queries(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    LiveSearchCacheRepository(db_session).put(
        "live:v1:blocked:gearvn", [{"reason": "x"}], now=NOW - timedelta(hours=1)
    )
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], log=log),
    }

    result = await service(factory, clock, scrapers).search("loa")

    assert result.sites_searched == [FPT] and [s.site for s in result.sites_skipped] == [GEARVN]
    assert log == [f"fptshop:loa:{MAX_PER_SITE}"]


async def test_a_query_that_looks_like_the_blocked_marker_does_not_read_the_marker_as_results(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    LiveSearchCacheRepository(db_session).put(
        "live:v1:blocked:gearvn", [{"reason": "x"}], now=NOW - timedelta(hours=30)
    )
    log: list[str] = []
    svc = service(factory, clock, {FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], log=log)})

    result = await svc.search("blocked:gearvn")

    assert log == [f"fptshop:blocked:gearvn:{MAX_PER_SITE}"] and len(result.items) == 1


# --- Đồng thời --------------------------------------------------------------------------------


class Probe:
    active = 0
    peak = 0
    entered: asyncio.Event | None = None


def probing_scraper(key: SiteKey, log: list[str]) -> type[BaseScraper]:
    """Scraper giả ghi số lần `live_search` chạy cùng lúc (phải luôn là 1)."""

    class Slow(BaseScraper):
        config: ClassVar[SiteConfig] = SiteConfig(
            key=key, base_url=URL, min_delay_s=0.0, supports_live_search=True
        )

        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage(items=[], has_next=False)

        async def live_search(self, query: str, limit: int) -> list[ListingItem]:
            Probe.active += 1
            Probe.peak = max(Probe.peak, Probe.active)
            log.append(query)
            if Probe.entered is not None:
                Probe.entered.set()
            try:
                await asyncio.sleep(0.01)
            finally:
                Probe.active -= 1
            return [listing(key, 1, 10)]

    return Slow


async def test_many_concurrent_distinct_queries_never_overlap_on_the_same_site(
    factory: Callable[[], Session], clock: Clock
) -> None:
    Probe.active = Probe.peak = 0
    log: list[str] = []
    svc = service(
        factory,
        clock,
        {GEARVN: probing_scraper(GEARVN, log), FPT: probing_scraper(FPT, log)},
    )
    queries = [f"loa {n}" for n in range(8)]

    results = await asyncio.gather(*(svc.search(q) for q in queries))

    assert Probe.peak == 1
    assert len(log) == 16 and all(len(r.items) == 2 for r in results)


async def test_concurrent_identical_queries_search_each_site_once(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: probing_scraper(GEARVN, log)})

    results = await asyncio.gather(*(svc.search("Loa  Bluetooth") for _ in range(6)))

    assert len(log) == 1
    assert sorted(r.from_cache for r in results) == [False] + [True] * 5


async def test_an_invalid_search_in_the_middle_of_a_gather_does_not_block_the_others(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)])})

    outcomes = await asyncio.gather(
        svc.search("loa"),
        svc.search(""),
        svc.search("ssd", limit_per_site=0),
        svc.search("tai"),
        return_exceptions=True,
    )

    assert [type(o).__name__ for o in outcomes] == [
        "LiveSearchResult",
        "ValidationFailed",
        "ValidationFailed",
        "LiveSearchResult",
    ]


async def test_a_cancelled_search_releases_the_lock_for_the_next_one(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    Probe.active = Probe.peak = 0
    Probe.entered = asyncio.Event()
    svc = service(factory, clock, {GEARVN: probing_scraper(GEARVN, log)})

    running = asyncio.create_task(svc.search("loa một"))
    await asyncio.wait_for(Probe.entered.wait(), timeout=5)  # đã giữ khóa, đang chờ trang
    Probe.entered = None
    waiting = asyncio.create_task(svc.search("loa hai"))
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    result = await asyncio.wait_for(waiting, timeout=5)

    assert [i.title for i in result.items] == ["Loa gearvn 1"]
    again = await asyncio.wait_for(svc.search("loa ba"), timeout=5)
    assert len(again.items) == 1


async def test_a_database_failure_inside_one_search_does_not_leave_the_service_locked(
    db_session: Session, clock: Clock
) -> None:
    bind = db_session.get_bind()
    attempts = {"n": 0}

    def flaky() -> Session:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("connection lost")
        return Session(bind=bind, join_transaction_mode="create_savepoint")

    svc = service(flaky, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)])})

    with pytest.raises(RuntimeError):
        await svc.search("loa")
    result = await asyncio.wait_for(svc.search("loa"), timeout=5)

    assert len(result.items) == 1


async def test_the_service_keeps_working_after_a_corrupt_marker_and_expired_entries(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    LiveSearchCacheRepository(db_session).put(
        "live:v1:blocked:gearvn", [], now=NOW - timedelta(days=3)
    )
    LiveSearchCacheRepository(db_session).put(
        key_for(GEARVN, "loa"), [], now=NOW - timedelta(days=3)
    )
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)])})

    result = await svc.search("loa")

    assert result.sites_searched == [GEARVN] and len(result.items) == 1
    assert datetime(2026, 10, 20, tzinfo=UTC) <= NOW


# --- Lỗi tải và captcha -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (HttpStatusError("404", url=URL, status=404), REASON_FAILED),
        (HttpStatusError("503", url=URL, status=503), REASON_FAILED),
        (RedirectError("redirect off-site", url=URL), REASON_FAILED),
        (ResponseTooLarge("too big", url=URL), REASON_FAILED),
        (FormNotAllowed("post", url=URL), REASON_FAILED),
        (FetchFailed("timeout", url=URL), REASON_FAILED),
        (FetchError("generic", url=URL), REASON_FAILED),
        (RobotsUnavailable("robots 5xx", url=URL), REASON_FAILED),
        (RobotsDisallowed("robots disallow", url=URL), REASON_ROBOTS),
        (RobotsBlocked("robots 429", url=URL, status=429), REASON_BLOCKED),
        (OfflineModeError("offline", url=URL), REASON_OFFLINE),
        (TimeoutError("slow"), REASON_FAILED),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), REASON_FAILED),
        (KeyError("parser"), REASON_FAILED),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, Exception) else str(value)[:20],
)
async def test_every_fetch_failure_becomes_a_skipped_site_and_never_an_exception(
    factory: Callable[[], Session], clock: Clock, error: Exception, reason: str
) -> None:
    scrapers = {
        GEARVN: fake_scraper(GEARVN, error),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)]),
    }

    result = await service(factory, clock, scrapers).search("loa")

    assert [(s.site, s.reason) for s in result.sites_skipped] == [(GEARVN, reason)]
    assert result.sites_searched == [FPT] and len(result.items) == 1


async def test_when_every_site_fails_the_result_is_empty_with_all_reasons(
    factory: Callable[[], Session], clock: Clock
) -> None:
    scrapers = {
        GEARVN: fake_scraper(GEARVN, FetchFailed("timeout", url=URL)),
        FPT: fake_scraper(FPT, RobotsDisallowed("no", url=URL)),
    }

    result = await service(factory, clock, scrapers).search("loa")

    assert result.items == [] and result.sites_searched == []
    assert result.from_cache is False
    assert {s.site: s.reason for s in result.sites_skipped} == {
        GEARVN: REASON_FAILED,
        FPT: REASON_ROBOTS,
    }


async def test_a_captcha_on_the_mock_shop_skips_it_without_a_cooldown_or_cache_entry(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    transport = httpx.ASGITransport(app=create_app(captcha_after=1))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as client:
        svc = LiveSearchService(
            factory,
            make_settings(scraper_offline_only=True),
            AsgiFetcher(client),
            clock,
            {SiteKey.mockshop: MockShopScraper},
        )

        first = await svc.search("loa bluetooth")
        second = await svc.search("ổ cứng")
        third = await svc.search("loa bluetooth")  # vẫn bị captcha, không đọc từ cache

    assert first.sites_searched == [SiteKey.mockshop] and len(first.items) >= 4
    assert [(s.site, s.reason) for s in second.sites_skipped] == [
        (SiteKey.mockshop, REASON_BLOCKED)
    ]
    assert second.sites_searched == [] and second.items == []
    assert third.from_cache is True  # kết quả tốt đã cache từ lần đầu
    assert cached(db_session, SiteKey.mockshop, "ổ cứng") is None
    assert (
        LiveSearchCacheRepository(db_session).get(
            "live:v1:blocked:mockshop", max_age=timedelta(hours=24), now=NOW
        )
        is None
    )


# --- Registry thật, fixture thật, không mạng --------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class RecordingFixtureFetcher:
    """Trả trang tìm kiếm đã lưu cho GearVN/FPT Shop, trang rỗng cho mock-shop; ghi URL đã hỏi."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        if url.startswith("https://gearvn.com/"):
            text = (FIXTURES / "gearvn" / "search_loa_bluetooth.html").read_text(encoding="utf-8")
        elif url.startswith("https://fptshop.com.vn/"):
            text = (FIXTURES / "fptshop" / "search_loa_bluetooth.html").read_text(encoding="utf-8")
        else:
            text = "<html></html>"
        return FetchResponse(url=url, final_url=url, status=200, text=text)


async def test_offline_mode_with_the_real_registry_requests_only_the_mock_shop(
    factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = RecordingFixtureFetcher()
    svc = LiveSearchService(factory, make_settings(scraper_offline_only=True), fetcher, clock)

    result = await svc.search("loa bluetooth")

    assert len(fetcher.requested) == 1
    assert fetcher.requested[0].startswith(("http://localhost", "http://127.0.0.1"))
    assert {s.site for s in result.sites_skipped} == {GEARVN, FPT}
    assert all(s.reason == REASON_OFFLINE for s in result.sites_skipped)


async def test_online_mode_with_the_real_registry_requests_only_real_sites_one_page_each(
    factory: Callable[[], Session], clock: Clock
) -> None:
    fetcher = RecordingFixtureFetcher()
    svc = LiveSearchService(factory, make_settings(scraper_offline_only=False), fetcher, clock)

    result = await svc.search("Loa  Bluetooth", price_max=1_000_000, limit_per_site=3)

    assert fetcher.requested == [
        "https://gearvn.com/search?q=Loa+Bluetooth",
        "https://fptshop.com.vn/tim-kiem?s=Loa+Bluetooth",
    ]
    assert result.sites_searched == [GEARVN, FPT] and result.sites_skipped == []
    assert 0 < len(result.items) <= 6
    assert all(i.price is not None and i.price <= 1_000_000 for i in result.items)
    assert all(
        i.url.startswith(("https://gearvn.com/", "https://fptshop.com.vn/")) for i in result.items
    )
    assert [i.site for i in result.items] == sorted(
        (i.site for i in result.items), key=[GEARVN, FPT].index
    )


async def test_the_eval_mock_shop_fetcher_serves_search_pages_and_the_service_finds_speakers(
    factory: Callable[[], Session], clock: Clock
) -> None:
    svc = LiveSearchService(
        factory, make_settings(scraper_offline_only=True), MockShopFetcher(), clock
    )

    result = await svc.search("loa bluetooth", price_max=1_000_000)

    assert result.sites_searched == [SiteKey.mockshop]
    assert [i.price for i in result.items] == [590_000, 890_000]
