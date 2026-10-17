from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.repositories.price_alerts import PriceAlertRepository
from app.db.repositories.products import ProductRepository
from app.domain.enums import AlertChannel, AlertStatus
from tests.factories import make_product

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _product_id(session: Session) -> int:
    product = ProductRepository(session).add(make_product())
    assert product.id is not None
    return product.id


def test_create_makes_an_active_alert(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)

    alert = repo.create(product_id, 25_000_000, AlertChannel.email, "mock@example.com", now=T0)

    assert alert.id is not None
    assert (alert.product_id, alert.target_price, alert.channel) == (
        product_id,
        25_000_000,
        AlertChannel.email,
    )
    assert (alert.destination, alert.status, alert.created_at) == (
        "mock@example.com",
        AlertStatus.active,
        T0,
    )
    assert (alert.last_notified_price, alert.last_notified_at) == (None, None)
    assert repo.get(alert.id) is alert
    assert repo.get(999_999_999) is None


def test_create_rejects_non_positive_target_price(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.create(_product_id(db_session), 0, AlertChannel.email, "mock@example.com")


def test_list_all_filters_by_status_newest_first(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    old = repo.create(product_id, 1, AlertChannel.email, "a@example.com", now=T0)
    new = repo.create(product_id, 2, AlertChannel.telegram, "123", now=T0 + timedelta(hours=1))
    repo.set_status(old, AlertStatus.paused)

    assert repo.list_all() == [new, old]
    assert repo.list_all(status=AlertStatus.active) == [new]
    assert repo.list_all(status=AlertStatus.paused) == [old]
    assert repo.list_all(status=AlertStatus.triggered) == []


def test_list_for_products_returns_live_alerts_of_the_given_products(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    first, second, third = (_product_id(db_session) for _ in range(3))
    active = repo.create(first, 1, AlertChannel.email, "a@example.com")
    triggered = repo.mark_notified(repo.create(first, 2, AlertChannel.email, "b@example.com"), 1)
    repo.set_status(repo.create(first, 3, AlertChannel.email, "c@example.com"), AlertStatus.paused)
    other = repo.create(second, 4, AlertChannel.email, "d@example.com")
    repo.create(third, 5, AlertChannel.email, "e@example.com")

    assert repo.list_for_products([first, second]) == [active, triggered, other]
    assert repo.list_for_products([first], statuses=(AlertStatus.paused,))[0].target_price == 3
    assert repo.list_for_products([]) == []


def test_find_live_matches_product_channel_destination_and_ignores_paused(
    db_session: Session,
) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    alert = repo.create(product_id, 1, AlertChannel.email, "a@example.com")

    assert repo.find_live(product_id, AlertChannel.email, "a@example.com") is alert
    assert repo.find_live(product_id, AlertChannel.telegram, "a@example.com") is None
    assert repo.find_live(product_id, AlertChannel.email, "x@example.com") is None
    assert repo.find_live(product_id + 1, AlertChannel.email, "a@example.com") is None

    repo.set_status(alert, AlertStatus.paused)
    assert repo.find_live(product_id, AlertChannel.email, "a@example.com") is None
    repo.mark_notified(alert, 20_000_000)
    assert repo.find_live(product_id, AlertChannel.email, "a@example.com") is alert


def test_mark_notified_records_price_time_and_triggers(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 25_000_000, AlertChannel.email, "a@example.com")
    when = T0 + timedelta(days=1)

    repo.mark_notified(alert, 24_000_000, now=when)
    db_session.expire(alert)

    assert alert.status == AlertStatus.triggered
    assert alert.last_notified_price == 24_000_000
    assert alert.last_notified_at == when


def test_set_target_price_and_delete(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 25_000_000, AlertChannel.email, "a@example.com")

    repo.set_target_price(alert, 22_000_000)
    assert alert.target_price == 22_000_000

    repo.delete(alert)
    assert repo.list_all() == []
