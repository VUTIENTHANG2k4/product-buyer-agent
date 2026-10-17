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


def test_create_get_and_get_by_name(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)

    created = repo.create("Mock máy học tập", now=T0)

    assert created.id is not None
    assert (created.created_at, created.updated_at) == (T0, T0)
    assert repo.get(created.id) is created
    assert repo.get(999_999_999) is None
    assert repo.get_by_name("Mock máy học tập") is created
    assert repo.get_by_name("không có") is None


def test_list_all_orders_by_updated_at_desc_and_rename_touches_it(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    first = repo.create("Mock A", now=T0)
    second = repo.create("Mock B", now=T0 + timedelta(hours=1))
    assert repo.list_all() == [second, first]

    repo.rename(first, "Mock A2", now=T0 + timedelta(hours=2))

    assert repo.list_all() == [first, second]
    assert first.name == "Mock A2"


def test_add_item_creates_item_and_touches_the_list(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    product_id = _product_id(db_session)
    later = T0 + timedelta(hours=1)

    item = repo.add_item(
        shopping_list.id,  # type: ignore[arg-type]
        product_id,
        quantity=2,
        note="màu đen",
        price_at_add=20_000_000,
        now=later,
    )

    assert item.id is not None
    assert (item.quantity, item.note, item.price_at_add, item.added_at) == (
        2,
        "màu đen",
        20_000_000,
        later,
    )
    assert shopping_list.updated_at == later
    assert repo.list_items(shopping_list.id) == [item]  # type: ignore[arg-type]


def test_add_same_product_again_increments_quantity_and_keeps_first_values(
    db_session: Session,
) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    product_id = _product_id(db_session)
    first = repo.add_item(
        shopping_list.id,  # type: ignore[arg-type]
        product_id,
        quantity=2,
        note="ghi chú đầu",
        price_at_add=20_000_000,
        now=T0,
    )

    second = repo.add_item(
        shopping_list.id,  # type: ignore[arg-type]
        product_id,
        quantity=3,
        price_at_add=18_000_000,
        now=T0 + timedelta(hours=1),
    )

    assert second is first
    assert second.quantity == 5
    assert second.note == "ghi chú đầu"  # không truyền note mới thì giữ note cũ
    assert second.price_at_add == 20_000_000
    assert second.added_at == T0
    assert len(db_session.exec(select(ShoppingListItem)).all()) == 1

    third = repo.add_item(shopping_list.id, product_id, note="ghi chú mới")  # type: ignore[arg-type]
    assert (third.quantity, third.note) == (6, "ghi chú mới")


def test_add_item_sets_preferred_offer(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    product_id = _product_id(db_session)
    offer = make_offer(product_id)
    db_session.add(offer)
    db_session.flush()

    item = repo.add_item(shopping_list.id, product_id, preferred_offer_id=offer.id)  # type: ignore[arg-type]

    assert item.preferred_offer_id == offer.id


def test_add_item_rejects_non_positive_quantity(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    product_id = _product_id(db_session)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        repo.add_item(shopping_list.id, product_id, quantity=0)  # type: ignore[arg-type]


def test_update_and_remove_item(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    item = repo.add_item(shopping_list.id, _product_id(db_session))  # type: ignore[arg-type]

    repo.update_item(item, quantity=4)
    repo.update_item(item, note="ưu tiên")
    repo.update_item(item)
    assert (item.quantity, item.note) == (4, "ưu tiên")
    assert repo.get_item(item.id) is item  # type: ignore[arg-type]

    repo.remove_item(item)

    assert repo.list_items(shopping_list.id) == []  # type: ignore[arg-type]
    assert repo.get_item(999_999_999) is None


def test_delete_list_cascades_to_items(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    repo.add_item(shopping_list.id, _product_id(db_session))  # type: ignore[arg-type]
    keep = repo.create("Mock giữ lại")
    repo.add_item(keep.id, _product_id(db_session))  # type: ignore[arg-type]

    repo.delete(shopping_list)

    assert repo.get_by_name("Mock") is None
    assert len(db_session.exec(select(ShoppingListItem)).all()) == 1


def test_list_items_orders_by_added_at(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock")
    late = repo.add_item(shopping_list.id, _product_id(db_session), now=T0 + timedelta(hours=2))  # type: ignore[arg-type]
    early = repo.add_item(shopping_list.id, _product_id(db_session), now=T0)  # type: ignore[arg-type]

    assert repo.list_items(shopping_list.id) == [early, late]  # type: ignore[arg-type]


def test_update_and_remove_item_touch_the_list_updated_at(db_session: Session) -> None:
    repo = ShoppingListRepository(db_session)
    shopping_list = repo.create("Mock", now=T0)
    item = repo.add_item(shopping_list.id, _product_id(db_session), now=T0)  # type: ignore[arg-type]

    repo.update_item(item, quantity=2, now=T0 + timedelta(hours=1))
    assert shopping_list.updated_at == T0 + timedelta(hours=1)

    repo.remove_item(item, now=T0 + timedelta(hours=2))
    assert shopping_list.updated_at == T0 + timedelta(hours=2)
