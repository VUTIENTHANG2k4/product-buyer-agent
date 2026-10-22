"""T7.3: `update_item` đổi/xóa offer ưu tiên và kiểm offer thuộc đúng sản phẩm."""

import pytest
from sqlmodel import Session

from app.db.repositories import ShoppingListRepository
from app.domain.errors import ValidationFailed
from app.services.shopping_list_service import ShoppingListService
from tests.service_support import add_offer, add_product, clock


def make(session: Session) -> ShoppingListService:
    return ShoppingListService(session, now=clock)


def test_update_item_sets_then_clears_the_preferred_offer(db_session: Session) -> None:
    product = add_product(db_session)
    cheap = add_offer(db_session, product, price=20_000_000)
    pricey = add_offer(db_session, product, price=26_000_000, url="https://mock.example/pricey")
    service = make(db_session)
    shopping_list = service.create_list("Mock")
    item = service.add_item(shopping_list.list_id, product.id or 0)

    chosen = service.update_item(shopping_list.list_id, item.item_id, preferred_offer_id=pricey.id)
    cleared = service.update_item(shopping_list.list_id, item.item_id, clear_preferred_offer=True)

    assert (chosen.preferred_offer_id, chosen.current_price) == (pricey.id, 26_000_000)
    assert (cleared.preferred_offer_id, cleared.current_price) == (None, cheap.price)


def test_update_item_without_the_argument_keeps_the_preferred_offer(db_session: Session) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product)
    service = make(db_session)
    shopping_list = service.create_list("Mock")
    item = service.add_item(shopping_list.list_id, product.id or 0, preferred_offer_id=offer.id)

    updated = service.update_item(shopping_list.list_id, item.item_id, quantity=2)

    assert updated.preferred_offer_id == offer.id


@pytest.mark.parametrize("bad", [999_999, 2**31, 2**70, 0, -1])
def test_update_item_rejects_unknown_offer_without_changing_anything(
    db_session: Session, bad: int
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    service = make(db_session)
    shopping_list = service.create_list("Mock")
    item = service.add_item(shopping_list.list_id, product.id or 0)

    with pytest.raises(ValidationFailed):
        service.update_item(shopping_list.list_id, item.item_id, quantity=7, preferred_offer_id=bad)

    stored = ShoppingListRepository(db_session).get_item(item.item_id)
    assert stored is not None
    assert (stored.quantity, stored.preferred_offer_id) == (1, None)


def test_update_item_rejects_an_offer_of_another_product(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    foreign = add_offer(db_session, add_product(db_session))
    service = make(db_session)
    shopping_list = service.create_list("Mock")
    item = service.add_item(shopping_list.list_id, product.id or 0)

    with pytest.raises(ValidationFailed, match="Offer ưu tiên"):
        service.update_item(shopping_list.list_id, item.item_id, preferred_offer_id=foreign.id)
