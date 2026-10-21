"""T6.2: ShoppingListService (gồm các ca QA M1 về tên NFC, offer ưu tiên, số lượng, ghi chú)."""

import unicodedata

import pytest
from sqlmodel import Session

from app.domain.catalog import MAX_QUANTITY
from app.domain.enums import StockStatus
from app.domain.errors import ListNotFound, ProductNotFound, ValidationFailed
from app.services.shopping_list_service import DEFAULT_LIST_NAME, ShoppingListService
from tests.service_support import NOW, add_offer, add_product, clock


def service(session: Session) -> ShoppingListService:
    return ShoppingListService(session, now=clock)


def test_create_cleans_the_name_to_nfc_with_single_spaces(db_session: Session) -> None:
    name = unicodedata.normalize("NFD", "  Mock   máy  học tập ")

    created = service(db_session).create_list(name)

    assert created.name == unicodedata.normalize("NFC", "Mock máy học tập")
    assert (created.item_count, created.total_price, created.updated_at) == (0, 0, NOW)


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_create_rejects_empty_or_overlong_names(db_session: Session, name: str) -> None:
    with pytest.raises(ValidationFailed):
        service(db_session).create_list(name)


def test_get_or_create_finds_the_list_across_unicode_forms_instead_of_duplicating(
    db_session: Session,
) -> None:
    first = service(db_session).get_or_create(unicodedata.normalize("NFC", "Mock máy học"))
    again = service(db_session).get_or_create(unicodedata.normalize("NFD", "Mock máy học"))

    assert again.list_id == first.list_id
    assert len(service(db_session).list_lists()) == 1


def test_get_or_create_without_name_uses_the_default_list(db_session: Session) -> None:
    assert service(db_session).get_or_create().name == DEFAULT_LIST_NAME


def test_add_item_records_best_buyable_price_at_add(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=22_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, product, price=25_000_000)
    add_offer(db_session, product, price=27_000_000)
    shopping_list = service(db_session).create_list("Mock")

    item = service(db_session).add_item(shopping_list.list_id, product.id or 0, quantity=2)

    assert (item.price_at_add, item.current_price, item.price_delta, item.quantity) == (
        25_000_000,
        25_000_000,
        0,
        2,
    )
    assert item.name == product.canonical_name
    assert service(db_session).get_list(shopping_list.list_id).total_price == 50_000_000


def test_adding_the_same_product_again_adds_quantity_and_keeps_the_first_price(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=25_000_000)
    shopping_list = service(db_session).create_list("Mock")
    service(db_session).add_item(shopping_list.list_id, product.id or 0)
    offer.price = 23_000_000
    db_session.flush()

    item = service(db_session).add_item(shopping_list.list_id, product.id or 0, quantity=2)

    assert (item.quantity, item.price_at_add, item.current_price, item.price_delta) == (
        3,
        25_000_000,
        23_000_000,
        -2_000_000,
    )


def test_preferred_offer_drives_current_price_until_it_stops_being_buyable(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    cheap = add_offer(db_session, product, price=25_000_000)
    preferred = add_offer(db_session, product, price=27_000_000)
    shopping_list = service(db_session).create_list("Mock")

    item = service(db_session).add_item(
        shopping_list.list_id, product.id or 0, preferred_offer_id=preferred.id
    )
    assert (item.price_at_add, item.current_price) == (27_000_000, 27_000_000)
    assert item.best_offer is not None and item.best_offer.offer_id == preferred.id

    preferred.stock_status = StockStatus.out_of_stock
    db_session.flush()
    detail = service(db_session).get_list(shopping_list.list_id)

    assert detail.items[0].current_price == 25_000_000
    assert (
        detail.items[0].best_offer is not None and detail.items[0].best_offer.offer_id == cheap.id
    )


def test_preferred_offer_of_another_product_is_rejected(db_session: Session) -> None:
    mine, other = add_product(db_session), add_product(db_session)
    foreign = add_offer(db_session, other)
    shopping_list = service(db_session).create_list("Mock")

    with pytest.raises(ValidationFailed, match="Offer ưu tiên"):
        service(db_session).add_item(
            shopping_list.list_id, mine.id or 0, preferred_offer_id=foreign.id
        )
    assert service(db_session).get_list(shopping_list.list_id).items == []


@pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY + 1])
def test_quantity_outside_range_is_rejected(db_session: Session, quantity: int) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    with pytest.raises(ValidationFailed):
        service(db_session).add_item(shopping_list.list_id, product.id or 0, quantity=quantity)


