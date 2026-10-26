"""LiveSearchService (T10.2): tuần tự, cache (trang, từ khóa), lọc giá, trang chặn nghỉ 24 giờ."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar

import httpx
import pytest
from sqlmodel import Session

from app.db.repositories import LiveSearchCacheRepository
from app.domain.dto import ListingItem, ListingPage
from app.domain.enums import Category, ScrapeStatus, SiteKey
from app.domain.errors import ValidationFailed
from app.mock_shop.main import create_app
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.challenge import ChallengeDetected, soft_block_challenge
from app.scrapers.http.errors import (
    FetchFailed,
    OfflineModeError,
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
)
from tests.factories import make_scrape_run
from tests.service_support import NOW, make_settings

URL = "https://shop.example"


class Clock:
    def __init__(self, moment: datetime = NOW) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


def listing(site: SiteKey, n: int, price: int | None) -> ListingItem:
    return ListingItem.model_validate(
        {
            "site": site,
            "url": f"{URL}/{site.value}/p{n}",
            "title": f"Loa {site.value} {n}",
            "price": price,
        }
    )


def fake_scraper(
    key: SiteKey,
    outcome: list[ListingItem] | Exception,
    *,
    is_mock: bool = False,
    supports: bool = True,
    enabled: bool = True,
    log: list[str] | None = None,
) -> type[BaseScraper]:
    """Scraper giả: `live_search` trả danh sách định sẵn hoặc ném lỗi; ghi lại các lần gọi."""
    calls: list[str] = log if log is not None else []

    class Fake(BaseScraper):
        config: ClassVar[SiteConfig] = SiteConfig(
            key=key,
            base_url=URL,
            min_delay_s=0.0,
            supports_live_search=supports,
            is_mock=is_mock,
            enabled=enabled,
        )
        queries: ClassVar[list[str]] = calls

        def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
            return ListingPage(items=[], has_next=False)

        async def live_search(self, query: str, limit: int) -> list[ListingItem]:
            calls.append(f"{key.value}:{query}:{limit}")
            await asyncio.sleep(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome[:limit]

    return Fake


class NoFetcher:
    async def get(self, url: str) -> FetchResponse:  # pragma: no cover - scraper giả không tải
        raise AssertionError(f"unexpected request to {url}")


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


@pytest.fixture
def clock() -> Clock:
    return Clock()


def service(
    factory: Callable[[], Session],
    clock: Clock,
    scrapers: dict[SiteKey, type[BaseScraper]],
    *,
    offline: bool = False,
    ttl_hours: int = 6,
) -> LiveSearchService:
    settings = make_settings(scraper_offline_only=offline, live_search_cache_ttl_hours=ttl_hours)
    return LiveSearchService(factory, settings, NoFetcher(), clock, scrapers)


GEARVN = SiteKey.gearvn
FPT = SiteKey.fptshop


# --- Mock-shop thật qua ASGI (chế độ ngoại tuyến) ---------------------------------------------


class AsgiFetcher:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        response = await self.client.get(url)
        return FetchResponse(
            url=url, final_url=str(response.url), status=response.status_code, text=response.text
        )


async def test_offline_search_finds_speakers_under_a_million_in_the_mock_shop(
    factory: Callable[[], Session], clock: Clock
) -> None:
    app = create_app(captcha_after=1000)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as client:
        fetcher = AsgiFetcher(client)
        scrapers: dict[SiteKey, type[BaseScraper]] = {
            SiteKey.mockshop: MockShopScraper,
            GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 100_000)]),
            FPT: fake_scraper(FPT, [listing(FPT, 1, 100_000)]),
        }
        svc = LiveSearchService(
            factory, make_settings(scraper_offline_only=True), fetcher, clock, scrapers
        )

        result = await svc.search("loa bluetooth", price_max=1_000_000, limit_per_site=5)

    assert result.sites_searched == [SiteKey.mockshop]
    assert {(s.site, s.reason) for s in result.sites_skipped} == {
        (GEARVN, REASON_OFFLINE),
        (FPT, REASON_OFFLINE),
    }
    assert [item.title for item in result.items] == [
        "Loa Bluetooth Edifier Mock Mini M1",
        "Loa Bluetooth Sony Mock Boom B3",
    ]  # JBL 1.490.000 quá giá; Xiaomi "Liên hệ" (không giá) bị bỏ khi có lọc giá
    assert all(item.site is SiteKey.mockshop and item.scraped_at == NOW for item in result.items)
    assert result.label == "unnormalized" and result.from_cache is False
    assert len(fetcher.requested) == 1


# --- Chọn trang -------------------------------------------------------------------------------


async def test_online_search_uses_real_sites_in_order_and_skips_mock_shop(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 500_000)], log=log),
        SiteKey.mockshop: fake_scraper(
            SiteKey.mockshop, [listing(SiteKey.mockshop, 1, 1)], is_mock=True, log=log
        ),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 700_000)], log=log),
    }
    result = await service(factory, clock, scrapers).search("Loa Bluetooth")

    assert log == [
        f"gearvn:Loa Bluetooth:{MAX_PER_SITE}",
        f"fptshop:Loa Bluetooth:{MAX_PER_SITE}",
    ]  # tuần tự, từ khóa gốc
    assert result.sites_searched == [GEARVN, FPT]
    assert [item.site for item in result.items] == [GEARVN, FPT]
    assert result.sites_skipped == []


async def test_only_enabled_sites_that_support_live_search_are_searched(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], supports=False, log=log),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], enabled=False, log=log),
        SiteKey.anphat: fake_scraper(SiteKey.anphat, [listing(SiteKey.anphat, 1, 5)], log=log),
    }
    result = await service(factory, clock, scrapers).search("loa")

    assert log == [f"anphat:loa:{MAX_PER_SITE}"]
    assert result.sites_searched == [SiteKey.anphat]
    assert result.sites_skipped == []


async def test_offline_mode_never_calls_a_real_site(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log),
        SiteKey.mockshop: fake_scraper(
            SiteKey.mockshop, [listing(SiteKey.mockshop, 1, 9)], is_mock=True, log=log
        ),
    }
    result = await service(factory, clock, scrapers, offline=True).search("loa")

    assert log == [f"mockshop:loa:{MAX_PER_SITE}"]
    assert [(s.site, s.reason) for s in result.sites_skipped] == [(GEARVN, REASON_OFFLINE)]


# --- Cache ------------------------------------------------------------------------------------


async def test_second_search_is_served_from_cache_until_the_ttl_expires(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 300_000)], log=log)}
    svc = service(factory, clock, scrapers)

    first = await svc.search("loa bluetooth")
    clock.advance(hours=5, minutes=59)
    second = await svc.search("loa bluetooth")
    clock.advance(minutes=2)  # đã quá 6 giờ kể từ lần đầu
    third = await svc.search("loa bluetooth")

    assert (first.from_cache, second.from_cache, third.from_cache) == (False, True, False)
    assert len(log) == 2
    assert second.items[0].scraped_at == NOW  # thời điểm tìm thật, không phải lúc đọc cache
    assert third.items[0].scraped_at == NOW + timedelta(hours=6, minutes=1)


async def test_cache_ttl_follows_the_setting(factory: Callable[[], Session], clock: Clock) -> None:
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)}
    svc = service(factory, clock, scrapers, ttl_hours=1)

    await svc.search("loa")
    clock.advance(minutes=61)
    await svc.search("loa")

    assert len(log) == 2


async def test_query_spelling_variants_share_one_cache_entry(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)}
    svc = service(factory, clock, scrapers)

    await svc.search("Loa  Bluetooth ")
    again = await svc.search("loa bluetooth")

    assert again.from_cache is True and len(log) == 1
    entry = LiveSearchCacheRepository(db_session).get(
        "live:v1:gearvn:loa bluetooth", max_age=timedelta(hours=6), now=NOW
    )
    assert entry is not None and len(entry.results) == 1


async def test_from_cache_is_false_when_only_some_sites_come_from_cache(
    factory: Callable[[], Session], clock: Clock
) -> None:
    scrapers = {
        GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)]),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)]),
    }
    await service(factory, clock, {GEARVN: scrapers[GEARVN]}).search("loa")

    mixed = await service(factory, clock, scrapers).search("loa")

    assert mixed.sites_searched == [GEARVN, FPT] and mixed.from_cache is False


async def test_a_corrupt_cache_entry_is_treated_as_a_miss(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    LiveSearchCacheRepository(db_session).put("live:v1:gearvn:loa", [{"unexpected": 1}], now=NOW)
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)}

    result = await service(factory, clock, scrapers).search("loa")

    assert len(log) == 1 and len(result.items) == 1 and result.from_cache is False


async def test_concurrent_searches_run_one_after_another_and_share_the_cache(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)}
    svc = service(factory, clock, scrapers)

    first, second = await asyncio.gather(svc.search("loa"), svc.search("loa"))

    assert len(log) == 1
    assert sorted([first.from_cache, second.from_cache]) == [False, True]


# --- Giới hạn và lọc giá ----------------------------------------------------------------------


async def test_results_are_cut_to_limit_per_site_but_the_cache_keeps_ten(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    items = [listing(GEARVN, n, 100_000 * n) for n in range(1, 15)]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items, log=log)})

    few = await svc.search("loa", limit_per_site=3)
    more = await svc.search("loa", limit_per_site=8)

    assert [i.title for i in few.items] == [f"Loa gearvn {n}" for n in (1, 2, 3)]
    assert len(more.items) == 8 and len(log) == 1  # lần hai đọc cache, không tìm lại
    assert log == [f"gearvn:loa:{MAX_PER_SITE}"]


async def test_price_filter_runs_before_the_per_site_cut_and_drops_unpriced_items(
    factory: Callable[[], Session], clock: Clock
) -> None:
    items = [
        listing(GEARVN, 1, 2_000_000),
        listing(GEARVN, 2, None),
        listing(GEARVN, 3, 2_500_000),
        listing(GEARVN, 4, 900_000),
        listing(GEARVN, 5, 400_000),
    ]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    cheap = await svc.search("loa", price_max=1_000_000, limit_per_site=1)
    ranged = await svc.search("loa", price_min=500_000, price_max=1_000_000)
    unfiltered = await svc.search("loa")

    assert [i.price for i in cheap.items] == [900_000]  # không phải mục đầu bị cắt trước
    assert [i.price for i in ranged.items] == [900_000]
    assert len(unfiltered.items) == 5  # không lọc giá thì giữ cả mục không giá


async def test_price_bounds_are_inclusive(factory: Callable[[], Session], clock: Clock) -> None:
    items = [
        listing(GEARVN, 1, 500_000),
        listing(GEARVN, 2, 1_000_000),
        listing(GEARVN, 3, 1_000_001),
    ]
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, items)})

    result = await svc.search("loa", price_min=500_000, price_max=1_000_000)

    assert [i.price for i in result.items] == [500_000, 1_000_000]


# --- Trang lỗi hoặc chặn ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (OfflineModeError("offline", url=URL), REASON_OFFLINE),
        (RobotsDisallowed("robots", url=URL), REASON_ROBOTS),
        (FetchFailed("timeout", url=URL), REASON_FAILED),
    ],
)
async def test_a_failing_site_is_skipped_with_a_reason_and_not_cached(
    factory: Callable[[], Session],
    clock: Clock,
    error: Exception,
    reason: str,
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, error, log=log),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], log=log),
    }
    svc = service(factory, clock, scrapers)

    first = await svc.search("loa")
    await svc.search("loa")

    assert [(s.site, s.reason) for s in first.sites_skipped] == [(GEARVN, reason)]
    assert first.sites_searched == [FPT] and len(first.items) == 1
    assert log.count(f"gearvn:loa:{MAX_PER_SITE}") == 2  # lỗi không vào cache, lần sau thử lại


async def test_an_unexpected_scraper_error_skips_only_that_site(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, ValueError("parser bug"), log=log),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], log=log),
    }
    svc = service(factory, clock, scrapers)

    first = await svc.search("loa")
    await svc.search("loa")

    assert [(s.site, s.reason) for s in first.sites_skipped] == [(GEARVN, REASON_FAILED)]
    assert first.sites_searched == [FPT] and len(first.items) == 1
    assert log.count(f"gearvn:loa:{MAX_PER_SITE}") == 2  # không cache lỗi


async def test_robots_txt_that_cannot_be_loaded_is_a_failure_not_a_prohibition(
    factory: Callable[[], Session], clock: Clock
) -> None:
    scrapers = {GEARVN: fake_scraper(GEARVN, RobotsUnavailable("5xx", url=URL))}

    result = await service(factory, clock, scrapers).search("loa")

    assert [(s.site, s.reason) for s in result.sites_skipped] == [(GEARVN, REASON_FAILED)]


async def test_the_mock_shop_never_gets_a_blocked_marker(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    challenge = ChallengeDetected(soft_block_challenge(SiteKey.mockshop, URL))
    scrapers = {SiteKey.mockshop: fake_scraper(SiteKey.mockshop, challenge, is_mock=True)}

    await service(factory, clock, scrapers, offline=True).search("loa")

    assert (
        LiveSearchCacheRepository(db_session).get(
            "live:v1:blocked:mockshop", max_age=timedelta(hours=24), now=NOW
        )
        is None
    )


@pytest.mark.parametrize(
    "error",
    [
        ChallengeDetected(soft_block_challenge(GEARVN, URL)),
        RobotsBlocked("403", url=URL, status=403),
    ],
    ids=["challenge", "robots-blocked"],
)
async def test_a_blocking_site_rests_for_24_hours_while_other_sites_still_answer(
    factory: Callable[[], Session], clock: Clock, error: Exception
) -> None:
    log: list[str] = []
    scrapers = {
        GEARVN: fake_scraper(GEARVN, error, log=log),
        FPT: fake_scraper(FPT, [listing(FPT, 1, 1)], log=log),
    }
    svc = service(factory, clock, scrapers)

    first = await svc.search("loa")
    clock.advance(hours=23)
    other_query = await svc.search("ssd")  # từ khóa khác vẫn không gọi lại trang đang nghỉ
    clock.advance(hours=1, minutes=1)
    after = await svc.search("tai nghe")

    assert [(s.site, s.reason) for s in first.sites_skipped] == [(GEARVN, REASON_BLOCKED)]
    assert [(s.site, s.reason) for s in other_query.sites_skipped] == [(GEARVN, REASON_BLOCKED)]
    assert first.sites_searched == [FPT]
    assert log.count(f"gearvn:loa:{MAX_PER_SITE}") == 1 and f"gearvn:ssd:{MAX_PER_SITE}" not in log
    assert f"gearvn:tai nghe:{MAX_PER_SITE}" in log  # hết 24 giờ: thử lại
    assert after.sites_searched == [FPT]


async def test_a_blocked_scrape_run_also_rests_the_site_for_live_search(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    db_session.add(
        make_scrape_run(
            site=GEARVN,
            status=ScrapeStatus.BLOCKED,
            started_at=NOW - timedelta(hours=2),
        )
    )
    db_session.flush()
    log: list[str] = []
    scrapers = {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 1)], log=log)}

    result = await service(factory, clock, scrapers).search("loa")

    assert log == [] and [(s.site, s.reason) for s in result.sites_skipped] == [
        (GEARVN, REASON_BLOCKED)
    ]
    assert result.sites_searched == [] and result.items == [] and result.from_cache is False


async def test_a_cooldown_does_not_apply_to_the_mock_shop(
    factory: Callable[[], Session], clock: Clock, db_session: Session
) -> None:
    db_session.add(
        make_scrape_run(site=SiteKey.mockshop, status=ScrapeStatus.BLOCKED, started_at=NOW)
    )
    db_session.flush()
    scrapers = {
        SiteKey.mockshop: fake_scraper(
            SiteKey.mockshop, [listing(SiteKey.mockshop, 1, 1)], is_mock=True
        )
    }

    result = await service(factory, clock, scrapers, offline=True).search("loa")

    assert result.sites_searched == [SiteKey.mockshop]


# --- Đầu vào ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "   \t "},
        {"query": "x" * 201},
        {"query": "loa", "limit_per_site": 0},
        {"query": "loa", "price_min": 2_000_000, "price_max": 1_000_000},
    ],
)
async def test_invalid_input_is_rejected_before_any_request(
    factory: Callable[[], Session], clock: Clock, kwargs: dict[str, object]
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})

    with pytest.raises(ValidationFailed):
        await svc.search(**kwargs)  # type: ignore[arg-type]

    assert log == []


async def test_no_sites_available_returns_an_empty_unnormalized_result(
    factory: Callable[[], Session], clock: Clock
) -> None:
    result = await service(factory, clock, {}).search("loa")

    assert (result.items, result.sites_searched, result.sites_skipped) == ([], [], [])
    assert result.from_cache is False and result.label == "unnormalized"


async def test_naive_clock_is_rejected(factory: Callable[[], Session]) -> None:
    svc = LiveSearchService(
        factory,
        make_settings(),
        NoFetcher(),
        lambda: datetime(2026, 10, 20, 12, 0),
        {GEARVN: fake_scraper(GEARVN, [])},
    )

    with pytest.raises(ValidationFailed):
        await svc.search("loa")
