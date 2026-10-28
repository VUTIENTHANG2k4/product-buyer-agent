"""QA small-1: trần số lượng × giá (10^12 ₫) của ShoppingListService (PostgreSQL thật).

Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-S1-n); khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import pytest
from sqlmodel import Session

from app.domain.catalog import MAX_QUANTITY
from app.domain.dto import INT8_MAX
from app.domain.enums import StockStatus
from app.domain.errors import ValidationFailed
from app.services.shopping_list_service import MAX_LINE_TOTAL_VND, ShoppingListService
from tests.service_support import add_offer, add_product, clock

CAP = MAX_LINE_TOTAL_VND


def lists(session: Session) -> ShoppingListService:
    return ShoppingListService(session, now=clock)


def test_the_cap_is_exactly_ten_to_the_twelfth() -> None:
    assert CAP == 10**12


@pytest.mark.parametrize("price", [1, 7, 999_999, 20_990_000, 3_333_333])
def test_adding_the_largest_quantity_under_the_cap_works_and_one_more_is_rejected(
    db_session: Session, price: int
) -> None:
    """Ranh giới đúng: quantity × price == floor(cap/price) × price chấp nhận, +1 từ chối."""
    product = add_product(db_session)
    add_offer(db_session, product, price=price)
    service = lists(db_session)
    created = service.create_list("Mock")
    largest = min(CAP // price, MAX_QUANTITY)

    item = service.add_item(created.list_id, product.id or 0, quantity=largest)

    assert item.quantity == largest and largest * price <= CAP
    if largest < MAX_QUANTITY:
        with pytest.raises(ValidationFailed, match="vượt"):
            service.update_item(created.list_id, item.item_id, quantity=largest + 1)
        assert service.get_list(created.list_id).items[0].quantity == largest


def test_a_new_line_one_unit_over_the_cap_is_rejected_on_add(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=1000)
    service = lists(db_session)
    created = service.create_list("Mock")

    with pytest.raises(ValidationFailed, match="vượt"):
        service.add_item(created.list_id, product.id or 0, quantity=CAP // 1000 + 1)

    assert service.get_list(created.list_id).items == []


def test_quantity_outside_one_to_int32_is_rejected_before_the_price_check(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=1)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(created.list_id, product.id or 0)

    for bad in (0, -1, MAX_QUANTITY + 1, 2**63):
        with pytest.raises(ValidationFailed):
            service.add_item(created.list_id, product.id or 0, quantity=bad)
        with pytest.raises(ValidationFailed):
            service.update_item(created.list_id, item.item_id, quantity=bad)

    assert service.get_list(created.list_id).items[0].quantity == 1


def test_total_of_several_lines_adds_up_and_skips_lines_without_a_price(
    db_session: Session,
) -> None:
    service = lists(db_session)
    created = service.create_list("Mock")
    expected = 0
    for index, (price, quantity) in enumerate([(1_500_000, 3), (20_990_000, 2), (99_000, 10)]):
        product = add_product(db_session, canonical_name=f"Mock sản phẩm {index}")
        add_offer(db_session, product, price=price)
        service.add_item(created.list_id, product.id or 0, quantity=quantity)
        expected += price * quantity
    sold_out = add_product(db_session, canonical_name="Mock hết hàng")
    add_offer(db_session, sold_out, price=5_000_000, stock_status=StockStatus.out_of_stock)
    unpriced = add_product(db_session, canonical_name="Mock không offer")
    service.add_item(created.list_id, sold_out.id or 0, quantity=4)
    service.add_item(created.list_id, unpriced.id or 0, quantity=4)

    detail = service.get_list(created.list_id)

    assert detail.item_count == 5 and detail.total_price == expected
    assert [item.current_price for item in detail.items][-2:] == [None, None]
    assert service.list_lists()[0].total_price == expected


def test_many_lines_each_exactly_at_the_cap_sum_without_overflow(db_session: Session) -> None:
    service = lists(db_session)
    created = service.create_list("Mock")
    for index in range(5):
        product = add_product(db_session, canonical_name=f"Mock dòng {index}")
        add_offer(db_session, product, price=1_000_000)
        service.add_item(created.list_id, product.id or 0, quantity=1_000_000)

    detail = service.get_list(created.list_id)

    assert detail.total_price == 5 * CAP <= INT8_MAX


def test_an_out_of_stock_preferred_offer_falls_back_to_the_cheapest_sellable_one(
    db_session: Session,
) -> None:
    """Giá dùng để kiểm trần phải trùng với giá hiển thị (offer ưu tiên hết hàng bị bỏ qua)."""
    product = add_product(db_session)
    cheap = add_offer(db_session, product, price=1_000_000)
    sold_out = add_offer(
        db_session, product, price=900_000_000, stock_status=StockStatus.out_of_stock
    )
    service = lists(db_session)
    created = service.create_list("Mock")

    item = service.add_item(
        created.list_id, product.id or 0, quantity=2_000, preferred_offer_id=sold_out.id
    )

    assert item.current_price == cheap.price  # 2.000 × 900 triệu sẽ vượt trần nếu dùng nhầm
    assert item.best_offer is not None and item.best_offer.offer_id == cheap.id


def test_preferred_offer_of_another_product_is_rejected_and_changes_nothing(
    db_session: Session,
) -> None:
    mine, other = add_product(db_session), add_product(db_session, canonical_name="Mock khác")
    add_offer(db_session, mine, price=1_000_000)
    foreign = add_offer(db_session, other, price=1_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(created.list_id, mine.id or 0, quantity=5)

    with pytest.raises(ValidationFailed):
        service.update_item(
            created.list_id, item.item_id, quantity=9, preferred_offer_id=foreign.id
        )
    with pytest.raises(ValidationFailed):
        service.add_item(created.list_id, mine.id or 0, preferred_offer_id=foreign.id)

    (after,) = service.get_list(created.list_id).items
    assert (after.quantity, after.preferred_offer_id) == (5, None)


def test_clear_wins_when_both_clear_and_set_preferred_offer_are_given(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=1_000_000)
    dear = add_offer(db_session, product, price=900_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(
        created.list_id, product.id or 0, quantity=1_000, preferred_offer_id=dear.id
    )

    after = service.update_item(
        created.list_id,
        item.item_id,
        preferred_offer_id=dear.id,
        clear_preferred_offer=True,
    )

    assert after.preferred_offer_id is None and after.current_price == 1_000_000


def test_note_only_update_is_allowed_even_when_the_line_drifted_above_the_cap(
    db_session: Session,
) -> None:
    """Giá tăng sau khi thêm làm dòng vượt trần: sửa ghi chú không bị kẹt bởi kiểm trần."""
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=1_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(created.list_id, product.id or 0, quantity=1_000_000)
    offer.price = 2_000_000
    db_session.flush()

    after = service.update_item(created.list_id, item.item_id, note="ghi chú mới")

    assert after.note == "ghi chú mới" and after.current_price == 2_000_000
    assert service.get_list(created.list_id).total_price == 2 * CAP


def test_removing_the_product_offers_after_adding_leaves_the_list_readable(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=20_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    service.add_item(created.list_id, product.id or 0, quantity=3)
    offer.is_active = False
    db_session.flush()

    detail = service.get_list(created.list_id)

    assert detail.total_price == 0 and detail.items[0].current_price is None
    assert detail.items[0].price_at_add == 20_000_000 and detail.items[0].price_delta is None


def test_adding_to_a_line_with_a_dear_preferred_offer_checks_the_cap_with_that_offer(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=1_000_000)
    dear = add_offer(db_session, product, price=900_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    service.add_item(created.list_id, product.id or 0, quantity=1_000, preferred_offer_id=dear.id)

    try:
        # Gộp thành 1.200 × 900 triệu = 1,08e12 > 10^12 nhưng 1.200 × 1 triệu thì không.
        service.add_item(created.list_id, product.id or 0, quantity=200)
    except ValidationFailed:
        return
    (item,) = service.get_list(created.list_id).items
    assert item.quantity * (item.current_price or 0) <= CAP
