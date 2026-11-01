"""QA M1: test biên cho hai bảng cache (hết hạn đúng biên, kết quả rỗng, ghi đè)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.db.repositories.caches import LiveSearchCacheRepository, LlmExtractionCacheRepository
from app.domain.enums import Category

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
TTL = timedelta(hours=6)
TICK = timedelta(microseconds=1)


@pytest.mark.parametrize(
    ("age", "fresh"),
    [
        pytest.param(timedelta(0), True, id="just-created"),
        pytest.param(TTL - TICK, True, id="1us-before-expiry"),
        pytest.param(TTL, True, id="exactly-max-age"),
        pytest.param(TTL + TICK, False, id="1us-after-expiry"),
        pytest.param(-timedelta(hours=1), True, id="clock-went-backwards"),
    ],
)
def test_live_search_cache_expiry_boundary(
    db_session: Session, age: timedelta, fresh: bool
) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("key", [{"url": "https://mock.example/p/1"}], now=T0)

    entry = repo.get("key", max_age=TTL, now=T0 + age)

    assert (entry is not None) is fresh


def test_live_search_cache_zero_max_age_only_accepts_the_same_instant(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("key", [], now=T0)

    assert repo.get("key", max_age=timedelta(0), now=T0) is not None
    assert repo.get("key", max_age=timedelta(0), now=T0 + TICK) is None


def test_live_search_cache_keeps_an_empty_result_list_distinct_from_a_miss(
    db_session: Session,
) -> None:
    repo = LiveSearchCacheRepository(db_session)
    assert repo.get("none", max_age=TTL, now=T0) is None

    repo.put("none", [], now=T0)
    entry = repo.get("none", max_age=TTL, now=T0)

    assert entry is not None and entry.results == []


def test_live_search_cache_round_trips_vietnamese_results_in_order(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    results = [
        {"title": "Chuột không dây Đẹp", "price": 499_000, "tags": ["gaming", "không dây"]},
        {"title": "Bàn phím cơ ⌨️", "price": None, "nested": {"a": [1, {"b": 2}]}},
    ]
    repo.put("vi", results, now=T0)
    db_session.expire_all()

    entry = repo.get("vi", max_age=TTL, now=T0)

    assert entry is not None and entry.results == results


def test_live_search_cache_keys_are_case_and_whitespace_sensitive(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("Laptop 20tr", [{"n": 1}], now=T0)

    assert repo.get("laptop 20tr", max_age=TTL, now=T0) is None
    assert repo.get("Laptop 20tr ", max_age=TTL, now=T0) is None
    assert repo.get("Laptop 20tr", max_age=TTL, now=T0) is not None


def test_purge_older_than_keeps_entry_created_exactly_at_cutoff(db_session: Session) -> None:
    repo = LiveSearchCacheRepository(db_session)
    repo.put("old", [], now=T0 - TICK)
    repo.put("edge", [], now=T0)
    repo.put("new", [], now=T0 + TICK)

    removed = repo.purge_older_than(T0)

    assert removed == 1
    for key, expected in (("old", False), ("edge", True), ("new", True)):
        assert (repo.get(key, max_age=timedelta(days=365), now=T0) is not None) is expected
    assert repo.purge_older_than(T0) == 0


def test_purge_on_empty_table_returns_zero(db_session: Session) -> None:
    assert LiveSearchCacheRepository(db_session).purge_older_than(T0) == 0


def test_llm_cache_stores_empty_and_nested_results(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)
    nested = {"gpu_model": "RTX 4060", "tags": [], "extra": {"ghi chú": None}}

    repo.put("e" * 64, Category.laptop, {}, "m", now=T0)
    repo.put("f" * 64, Category.laptop, nested, "m", now=T0)
    db_session.expire_all()

    first, second = repo.get("e" * 64), repo.get("f" * 64)
    assert first is not None and first.result == {}
    assert second is not None and second.result == nested


def test_llm_cache_hash_keys_are_case_sensitive(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)
    repo.put("a" * 64, Category.laptop, {"ram_gb": 8}, "m", now=T0)
    repo.put("A" * 64, Category.laptop, {"ram_gb": 16}, "m", now=T0)

    lower, upper = repo.get("a" * 64), repo.get("A" * 64)
    assert lower is not None and upper is not None
    assert (lower.result, upper.result) == ({"ram_gb": 8}, {"ram_gb": 16})


def test_llm_cache_put_on_conflict_can_change_the_category_and_model(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)
    repo.put("a" * 64, Category.laptop, {"x": 1}, "m1", now=T0)

    entry = repo.put("a" * 64, Category.mouse, {"x": 2}, "m2", now=T0 + timedelta(days=1))

    assert (entry.category, entry.result, entry.model, entry.created_at) == (
        Category.mouse,
        {"x": 2},
        "m2",
        T0 + timedelta(days=1),
    )


def test_llm_cache_rejects_a_hash_longer_than_64_characters(db_session: Session) -> None:
    repo = LlmExtractionCacheRepository(db_session)

    with pytest.raises(DBAPIError), db_session.begin_nested():
        repo.put("a" * 65, Category.laptop, {}, "m", now=T0)
