"""T6.2: phần repository được mở rộng cho service (nhóm offer, chuẩn hóa tên/email, xóa ghi chú)."""

import unicodedata

from sqlalchemy import select
from sqlmodel import Session

from app.db.models import Offer
from app.db.repositories import (
    OfferRepository,
    PriceAlertRepository,
    ShoppingListRepository,
    effective_price,
    effective_price_of,
    normalize_destination,
    normalize_list_name,
)
from app.domain.enums import AlertChannel, PriceType
from tests.service_support import add_offer, add_product


def test_effective_price_of_matches_the_sql_expression(db_session: Session) -> None:
    product = add_product(db_session)
    cases = [
        {"price": 10, "list_price": None, "price_type": PriceType.regular},
        {"price": 10, "list_price": 20, "price_type": PriceType.sale},
        {"price": 10, "list_price": 20, "price_type": PriceType.member},
        {"price": 10, "list_price": None, "price_type": PriceType.member},
        {"price": 10, "list_price": 20, "price_type": PriceType.flash},
    ]
    offers = [add_offer(db_session, product, **case) for case in cases]

    rows = db_session.execute(select(Offer.id, effective_price())).all()
    in_sql = {offer_id: price for offer_id, price in rows}

    for offer in offers:
        assert effective_price_of(offer) == in_sql[offer.id]


def test_list_for_products_groups_cheapest_first_and_filters_inactive(db_session: Session) -> None:
    a, b, empty = add_product(db_session), add_product(db_session), add_product(db_session)
    dear = add_offer(db_session, a, price=30)
    cheap = add_offer(db_session, a, price=10)
    off = add_offer(db_session, a, price=5, is_active=False)
    only = add_offer(db_session, b, price=7)
    repo = OfferRepository(db_session)
    ids = [a.id or 0, b.id or 0, empty.id or 0]

    active = repo.list_for_products(ids)
    everything = repo.list_for_products(ids, active_only=False)

    assert active == {a.id: [cheap, dear], b.id: [only], empty.id: []}
    assert everything[a.id or 0] == [off, cheap, dear]
    assert repo.list_for_products([]) == {}


def test_alert_destination_is_normalized_on_create(db_session: Session) -> None:
    product = add_product(db_session)
    repo = PriceAlertRepository(db_session)

    email = repo.create(product.id or 0, 10, AlertChannel.email, "  Mock@Example.COM ")
    telegram = repo.create(product.id or 0, 10, AlertChannel.telegram, " @MockChat ")

    assert (email.destination, telegram.destination) == ("mock@example.com", "@MockChat")
    assert normalize_destination(AlertChannel.email, "A@B.c ") == "a@b.c"


def test_list_names_are_stored_and_looked_up_in_nfc(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    nfd = unicodedata.normalize("NFD", "Mock máy học")

    created = repo.create(nfd)
    assert created.name == normalize_list_name(nfd) == unicodedata.normalize("NFC", nfd)

    renamed = repo.rename(created, unicodedata.normalize("NFD", "Mock đổi tên"))
    assert repo.get_by_name(unicodedata.normalize("NFD", "Mock đổi tên")) is renamed


def test_update_item_clear_note_removes_the_note_and_none_keeps_it(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    product = add_product(db_session)
    shopping_list = repo.create("Mock")
    item = repo.add_item(shopping_list.id or 0, product.id or 0, note="giữ")

    repo.update_item(item, quantity=2)
    assert item.note == "giữ"
    repo.update_item(item, clear_note=True)
    assert item.note is None
