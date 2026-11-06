"""T6.7v: `contains`/`contains_any` với trường chuỗi (cpu_model, gpu_model) là so khớp chuỗi con.

Eval L10 ("laptop core i7 ram 32gb ssd 1tb"): planner luôn viết `cpu_model contains "i7"`, trước đây
bị dịch thành "danh sách cpu_model chứa i7" nên không bao giờ khớp và agent gọi lại tool 8 lần.
"""

from typing import Any

import pytest
from sqlmodel import Session

from app.db.models import Product
from app.db.repositories import ProductQuery, ProductRepository
from app.domain.dto import SpecFilter
from app.domain.enums import Category
from tests.factories import make_offer, make_product


def add_laptop(session: Session, **specs: Any) -> Product:
    product = make_product(specs={"ram_gb": 16, **specs})
    session.add(product)
    session.flush()
    session.add(make_offer(product.id or 0))
    session.flush()
    return product


def ids(session: Session, *filters: SpecFilter) -> set[int]:
    query = ProductQuery(category=Category.laptop, spec_filters=list(filters))
    return {hit.product.id or 0 for hit in ProductRepository(session).search(query).items}


def test_contains_matches_a_substring_of_a_string_field_case_insensitively(
    db_session: Session,
) -> None:
    i7 = add_laptop(db_session, cpu_model="i7-14700HX")
    add_laptop(db_session, cpu_model="Ryzen 7 7745HX")
    add_laptop(db_session, cpu_model="i5-12450H")

    found = ids(db_session, SpecFilter(field="cpu_model", op="contains", value="I7"))

    assert found == {i7.id}


def test_contains_on_a_list_field_still_means_list_membership(db_session: Session) -> None:
    wired = make_product(category=Category.mouse, specs={"connection": ["wired", "bluetooth"]})
    wireless = make_product(category=Category.mouse, specs={"connection": ["wireless_2_4"]})
    db_session.add_all([wired, wireless])
    db_session.flush()
    db_session.add_all([make_offer(wired.id or 0), make_offer(wireless.id or 0)])
    db_session.flush()

    query = ProductQuery(
        category=Category.mouse,
        spec_filters=[SpecFilter(field="connection", op="contains", value="bluetooth")],
    )
    found = {hit.product.id for hit in ProductRepository(db_session).search(query).items}

    assert found == {wired.id}


def test_contains_any_matches_any_substring_of_a_string_field(db_session: Session) -> None:
    i7 = add_laptop(db_session, cpu_model="i7-13620H")
    ryzen = add_laptop(db_session, cpu_model="Ryzen 9 8945HS")
    add_laptop(db_session, cpu_model="i5-1335U")

    found = ids(
        db_session, SpecFilter(field="cpu_model", op="contains_any", value=["i7", "ryzen 9"])
    )

    assert found == {i7.id, ryzen.id}


def test_contains_does_not_match_products_without_the_field_or_with_a_number(
    db_session: Session,
) -> None:
    add_laptop(db_session)  # không có cpu_model
    add_laptop(db_session, cpu_model=None)

    assert ids(db_session, SpecFilter(field="cpu_model", op="contains", value="i7")) == set()


@pytest.mark.parametrize("needle", ["%", "_", "\\", "i7%", "_7"])
def test_like_wildcards_in_the_value_are_literal(db_session: Session, needle: str) -> None:
    add_laptop(db_session, cpu_model="i7-14700HX")

    assert ids(db_session, SpecFilter(field="cpu_model", op="contains", value=needle)) == set()
