"""QA M1: test biên cho `ShoppingListRepository` (docs/04 §3: thêm trùng, quantity, liên kết)."""

import unicodedata
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import ShoppingListItem
from app.db.repositories.products import ProductRepository
from app.db.repositories.shopping_lists import ShoppingListRepository
from tests.factories import make_offer, make_product

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _product_id(session: Session) -> int:
    product = ProductRepository(session).add(make_product())
    assert product.id is not None
    return product.id


def test_add_item_with_non_positive_quantity_on_existing_item_is_rejected_and_keeps_quantity(
    db_session: Session,
) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    assert shopping_list.id is not None
    product_id = _product_id(db_session)
    item = repo.add_item(shopping_list.id, product_id, quantity=2, now=T0)

    for bad in (0, -1, -5):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            repo.add_item(shopping_list.id, product_id, quantity=bad)

    db_session.refresh(item)
    assert item.quantity == 2


@pytest.mark.parametrize("which", ["product", "list"])
def test_add_item_with_unknown_parent_is_rejected_and_does_not_touch_the_list(
    db_session: Session, which: str
) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    assert shopping_list.id is not None
    product_id = _product_id(db_session)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        if which == "product":
            repo.add_item(shopping_list.id, 999_999_999, now=T0 + timedelta(hours=1))
        else:
            repo.add_item(999_999_999, product_id, now=T0 + timedelta(hours=1))

    db_session.refresh(shopping_list)
    assert shopping_list.updated_at == T0
    assert db_session.exec(select(ShoppingListItem)).all() == []


def test_same_product_in_two_lists_keeps_independent_quantities(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    first, second = repo.create("Mock A"), repo.create("Mock B")
    assert first.id is not None and second.id is not None
    product_id = _product_id(db_session)

    repo.add_item(first.id, product_id, quantity=2)
    repo.add_item(first.id, product_id, quantity=1)
    other = repo.add_item(second.id, product_id, quantity=5)

    assert [item.quantity for item in repo.list_items(first.id)] == [3]
    assert other.quantity == 5


def test_add_item_on_conflict_keeps_note_and_offer_when_new_values_are_blank_strings(
    db_session: Session,
) -> None:
    """`note=""` là giá trị có thật (khác None): thay ghi chú cũ; None thì giữ ghi chú cũ."""
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    assert shopping_list.id is not None
    product_id = _product_id(db_session)
    repo.add_item(shopping_list.id, product_id, note="màu đen")

    kept = repo.add_item(shopping_list.id, product_id, note=None)
    assert kept.note == "màu đen"
    cleared = repo.add_item(shopping_list.id, product_id, note="")
    assert (cleared.note, cleared.quantity) == ("", 3)


def test_remove_then_add_again_starts_from_scratch(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    assert shopping_list.id is not None
    product_id = _product_id(db_session)
    first = repo.add_item(shopping_list.id, product_id, quantity=4, price_at_add=10, now=T0)
    repo.remove_item(first)

    again = repo.add_item(
        shopping_list.id, product_id, quantity=1, price_at_add=20, now=T0 + timedelta(hours=1)
    )

    assert (again.quantity, again.price_at_add, again.added_at) == (1, 20, T0 + timedelta(hours=1))
    assert again.id != first.id


def test_deleting_the_preferred_offer_keeps_the_item_and_clears_the_link(
    db_session: Session,
) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    assert shopping_list.id is not None
    product_id = _product_id(db_session)
    offer = make_offer(product_id)
    db_session.add(offer)
    db_session.flush()
    item = repo.add_item(shopping_list.id, product_id, preferred_offer_id=offer.id)

    db_session.delete(offer)
    db_session.flush()
    db_session.refresh(item)

    assert (item.preferred_offer_id, item.quantity) == (None, 1)


def test_two_lists_with_the_same_name_resolve_to_the_oldest(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    oldest = repo.create("Mock trùng tên", now=T0)
    repo.create("Mock trùng tên", now=T0 + timedelta(hours=1))

    assert repo.get_by_name("Mock trùng tên") is oldest
    assert len(repo.list_all()) == 2


def test_add_item_rejects_preferred_offer_of_another_product(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    assert shopping_list.id is not None
    mine, other = _product_id(db_session), _product_id(db_session)
    foreign = make_offer(other)
    db_session.add(foreign)
    db_session.flush()

    with pytest.raises((IntegrityError, ValueError)), db_session.begin_nested():
        repo.add_item(shopping_list.id, mine, preferred_offer_id=foreign.id)


def test_get_by_name_matches_vietnamese_name_in_either_unicode_form(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    name = "Mock máy học tập"
    stored = repo.create(unicodedata.normalize("NFC", name))

    assert repo.get_by_name(unicodedata.normalize("NFD", name)) is stored
