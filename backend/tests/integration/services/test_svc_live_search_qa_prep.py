"""QA "Chuẩn bị bảo vệ" (T10.4): trần 24 kết quả, TTL 1 giờ cho kết quả rỗng, dọn cache cũ."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.db.models import LiveSearchCache
from app.db.repositories import LiveSearchCacheRepository
from app.scrapers.pipeline import BLOCK_COOLDOWN
from app.services.live_search_service import MAX_PER_SITE, blocked_key, cache_key
from tests.integration.services.test_svc_live_search import (
    FPT,
    GEARVN,
    Clock,
    fake_scraper,
    listing,
    service,
)


@pytest.fixture
def factory(db_session: Session) -> Callable[[], Session]:
    bind = db_session.get_bind()
    return lambda: Session(bind=bind, join_transaction_mode="create_savepoint")


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _keys(session: Session) -> list[str]:
    return sorted(row.cache_key for row in session.exec(select(LiveSearchCache)).all())


# ---- MAX_PER_SITE -----------------------------------------------------------------------------
async def test_the_scraper_is_asked_for_exactly_the_cache_cap_and_the_cache_holds_that_many(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    items = [listing(FPT, n, 500_000 + n) for n in range(1, MAX_PER_SITE + 10)]
    svc = service(factory, clock, {FPT: fake_scraper(FPT, items, log=log)})

    first = await svc.search("loa", limit_per_site=100)
    second = await svc.search("loa", limit_per_site=100)

    assert log == [f"fptshop:loa:{MAX_PER_SITE}"]
    assert len(first.items) == len(second.items) == MAX_PER_SITE
    assert second.from_cache and not first.from_cache
    entry = db_session.get(LiveSearchCache, cache_key(FPT, "loa"))
    assert entry is not None and len(entry.results) == MAX_PER_SITE


async def test_limit_per_site_below_the_cache_cap_is_applied_after_the_price_filter(
    factory: Callable[[], Session], clock: Clock
) -> None:
    items = [listing(FPT, n, 100_000 * n) for n in range(1, MAX_PER_SITE + 1)]
    svc = service(factory, clock, {FPT: fake_scraper(FPT, items)})

    result = await svc.search("loa", price_min=2_000_000, price_max=2_400_000, limit_per_site=2)

    assert [item.price for item in result.items] == [2_000_000, 2_100_000]


# ---- TTL 1 giờ cho kết quả rỗng ---------------------------------------------------------------
async def test_an_empty_entry_exactly_one_hour_old_is_still_served_from_cache(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})
    await svc.search("loa")

    clock.advance(hours=1)
    result = await svc.search("loa")

    assert len(log) == 1 and result.from_cache and result.sites_searched == [GEARVN]


async def test_an_empty_entry_one_second_past_the_hour_is_searched_again(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})
    await svc.search("loa")

    clock.advance(hours=1, seconds=1)
    result = await svc.search("loa")

    assert len(log) == 2 and not result.from_cache


async def test_a_still_empty_research_restarts_the_one_hour_window(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})
    await svc.search("loa")
    clock.advance(minutes=61)
    await svc.search("loa")  # tìm lại, vẫn rỗng, ghi created_at mới
    clock.advance(minutes=59)
    await svc.search("loa")
    assert len(log) == 2

    clock.advance(minutes=2)
    await svc.search("loa")

    assert len(log) == 3


async def test_a_stale_empty_entry_is_replaced_by_results_that_keep_the_full_ttl(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    empty = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})
    full = service(
        factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 400_000)], log=log)}
    )
    await empty.search("loa")
    clock.advance(hours=2)
    found = await full.search("loa")
    clock.advance(hours=5, minutes=59)
    again = await full.search("loa")

    assert [item.price for item in found.items] == [400_000]
    assert len(log) == 2 and again.from_cache and len(again.items) == 1


async def test_only_the_site_with_a_stale_empty_entry_is_searched_again(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(
        factory,
        clock,
        {
            GEARVN: fake_scraper(GEARVN, [], log=log),
            FPT: fake_scraper(FPT, [listing(FPT, 1, 300_000)], log=log),
        },
    )
    await svc.search("loa")
    clock.advance(hours=2)

    result = await svc.search("loa")

    assert sorted(log) == ["fptshop:loa:24", "gearvn:loa:24", "gearvn:loa:24"]
    assert not result.from_cache


# ---- purge_expired ----------------------------------------------------------------------------
async def test_purge_keeps_an_entry_exactly_at_the_cutoff_and_removes_one_second_older(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {}, ttl_hours=6)
    repo = LiveSearchCacheRepository(db_session)
    cutoff = clock() - BLOCK_COOLDOWN
    repo.put(cache_key(GEARVN, "đúng ngưỡng"), [], now=cutoff)
    repo.put(cache_key(GEARVN, "cũ hơn 1 giây"), [], now=cutoff - timedelta(seconds=1))
    db_session.flush()

    removed = await svc.purge_expired()

    assert removed == 1
    assert _keys(db_session) == [cache_key(GEARVN, "đúng ngưỡng")]


async def test_purge_follows_a_ttl_longer_than_the_block_cooldown(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {}, ttl_hours=48)
    repo = LiveSearchCacheRepository(db_session)
    repo.put(cache_key(GEARVN, "30 giờ"), [], now=clock() - timedelta(hours=30))
    repo.put(cache_key(GEARVN, "49 giờ"), [], now=clock() - timedelta(hours=49))
    db_session.flush()

    removed = await svc.purge_expired()

    assert removed == 1 and _keys(db_session) == [cache_key(GEARVN, "30 giờ")]


async def test_purge_removes_a_block_marker_once_its_cooldown_is_over(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {}, ttl_hours=6)
    repo = LiveSearchCacheRepository(db_session)
    repo.put(blocked_key(GEARVN), [{"reason": "x"}], now=clock() - timedelta(hours=25))
    repo.put(blocked_key(FPT), [{"reason": "x"}], now=clock() - timedelta(hours=23))
    db_session.flush()

    assert await svc.purge_expired() == 1
    assert _keys(db_session) == [blocked_key(FPT)]


async def test_purge_on_an_empty_table_and_a_second_purge_remove_nothing(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {}, ttl_hours=6)
    assert await svc.purge_expired() == 0

    LiveSearchCacheRepository(db_session).put(
        cache_key(FPT, "cũ"), [], now=clock() - timedelta(days=3)
    )
    db_session.flush()

    assert await svc.purge_expired() == 1
    assert await svc.purge_expired() == 0
