from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.db.repositories.caches import LiveSearchCacheRepository, LlmExtractionCacheRepository
from app.domain.enums import Category

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
HASH = "a" * 64


def test_llm_cache_put_then_get(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)
    assert repo.get(HASH) is None

    entry = repo.put(HASH, Category.laptop, {"ram_gb": 16}, "fake-model", now=T0)

    assert repo.get(HASH) is entry
    assert (entry.category, entry.result, entry.model, entry.created_at) == (
        Category.laptop,
        {"ram_gb": 16},
        "fake-model",
        T0,
    )


def test_llm_cache_put_same_hash_replaces_the_entry(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)
    first = repo.put(HASH, Category.laptop, {"ram_gb": 8}, "m1", now=T0)

    second = repo.put(HASH, Category.mouse, {"dpi_max": 1600}, "m2", now=T0 + timedelta(days=1))

    assert second is first
    assert (second.category, second.result, second.model) == (
        Category.mouse,
        {"dpi_max": 1600},
        "m2",
    )
    assert second.created_at == T0 + timedelta(days=1)


def test_live_search_cache_returns_fresh_entries_only(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    ttl = timedelta(hours=6)
    repo.put("loa bluetooth", [{"site": "gearvn", "price": 900_000}], now=T0)

    fresh = repo.get("loa bluetooth", max_age=ttl, now=T0 + timedelta(hours=5, minutes=59))
    at_limit = repo.get("loa bluetooth", max_age=ttl, now=T0 + ttl)
    stale = repo.get("loa bluetooth", max_age=ttl, now=T0 + ttl + timedelta(seconds=1))

    assert fresh is not None and fresh.results == [{"site": "gearvn", "price": 900_000}]
    assert at_limit is not None
    assert stale is None
    assert repo.get("khác", max_age=ttl, now=T0) is None


def test_live_search_cache_put_refreshes_results_and_created_at(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("key", [{"n": 1}], now=T0)

    entry = repo.put("key", [{"n": 2}, {"n": 3}], now=T0 + timedelta(hours=7))

    assert entry.results == [{"n": 2}, {"n": 3}]
    assert entry.created_at == T0 + timedelta(hours=7)
    assert repo.get("key", max_age=timedelta(hours=6), now=T0 + timedelta(hours=8)) is entry


def test_live_search_cache_purge_older_than_removes_only_old_entries(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("old", [], now=T0)
    repo.put("edge", [], now=T0 + timedelta(hours=1))
    repo.put("new", [], now=T0 + timedelta(hours=2))

    removed = repo.purge_older_than(T0 + timedelta(hours=1))

    assert removed == 1
    day = timedelta(days=30)
    assert repo.get("old", max_age=day, now=T0) is None
    assert repo.get("edge", max_age=day, now=T0) is not None
    assert repo.get("new", max_age=day, now=T0) is not None
    assert repo.purge_older_than(T0) == 0
