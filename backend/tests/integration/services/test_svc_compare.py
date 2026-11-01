"""T6.2: CompareService."""

import pytest
from sqlmodel import Session

from app.domain.enums import StockStatus
from app.domain.errors import ProductNotFound, ValidationFailed
from app.services.compare_service import CompareService
from tests.service_support import add_offer, add_product, clock


def compare(session: Session, ids: list[int | None]) -> object:
    return CompareService(session, now=clock).compare([i for i in ids if i is not None])


def test_compare_reports_differing_fields_and_cheapest(db_session: Session) -> None:
    a = add_product(db_session, specs={"ram_gb": 16, "gpu_rank": 40, "os": "Win 11"})
    b = add_product(
        db_session, specs={"ram_gb": 32, "gpu_rank": 40, "os": "Win 11", "panel": "IPS"}
    )
    add_offer(db_session, a, price=27_000_000)
    add_offer(db_session, b, price=26_000_000)

    result = CompareService(db_session, now=clock).compare([a.id or 0, b.id or 0])

    assert [p.product_id for p in result.products] == [a.id, b.id]
    assert result.differing_fields == ["ram_gb", "panel"]
    assert result.cheapest_product_id == b.id


def test_compare_keeps_requested_order(db_session: Session) -> None:
    a, b = add_product(db_session), add_product(db_session)
    result = CompareService(db_session, now=clock).compare([b.id or 0, a.id or 0])
    assert [p.product_id for p in result.products] == [b.id, a.id]


def test_cheapest_ignores_out_of_stock_and_products_without_offers(db_session: Session) -> None:
    sold_out, none, ok = (add_product(db_session) for _ in range(3))
    add_offer(db_session, sold_out, price=10_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, ok, price=30_000_000)

    result = CompareService(db_session, now=clock).compare(
        [sold_out.id or 0, none.id or 0, ok.id or 0]
    )

    assert result.cheapest_product_id == ok.id


def test_cheapest_is_none_when_nothing_is_buyable(db_session: Session) -> None:
    a, b = add_product(db_session), add_product(db_session)
    assert (
        CompareService(db_session, now=clock).compare([a.id or 0, b.id or 0]).cheapest_product_id
        is None
    )


def test_price_tie_goes_to_the_smaller_product_id(db_session: Session) -> None:
    a, b = add_product(db_session), add_product(db_session)
    add_offer(db_session, a, price=20_000_000)
    add_offer(db_session, b, price=20_000_000)

    result = CompareService(db_session, now=clock).compare([b.id or 0, a.id or 0])

    assert result.cheapest_product_id == min(a.id or 0, b.id or 0)


def test_list_valued_specs_compare_by_value_not_identity(db_session: Session) -> None:
    a = add_product(db_session, specs={"connection": ["wired", "usb"]})
    b = add_product(db_session, specs={"connection": ["wired", "usb"]})
    c = add_product(db_session, specs={"connection": ["wireless"]})

    same = CompareService(db_session, now=clock).compare([a.id or 0, b.id or 0])
    different = CompareService(db_session, now=clock).compare([a.id or 0, c.id or 0])

    assert same.differing_fields == []
    assert different.differing_fields == ["connection"]


@pytest.mark.parametrize("count", [0, 1, 6])
def test_compare_needs_between_two_and_five_products(db_session: Session, count: int) -> None:
    ids = [add_product(db_session).id or 0 for _ in range(count)]
    with pytest.raises(ValidationFailed) as caught:
        CompareService(db_session, now=clock).compare(ids)
    assert caught.value.details == {"count": count}


def test_five_products_are_accepted(db_session: Session) -> None:
    ids = [add_product(db_session).id or 0 for _ in range(5)]
    assert len(CompareService(db_session, now=clock).compare(ids).products) == 5


def test_duplicate_ids_are_rejected(db_session: Session) -> None:
    a = add_product(db_session)
    with pytest.raises(ValidationFailed, match="trùng"):
        CompareService(db_session, now=clock).compare([a.id or 0, a.id or 0])


def test_unknown_ids_are_listed_in_the_error(db_session: Session) -> None:
    a = add_product(db_session)
    with pytest.raises(ProductNotFound) as caught:
        CompareService(db_session, now=clock).compare([a.id or 0, 888_888, 999_999])
    assert caught.value.details == {"product_ids": [888_888, 999_999]}
