"""QA "Chuẩn bị bảo vệ" (T11.4): biên của `prepare_price_drop`."""

import pytest
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.db.models import PriceAlert
from app.domain.enums import AlertChannel, AlertStatus
from app.normalize.price import MAX_PRICE_VND
from scripts.demo_price_drop import DemoPriceError, prepare_price_drop
from tests.integration.test_pipeline import NOW
from tests.service_support import add_offer, add_product


def _alerts(session: Session, product_id: int | None) -> list[PriceAlert]:
    return list(session.exec(select(PriceAlert).where(PriceAlert.product_id == product_id)).all())


def test_equal_cheapest_prices_are_broken_by_the_lowest_offer_id(db_session: Session) -> None:
    product = add_product(db_session)
    first = add_offer(db_session, product, price=14_180_000)
    add_offer(db_session, add_product(db_session), price=14_180_000)

    prepared = prepare_price_drop(db_session, now=NOW)

    assert prepared.offer_id == first.id


@pytest.mark.parametrize("price", [0, 1, 999, MAX_PRICE_VND])
@pytest.mark.parametrize("bump", [1, 15, 100])
def test_the_invariant_holds_for_extreme_prices_and_bumps(
    db_session: Session, price: int, bump: int
) -> None:
    add_offer(db_session, add_product(db_session), price=price)

    prepared = prepare_price_drop(db_session, bump_percent=bump, now=NOW)

    assert prepared.shop_price == price
    assert price < prepared.target_price < prepared.raised_price
    assert prepared.target_price > 0


def test_a_price_near_the_bigint_limit_fails_with_a_clear_error_or_works(
    db_session: Session,
) -> None:
    """Giá thật bị chặn ở MAX_PRICE_VND nên không xảy ra; ghi nhận hành vi để biết."""
    add_offer(db_session, add_product(db_session), price=2**63 - 5)

    try:
        with db_session.begin_nested():
            prepare_price_drop(db_session, now=NOW)
    except (DemoPriceError, DBAPIError, OverflowError, ValueError):
        return
    pytest.fail("giá gần cận BIGINT không thể nâng mà không báo lỗi")


@pytest.mark.parametrize(
    "email", ["Mock@Example.COM", "  mock@example.com  ", "MOCK@example.com\t"]
)
def test_email_case_and_whitespace_are_normalised_and_rerun_is_recognised(
    db_session: Session, email: str
) -> None:
    laptop = add_product(db_session)
    add_offer(db_session, laptop, price=15_000_000)
    first = prepare_price_drop(db_session, email=email, now=NOW)

    again = prepare_price_drop(db_session, email="mock@example.com", now=NOW)

    (alert,) = _alerts(db_session, laptop.id)
    assert alert.destination == "mock@example.com" and alert.channel is AlertChannel.email
    assert again.already_prepared and again.alert_id == first.alert_id


def test_a_new_round_keeps_alerts_of_other_recipients_and_other_products(
    db_session: Session,
) -> None:
    laptop = add_product(db_session)
    other = add_product(db_session)
    offer = add_offer(db_session, laptop, price=15_000_000)
    add_offer(db_session, other, price=40_000_000)
    kept_other_product = prepare_price_drop(db_session, offer_id=None, now=NOW)  # laptop rẻ nhất
    assert kept_other_product.product_id == laptop.id
    offer.price = 15_000_000  # mô phỏng một vòng đã xong: giá về

    prepare_price_drop(db_session, email="khac@example.com", now=NOW)
    # Cảnh báo của mock@example.com vẫn nguyên khi chạy cho người nhận khác.
    destinations = sorted(alert.destination for alert in _alerts(db_session, laptop.id))

    assert destinations == ["khac@example.com", "mock@example.com"]
    assert _alerts(db_session, other.id) == []


def test_a_triggered_alert_of_the_previous_round_is_replaced(db_session: Session) -> None:
    laptop = add_product(db_session)
    offer = add_offer(db_session, laptop, price=15_000_000)
    first = prepare_price_drop(db_session, now=NOW)
    (old,) = _alerts(db_session, laptop.id)
    old.status = AlertStatus.triggered
    db_session.add(old)
    offer.price = 15_000_000
    db_session.flush()

    second = prepare_price_drop(db_session, now=NOW)

    assert not second.already_prepared and second.alert_id != first.alert_id
    (alert,) = _alerts(db_session, laptop.id)
    assert alert.id == second.alert_id and alert.status is AlertStatus.active


def test_bug_prep_6_default_rerun_with_two_laptops_changes_nothing(db_session: Session) -> None:
    cheap = add_offer(db_session, add_product(db_session), price=14_180_000)
    next_cheapest = add_offer(db_session, add_product(db_session), price=14_880_000)
    first = prepare_price_drop(db_session, now=NOW)
    assert first.offer_id == cheap.id

    second = prepare_price_drop(db_session, now=NOW)  # không truyền --offer-id

    assert second.already_prepared and second.alert_id == first.alert_id
    assert next_cheapest.price == 14_880_000


def test_bug_prep_7_a_second_recipient_does_not_raise_the_price_again(db_session: Session) -> None:
    laptop = add_product(db_session)
    offer = add_offer(db_session, laptop, price=15_000_000)
    first = prepare_price_drop(db_session, offer_id=offer.id, now=NOW)

    second = prepare_price_drop(db_session, offer_id=offer.id, email="khac@example.com", now=NOW)

    assert offer.price == first.raised_price
    assert second.shop_price == 15_000_000
