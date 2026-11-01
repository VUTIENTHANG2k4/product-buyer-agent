"""T7.1: id ngoài miền INTEGER là "không tồn tại", không phải `DataError` (HTTP 500)."""

import pytest
from sqlmodel import Session

from app.db.repositories import (
    ConversationRepository,
    OfferRepository,
    PriceAlertRepository,
    ProductRepository,
    ScrapeRunRepository,
    ShoppingListRepository,
)
from app.domain.dto import INT4_MAX
from app.domain.enums import AlertChannel, Category
from tests.service_support import add_offer, add_product

BAD_IDS = [0, -1, INT4_MAX + 1, 2**63, 2**70]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_get_by_primary_key_returns_none_for_out_of_range_ids(
    db_session: Session, bad: int
) -> None:
    assert ProductRepository(db_session).get(bad) is None
    assert OfferRepository(db_session).get(bad) is None
    assert ShoppingListRepository(db_session).get(bad) is None
    assert ShoppingListRepository(db_session).get_item(bad) is None
    assert PriceAlertRepository(db_session).get(bad) is None
    assert ConversationRepository(db_session).get(bad) is None
    assert ScrapeRunRepository(db_session).get(bad) is None


@pytest.mark.parametrize("bad", BAD_IDS)
def test_list_queries_ignore_out_of_range_ids(db_session: Session, bad: int) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    assert product.id is not None

    assert ProductRepository(db_session).get_many([bad]) == []
    assert ProductRepository(db_session).get_many([bad, product.id]) == [product]
    offers = OfferRepository(db_session)
    assert offers.list_for_products([bad]) == {bad: []}
    assert offers.list_for_product(bad) == []
    alerts = PriceAlertRepository(db_session)
    assert alerts.list_for_products([bad]) == []
    assert alerts.find_live(bad, AlertChannel.email, "mock@example.com") is None


@pytest.mark.parametrize("bad", BAD_IDS)
def test_preferred_offer_outside_the_key_range_is_rejected_like_a_foreign_offer(
    db_session: Session, bad: int
) -> None:
    product = add_product(db_session)
    lists = ShoppingListRepository(db_session)
    shopping_list = lists.create("Mock danh sách")
    assert shopping_list.id is not None and product.id is not None

    with pytest.raises(ValueError, match="preferred_offer_id"):
        lists.add_item(shopping_list.id, product.id, preferred_offer_id=bad)


def test_count_by_category_counts_products_with_an_active_offer(db_session: Session) -> None:
    live = add_product(db_session, category=Category.mouse)
    add_offer(db_session, live)
    add_offer(db_session, live)  # nhiều offer vẫn tính một sản phẩm
    dead = add_product(db_session, category=Category.mouse)
    add_offer(db_session, dead, is_active=False)
    add_product(db_session, category=Category.keyboard)  # không có offer

    counts = ProductRepository(db_session).count_by_category()

    assert counts.get(Category.mouse) == 1
    assert Category.keyboard not in counts
