"""T6.2: AlertService (gồm ca QA M1 về chuẩn hóa email nhận cảnh báo)."""

import pytest
from sqlmodel import Session

from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel, AlertStatus, StockStatus
from app.domain.errors import AlertNotFound, DuplicateAlert, ProductNotFound, ValidationFailed
from app.services.alert_service import AlertService
from tests.service_support import NOW, add_offer, add_product, clock, make_settings


def service(session: Session, **settings: object) -> AlertService:
    return AlertService(session, make_settings(**settings), now=clock)


def test_create_uses_configured_default_channel_and_email(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)

    alert = service(db_session, alert_default_email=" Mock@Example.com ").create(
        AlertCreate(product_id=product.id or 0, target_price=25_000_000)
    )

    assert (alert.channel, alert.destination, alert.status) == (
        AlertChannel.email,
        "mock@example.com",
        AlertStatus.active,
    )
    assert (alert.target_price, alert.current_best_price, alert.created_at) == (
        25_000_000,
        27_000_000,
        NOW,
    )
    assert alert.product_name == product.canonical_name


def test_telegram_default_uses_chat_id_and_keeps_its_case(db_session: Session) -> None:
    product = add_product(db_session)

    alert = service(
        db_session, alert_default_channel="telegram", telegram_chat_id=" @MockChat "
    ).create(AlertCreate(product_id=product.id or 0, target_price=1))

    assert (alert.channel, alert.destination) == (AlertChannel.telegram, "@MockChat")


def test_explicit_channel_and_destination_override_defaults(db_session: Session) -> None:
    product = add_product(db_session)

    alert = service(db_session).create(
        AlertCreate(
            product_id=product.id or 0,
            target_price=10,
            channel=AlertChannel.telegram,
            destination="12345",
        )
    )

    assert (alert.channel, alert.destination) == (AlertChannel.telegram, "12345")


def test_missing_default_destination_is_a_validation_error(db_session: Session) -> None:
    product = add_product(db_session)
    with pytest.raises(ValidationFailed, match="Chưa cấu hình") as caught:
        service(db_session, alert_default_email="").create(
            AlertCreate(product_id=product.id or 0, target_price=10)
        )
    assert caught.value.details == {"channel": "email"}


@pytest.mark.parametrize("email", ["khong-co-a-cong", "a@b", "a b@c.com", "@x.com"])
def test_invalid_email_is_rejected(db_session: Session, email: str) -> None:
    product = add_product(db_session)
    with pytest.raises(ValidationFailed, match="email"):
        service(db_session).create(
            AlertCreate(product_id=product.id or 0, target_price=10, destination=email)
        )


def test_same_mailbox_in_other_spelling_is_a_duplicate(db_session: Session) -> None:
    product = add_product(db_session)
    first = service(db_session).create(
        AlertCreate(
            product_id=product.id or 0, target_price=20_000_000, destination="mock@example.com"
        )
    )

    with pytest.raises(DuplicateAlert) as caught:
        service(db_session).create(
            AlertCreate(
                product_id=product.id or 0,
                target_price=20_000_000,
                destination="  MOCK@Example.COM ",
            )
        )
    assert caught.value.details == {"alert_id": first.alert_id}


def test_other_threshold_channel_or_destination_is_not_a_duplicate(db_session: Session) -> None:
    product = add_product(db_session)
    base = AlertCreate(product_id=product.id or 0, target_price=20_000_000)
    service(db_session).create(base)

    service(db_session).create(base.model_copy(update={"target_price": 19_000_000}))
    service(db_session).create(base.model_copy(update={"destination": "khac@example.com"}))
    service(db_session).create(
        base.model_copy(update={"channel": AlertChannel.telegram, "destination": "1"})
    )

    assert len(service(db_session).list_alerts()) == 4


def test_paused_alert_does_not_block_a_new_identical_one(db_session: Session) -> None:
    product = add_product(db_session)
    request = AlertCreate(product_id=product.id or 0, target_price=20_000_000)
    first = service(db_session).create(request)
    service(db_session).update(first.alert_id, status=AlertStatus.paused)

    second = service(db_session).create(request)

    assert second.alert_id != first.alert_id


def test_unknown_product_raises_product_not_found(db_session: Session) -> None:
    with pytest.raises(ProductNotFound):
        service(db_session).create(AlertCreate(product_id=999_999, target_price=10))


@pytest.mark.parametrize("price", [0, -5, 2**63])
def test_target_price_must_be_positive_and_fit_bigint(price: int) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic.ValidationError là ValueError
        AlertCreate(product_id=1, target_price=price)


def test_current_best_price_ignores_out_of_stock_offers(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=20_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, product, price=26_000_000)
    other = add_product(db_session)

    with_price = service(db_session).create(
        AlertCreate(product_id=product.id or 0, target_price=25_000_000)
    )
    without_offers = service(db_session).create(
        AlertCreate(product_id=other.id or 0, target_price=25_000_000)
    )

    assert with_price.current_best_price == 26_000_000
    assert without_offers.current_best_price is None


def test_list_alerts_filters_by_status_newest_first(db_session: Session) -> None:
    product = add_product(db_session)
    first = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))
    second = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=20))
    service(db_session).update(first.alert_id, status=AlertStatus.paused)

    assert [a.alert_id for a in service(db_session).list_alerts()] == [
        second.alert_id,
        first.alert_id,
    ]
    paused = service(db_session).list_alerts(AlertStatus.paused)
    assert [a.alert_id for a in paused] == [first.alert_id]


def test_update_changes_target_and_status_and_rejects_triggered(db_session: Session) -> None:
    product = add_product(db_session)
    alert = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))

    updated = service(db_session).update(alert.alert_id, target_price=99, status=AlertStatus.paused)
    assert (updated.target_price, updated.status) == (99, AlertStatus.paused)

    with pytest.raises(ValidationFailed):
        service(db_session).update(alert.alert_id, status=AlertStatus.triggered)
    with pytest.raises(ValidationFailed):
        service(db_session).update(alert.alert_id, target_price=0)


def test_get_delete_and_unknown_alert(db_session: Session) -> None:
    product = add_product(db_session)
    alert = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))

    assert service(db_session).get(alert.alert_id).alert_id == alert.alert_id
    service(db_session).delete(alert.alert_id)
    for call in (service(db_session).get, service(db_session).delete):
        with pytest.raises(AlertNotFound) as caught:
            call(alert.alert_id)
        assert caught.value.details == {"alert_id": alert.alert_id}


def test_update_validates_everything_before_writing_anything(db_session: Session) -> None:
    product = add_product(db_session)
    alert = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))

    with pytest.raises(ValidationFailed):
        service(db_session).update(alert.alert_id, target_price=5, status=AlertStatus.triggered)

    assert service(db_session).get(alert.alert_id).target_price == 10


def test_update_error_reports_the_rejected_value(db_session: Session) -> None:
    product = add_product(db_session)
    alert = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))

    with pytest.raises(ValidationFailed) as caught:
        service(db_session).update(alert.alert_id, target_price=2**63)

    assert caught.value.details == {"target_price": 2**63}


def test_update_to_a_threshold_another_alert_already_has_is_a_duplicate(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    first = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=10))
    second = service(db_session).create(AlertCreate(product_id=product.id or 0, target_price=20))

    with pytest.raises(DuplicateAlert) as caught:
        service(db_session).update(second.alert_id, target_price=10)

    assert caught.value.details == {"alert_id": first.alert_id}
    assert service(db_session).update(second.alert_id, target_price=20).target_price == 20
