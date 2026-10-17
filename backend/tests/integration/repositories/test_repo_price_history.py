from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.db.models import Offer
from app.db.repositories.price_history import (
    HEARTBEAT_INTERVAL,
    PriceHistoryRepository,
    SnapshotResult,
)
from app.domain.enums import PriceType, SiteKey, StockStatus
from tests.factories import make_offer, make_product

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _offer(session: Session, product_id: int | None = None, **overrides: object) -> Offer:
    if product_id is None:
        product = make_product()
        session.add(product)
        session.flush()
        product_id = product.id
    assert product_id is not None
    offer = make_offer(product_id, **overrides)
    session.add(offer)
    session.flush()
    return offer


def test_first_snapshot_adds_a_row_with_the_offer_values(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(
        db_session, price=20_000_000, price_type=PriceType.sale, stock_status=StockStatus.in_stock
    )

    result = repo.record_snapshot(offer, now=T0)

    assert result == SnapshotResult(
        added=True, reason="first", previous_price=None, price_changed=False
    )
    rows = repo.list_for_offer(offer.id)  # type: ignore[arg-type]
    assert len(rows) == 1
    assert (rows[0].price, rows[0].price_type, rows[0].stock_status, rows[0].scraped_at) == (
        20_000_000,
        PriceType.sale,
        StockStatus.in_stock,
        T0,
    )


def test_unchanged_snapshot_within_24_hours_adds_nothing(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)

    result = repo.record_snapshot(offer, now=T0 + timedelta(hours=23, minutes=59))

    assert result == SnapshotResult(
        added=False, reason=None, previous_price=27_490_000, price_changed=False
    )
    assert len(repo.list_for_offer(offer.id)) == 1  # type: ignore[arg-type]


def test_unchanged_snapshot_at_exactly_24_hours_adds_nothing(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)

    result = repo.record_snapshot(offer, now=T0 + HEARTBEAT_INTERVAL)

    assert result.added is False


def test_unchanged_snapshot_older_than_24_hours_adds_a_heartbeat_row(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)

    later = T0 + HEARTBEAT_INTERVAL + timedelta(seconds=1)
    result = repo.record_snapshot(offer, now=later)

    assert result == SnapshotResult(
        added=True, reason="heartbeat", previous_price=27_490_000, price_changed=False
    )
    assert [row.scraped_at for row in repo.list_for_offer(offer.id)] == [T0, later]  # type: ignore[arg-type]


def test_heartbeat_is_measured_from_the_latest_row_not_the_first(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)
    repo.record_snapshot(offer, now=T0 + timedelta(hours=25))

    result = repo.record_snapshot(offer, now=T0 + timedelta(hours=26))

    assert result.added is False


def test_price_change_adds_a_row_and_reports_previous_price(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=27_490_000)
    repo.record_snapshot(offer, now=T0)
    offer.price = 25_990_000
    db_session.flush()

    result = repo.record_snapshot(offer, now=T0 + timedelta(minutes=10))

    assert result == SnapshotResult(
        added=True, reason="changed", previous_price=27_490_000, price_changed=True
    )
    assert [row.price for row in repo.list_for_offer(offer.id)] == [27_490_000, 25_990_000]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "new_value"),
    [("price_type", PriceType.flash), ("stock_status", StockStatus.out_of_stock)],
)
def test_type_or_stock_change_adds_a_row_but_is_not_a_price_change(
    db_session: Session, field: str, new_value: object
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    repo.record_snapshot(offer, now=T0)
    setattr(offer, field, new_value)
    db_session.flush()

    result = repo.record_snapshot(offer, now=T0 + timedelta(minutes=10))

    assert result.added is True
    assert result.reason == "changed"
    assert result.price_changed is False


def test_snapshot_compares_with_latest_history_row_not_with_offer_state(
    db_session: Session,
) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=100_000)
    repo.record_snapshot(offer, now=T0)
    offer.price = 90_000
    repo.record_snapshot(offer, now=T0 + timedelta(hours=1))
    offer.price = 100_000  # quay lại giá đầu: so với dòng 90_000 nên vẫn là thay đổi
    db_session.flush()

    result = repo.record_snapshot(offer, now=T0 + timedelta(hours=2))

    assert result.added is True
    assert result.previous_price == 90_000


def test_snapshot_requires_a_saved_offer() -> None:
    repo = PriceHistoryRepository(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        repo.record_snapshot(make_offer(1))


def test_latest_returns_the_most_recent_row(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session)
    assert repo.latest(offer.id) is None  # type: ignore[arg-type]
    repo.record_snapshot(offer, now=T0)
    offer.price = 1
    repo.record_snapshot(offer, now=T0 + timedelta(hours=1))

    latest = repo.latest(offer.id)  # type: ignore[arg-type]

    assert latest is not None
    assert latest.price == 1


def test_list_for_offer_filters_by_since_and_orders_oldest_first(db_session: Session) -> None:
    repo = PriceHistoryRepository(db_session)
    offer = _offer(db_session, price=1)
    for hours, price in [(0, 1), (30, 2), (60, 3)]:
        offer.price = price
        repo.record_snapshot(offer, now=T0 + timedelta(hours=hours))

    assert [row.price for row in repo.list_for_offer(offer.id)] == [1, 2, 3]  # type: ignore[arg-type]
    since = T0 + timedelta(hours=30)
    assert [row.price for row in repo.list_for_offer(offer.id, since=since)] == [2, 3]  # type: ignore[arg-type]


def test_series_for_product_groups_by_site_then_time_and_scopes_to_the_product(
    db_session: Session,
) -> None:
    repo = PriceHistoryRepository(db_session)
    product = make_product()
    other_product = make_product()
    db_session.add_all([product, other_product])
    db_session.flush()
    gear = _offer(db_session, product.id, site=SiteKey.gearvn, price=10)
    mock = _offer(db_session, product.id, site=SiteKey.mockshop, price=30)
    other = _offer(db_session, other_product.id, price=99)
    for hours in (0, 30):
        repo.record_snapshot(mock, now=T0 + timedelta(hours=hours))
        gear.price += 1
        repo.record_snapshot(gear, now=T0 + timedelta(hours=hours + 1))
    repo.record_snapshot(other, now=T0)

    series = repo.series_for_product(product.id)  # type: ignore[arg-type]

    assert [(p.site, p.price) for p in series] == [
        (SiteKey.gearvn, 11),
        (SiteKey.gearvn, 12),
        (SiteKey.mockshop, 30),
        (SiteKey.mockshop, 30),
    ]
    assert series[0].offer_id == gear.id
    since = T0 + timedelta(hours=10)
    assert len(repo.series_for_product(product.id, since=since)) == 2  # type: ignore[arg-type]
    assert repo.series_for_product(999_999_999) == []
