"""T10.4: lọc giá trên đủ một trang kết quả, TTL ngắn cho kết quả rỗng, dọn cache cũ."""

from collections.abc import Callable

import pytest
from sqlmodel import Session, select

from app.db.models import LiveSearchCache
from app.db.repositories import LiveSearchCacheRepository
from app.scrapers.pipeline import BLOCK_COOLDOWN
from app.services.live_search_service import (
    EMPTY_CACHE_TTL,
    MAX_PER_SITE,
    blocked_key,
    cache_key,
)
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


async def test_a_tight_price_cap_finds_cards_after_the_tenth(
    factory: Callable[[], Session], clock: Clock
) -> None:
    # 24 thẻ (một trang FPT Shop); chỉ thẻ 20–24 rẻ hơn 1 triệu.
    items = [listing(FPT, n, 2_000_000 if n < 20 else 900_000) for n in range(1, MAX_PER_SITE + 1)]
    svc = service(factory, clock, {FPT: fake_scraper(FPT, items)})

    result = await svc.search("loa", price_max=1_000_000, limit_per_site=3)

    assert [item.price for item in result.items] == [900_000] * 3
    assert str(result.items[0].url).endswith("/p20")


async def test_an_empty_result_is_searched_again_after_one_hour(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(factory, clock, {GEARVN: fake_scraper(GEARVN, [], log=log)})

    await svc.search("loa")
    clock.advance(minutes=59)
    await svc.search("loa")
    assert len(log) == 1  # còn trong 1 giờ: dùng cache rỗng
    clock.advance(minutes=2)
    await svc.search("loa")

    assert len(log) == 2


async def test_a_non_empty_result_keeps_the_full_ttl(
    factory: Callable[[], Session], clock: Clock
) -> None:
    log: list[str] = []
    svc = service(
        factory, clock, {GEARVN: fake_scraper(GEARVN, [listing(GEARVN, 1, 500_000)], log=log)}
    )

    await svc.search("loa")
    clock.advance(hours=5, minutes=59)
    result = await svc.search("loa")

    assert len(log) == 1 and result.from_cache
    assert EMPTY_CACHE_TTL.total_seconds() == 3600


async def test_purge_removes_only_entries_older_than_the_ttl_and_the_block_cooldown(
    db_session: Session, factory: Callable[[], Session], clock: Clock
) -> None:
    svc = service(factory, clock, {}, ttl_hours=6)
    repo = LiveSearchCacheRepository(db_session)
    repo.put(cache_key(GEARVN, "cũ"), [], now=clock() - BLOCK_COOLDOWN * 2)
    repo.put(blocked_key(GEARVN), [{"reason": "x"}], now=clock() - BLOCK_COOLDOWN / 2)
    repo.put(cache_key(FPT, "mới"), [], now=clock())
    db_session.flush()

    removed = await svc.purge_expired()

    assert removed == 1  # giữ được 24 giờ nghỉ chặn dù TTL tìm kiếm chỉ 6 giờ
    keys = sorted(row.cache_key for row in db_session.exec(select(LiveSearchCache)).all())
    assert keys == sorted([blocked_key(GEARVN), cache_key(FPT, "mới")])
