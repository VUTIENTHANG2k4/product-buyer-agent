"""QA M1: test biên cho `PriceHistoryRepository.record_snapshot` (docs/04 §3, luật 24 giờ)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.db.models import Offer
from app.db.repositories.price_history import (
    HEARTBEAT_INTERVAL,
    PriceHistoryRepository,
    SnapshotResult,
)
from app.domain.enums import PriceType, StockStatus
from tests.factories import make_offer, make_product

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)


def _offer(session: Session, **overrides: object) -> Offer:
    product = make_product()
    session.add(product)
    session.flush()
    assert product.id is not None
    offer = make_offer(product.id, **overrides)
    session.add(offer)
    session.flush()
    return offer


def _change(session: Session, offer: Offer, **values: object) -> None:
    for name, value in values.items():
        setattr(offer, name, value)
    session.flush()


@pytest.mark.parametrize(
    ("elapsed", "added"),
    [
        pytest.param(HEARTBEAT_INTERVAL - TICK, False, id="1us-before-24h"),
        pytest.param(HEARTBEAT_INTERVAL, False, id="exactly-24h"),
        pytest.param(HEARTBEAT_INTERVAL + TICK, True, id="1us-after-24h"),
        pytest.param(timedelta(0), False, id="same-instant"),
        pytest.param(-timedelta(hours=48), False, id="clock-went-backwards"),
    ],
)
def test_heartbeat_boundary_is_strictly_longer_than_24_hours(
    db_session: Session, elapsed: timedelta, added: bool
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)

    result = repo.record_snapshot(offer, now=T0 + elapsed)

    assert result.added is added
    assert result.reason == ("heartbeat" if added else None)
    assert result.price_changed is False
    assert len(repo.list_for_offer(offer.id)) == (2 if added else 1)  # type: ignore[arg-type]


def test_price_going_up_then_back_down_adds_a_row_each_time_with_the_right_previous_price(
    db_session: Session,
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=20_000_000)
    repo.record_snapshot(offer, now=T0)

    _change(db_session, offer, price=22_000_000)
    up = repo.record_snapshot(offer, now=T0 + timedelta(minutes=10))
    _change(db_session, offer, price=20_000_000)
    down = repo.record_snapshot(offer, now=T0 + timedelta(minutes=20))
    same = repo.record_snapshot(offer, now=T0 + timedelta(minutes=30))

    assert up == SnapshotResult(True, "changed", 20_000_000, True)
    assert down == SnapshotResult(True, "changed", 22_000_000, True)
    assert same == SnapshotResult(False, None, 20_000_000, False)
    assert [row.price for row in repo.list_for_offer(offer.id)] == [  # type: ignore[arg-type]
        20_000_000,
        22_000_000,
        20_000_000,
    ]


def test_rows_with_identical_timestamps_are_ordered_by_insertion(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=100)
    repo.record_snapshot(offer, now=T0)

    results = []
    for price in (200, 300, 200):
        _change(db_session, offer, price=price)
        results.append(repo.record_snapshot(offer, now=T0))

    assert [r.previous_price for r in results] == [100, 200, 300]
    latest = repo.latest(offer.id)  # type: ignore[arg-type]
    assert latest is not None and latest.price == 200
    assert [row.price for row in repo.list_for_offer(offer.id)] == [100, 200, 300, 200]  # type: ignore[arg-type]


def test_zero_price_is_a_real_previous_price_not_a_missing_one(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=0)
    first = repo.record_snapshot(offer, now=T0)

    _change(db_session, offer, price=5_000_000)
    second = repo.record_snapshot(offer, now=T0 + timedelta(hours=1))
    _change(db_session, offer, price=0)
    third = repo.record_snapshot(offer, now=T0 + timedelta(hours=2))

    assert first.previous_price is None and first.price_changed is False
    assert second == SnapshotResult(True, "changed", 0, True)
    assert third == SnapshotResult(True, "changed", 5_000_000, True)


def test_price_type_and_stock_change_together_add_one_row_and_no_price_change(
    db_session: Session,
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price_type=PriceType.regular, stock_status=StockStatus.in_stock)
    repo.record_snapshot(offer, now=T0)

    _change(db_session, offer, price_type=PriceType.flash, stock_status=StockStatus.out_of_stock)
    result = repo.record_snapshot(offer, now=T0 + timedelta(minutes=5))

    assert result == SnapshotResult(True, "changed", 27_490_000, False)
    rows = repo.list_for_offer(offer.id)  # type: ignore[arg-type]
    assert [(r.price_type, r.stock_status) for r in rows] == [
        (PriceType.regular, StockStatus.in_stock),
        (PriceType.flash, StockStatus.out_of_stock),
    ]


def test_price_and_type_change_in_the_same_snapshot_counts_as_a_price_change(
    db_session: Session,
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=30_000_000, price_type=PriceType.regular)
    repo.record_snapshot(offer, now=T0)

    _change(db_session, offer, price=24_000_000, price_type=PriceType.flash)
    result = repo.record_snapshot(offer, now=T0 + timedelta(hours=1))

    assert result == SnapshotResult(True, "changed", 30_000_000, True)


def test_each_heartbeat_is_measured_from_the_previous_heartbeat(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)

    heartbeats = [
        repo.record_snapshot(offer, now=T0 + timedelta(hours=hours)).reason
        for hours in (25, 49, 50, 73, 74.5, 100)
    ]

    assert heartbeats == ["heartbeat", None, "heartbeat", None, "heartbeat", "heartbeat"]


def test_list_price_alone_changing_does_not_add_history_since_only_price_is_stored(
    db_session: Session,
) -> None:
    """Ghi nhận: lịch sử chỉ theo `price`, `price_type`, `stock_status` (docs/04 §3)."""
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=25_000_000, list_price=30_000_000, price_type=PriceType.member)
    repo.record_snapshot(offer, now=T0)

    _change(db_session, offer, list_price=28_000_000)
    result = repo.record_snapshot(offer, now=T0 + timedelta(minutes=1))

    assert result.added is False
