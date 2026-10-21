"""QA M1: test biên cho `PriceAlertRepository` (cảnh báo trùng, trạng thái, giá 0)."""

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


@pytest.mark.parametrize(
    ("status", "live"),
    [
        (AlertStatus.active, True),
        (AlertStatus.triggered, True),
        (AlertStatus.paused, False),
    ],
)
def test_find_live_depends_only_on_status(
    db_session: Session, status: AlertStatus, live: bool
) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    alert = repo.create(product_id, 20_000_000, AlertChannel.email, "mock@example.com")
    repo.set_status(alert, status)

    found = repo.find_live(product_id, AlertChannel.email, "mock@example.com")

    assert (found is alert) is live


def test_find_live_does_not_cross_product_channel_or_destination(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    product_id, other_id = _product_id(db_session), _product_id(db_session)
    repo.create(product_id, 20_000_000, AlertChannel.telegram, "12345")

    assert repo.find_live(other_id, AlertChannel.telegram, "12345") is None
    assert repo.find_live(product_id, AlertChannel.email, "12345") is None
    assert repo.find_live(product_id, AlertChannel.telegram, "123456") is None
    assert repo.find_live(product_id, AlertChannel.telegram, "") is None


def test_find_live_returns_the_oldest_when_duplicates_already_exist(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    first = repo.create(product_id, 20_000_000, AlertChannel.email, "mock@example.com")
    repo.create(product_id, 19_000_000, AlertChannel.email, "mock@example.com")

    assert repo.find_live(product_id, AlertChannel.email, "mock@example.com") is first
    assert len(repo.list_for_products([product_id])) == 2


@pytest.mark.parametrize("variant", ["MOCK@EXAMPLE.COM", "  mock@example.com ", "Mock@Example.com"])
def test_find_live_treats_email_variants_of_one_mailbox_as_the_same_destination(
    db_session: Session, variant: str
) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    alert = repo.create(product_id, 20_000_000, AlertChannel.email, "mock@example.com")

    assert repo.find_live(product_id, AlertChannel.email, variant) is alert


def test_mark_notified_twice_keeps_the_latest_price_and_time(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 20_000_000, AlertChannel.email, "m@example.com")

    repo.mark_notified(alert, 19_000_000, now=T0)
    repo.mark_notified(alert, 18_000_000, now=T0 + timedelta(hours=3))

    assert (alert.status, alert.last_notified_price, alert.last_notified_at) == (
        AlertStatus.triggered,
        18_000_000,
        T0 + timedelta(hours=3),
    )


def test_mark_notified_with_zero_price_stores_zero_not_null(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 20_000_000, AlertChannel.email, "m@example.com")

    repo.mark_notified(alert, 0, now=T0)
    db_session.expire(alert)

    assert alert.last_notified_price == 0


@pytest.mark.parametrize("price", [-1, 0])
def test_set_target_price_rejects_non_positive_prices(db_session: Session, price: int) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 20_000_000, AlertChannel.email, "m@example.com")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.set_target_price(alert, price)


def test_mark_notified_rejects_negative_price(db_session: Session) -> None:
    repo = PriceAlertRepository(db_session)
    alert = repo.create(_product_id(db_session), 20_000_000, AlertChannel.email, "m@example.com")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.mark_notified(alert, -1, now=T0)


def test_list_all_orders_alerts_created_at_the_same_instant_by_id_desc(
    db_session: Session,
) -> None:
    repo = PriceAlertRepository(db_session)
    product_id = _product_id(db_session)
    first = repo.create(product_id, 1_000_000, AlertChannel.email, "a@example.com", now=T0)
    second = repo.create(product_id, 1_000_000, AlertChannel.email, "b@example.com", now=T0)

    assert repo.list_all() == [second, first]