def test_accumulated_quantity_beyond_int32_is_rejected_not_a_database_error(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    service(db_session).add_item(shopping_list.list_id, product.id or 0, quantity=MAX_QUANTITY)

    with pytest.raises(ValidationFailed):
        service(db_session).add_item(shopping_list.list_id, product.id or 0)


def test_unknown_product_or_list_raise_domain_errors(db_session: Session) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    with pytest.raises(ProductNotFound):
        service(db_session).add_item(shopping_list.list_id, 999_999)
    with pytest.raises(ListNotFound):
        service(db_session).add_item(999_999, product.id or 0)
    with pytest.raises(ListNotFound):
        service(db_session).get_list(999_999)


def test_item_without_buyable_offer_has_no_current_price_and_not_in_total(
    db_session: Session,
) -> None:
    gone, ok = add_product(db_session), add_product(db_session)
    add_offer(db_session, ok, price=10_000_000)
    shopping_list = service(db_session).create_list("Mock")
    service(db_session).add_item(shopping_list.list_id, gone.id or 0)
    service(db_session).add_item(shopping_list.list_id, ok.id or 0, quantity=3)

    detail = service(db_session).get_list(shopping_list.list_id)

    by_product = {item.product_id: item for item in detail.items}
    assert by_product[gone.id or 0].current_price is None
    assert by_product[gone.id or 0].price_delta is None
    assert (detail.item_count, detail.total_price) == (2, 30_000_000)


def test_update_item_changes_quantity_and_note_and_can_clear_the_note(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    item = service(db_session).add_item(shopping_list.list_id, product.id or 0, note="đợi sale")

    changed = service(db_session).update_item(
        shopping_list.list_id, item.item_id, quantity=4, note="mua gấp"
    )
    cleared = service(db_session).update_item(shopping_list.list_id, item.item_id, clear_note=True)

    assert (changed.quantity, changed.note) == (4, "mua gấp")
    assert (cleared.quantity, cleared.note) == (4, None)


def test_update_item_validates_quantity_and_note_length(db_session: Session) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    item = service(db_session).add_item(shopping_list.list_id, product.id or 0)
    with pytest.raises(ValidationFailed):
        service(db_session).update_item(shopping_list.list_id, item.item_id, quantity=0)
    with pytest.raises(ValidationFailed):
        service(db_session).update_item(shopping_list.list_id, item.item_id, note="x" * 501)


def test_item_of_another_list_is_not_found(db_session: Session) -> None:
    product = add_product(db_session)
    first = service(db_session).create_list("Mock A")
    second = service(db_session).create_list("Mock B")
    item = service(db_session).add_item(first.list_id, product.id or 0)

    with pytest.raises(ListNotFound) as caught:
        service(db_session).update_item(second.list_id, item.item_id, quantity=2)
    assert caught.value.details == {"item_id": item.item_id}
    with pytest.raises(ListNotFound):
        service(db_session).remove_item(second.list_id, item.item_id)


def test_remove_item_and_delete_list(db_session: Session) -> None:
    product = add_product(db_session)
    shopping_list = service(db_session).create_list("Mock")
    item = service(db_session).add_item(shopping_list.list_id, product.id or 0)

    service(db_session).remove_item(shopping_list.list_id, item.item_id)
    assert service(db_session).get_list(shopping_list.list_id).items == []

    service(db_session).delete_list(shopping_list.list_id)
    assert service(db_session).list_lists() == []
    with pytest.raises(ListNotFound):
        service(db_session).delete_list(shopping_list.list_id)


def test_rename_list_cleans_the_new_name(db_session: Session) -> None:
    shopping_list = service(db_session).create_list("Mock cũ")
    renamed = service(db_session).rename_list(shopping_list.list_id, "  Mock  mới ")
    assert renamed.name == "Mock mới"


def test_list_lists_reports_counts_and_totals(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=5_000_000)
    first = service(db_session).create_list("Mock A")
    service(db_session).create_list("Mock B")
    service(db_session).add_item(first.list_id, product.id or 0, quantity=2)

    summaries = {s.name: s for s in service(db_session).list_lists()}

    assert (summaries["Mock A"].item_count, summaries["Mock A"].total_price) == (1, 10_000_000)
    assert (summaries["Mock B"].item_count, summaries["Mock B"].total_price) == (0, 0)


def test_clock_without_timezone_is_rejected(db_session: Session) -> None:
    naive = ShoppingListService(db_session, now=lambda: NOW.replace(tzinfo=None))
    with pytest.raises(ValidationFailed, match="múi giờ"):
        naive.create_list("Mock")
