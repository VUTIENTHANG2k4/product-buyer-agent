"""T1.6: DTO từ chối giá trị mà PostgreSQL không lưu được (không cần CSDL)."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.db.repositories.offers import MAX_URL_BYTES, OfferUpsert
from app.db.repositories.products import ProductQuery
from app.domain.dto import INT8_MAX, SpecFilter


def _offer(**changes: Any) -> OfferUpsert:
    base: dict[str, Any] = {
        "product_id": 1,
        "site": "mockshop",
        "url": "https://m.example/p",
        "title": "Mock laptop",
        "price": 1_000_000,
    }
    return OfferUpsert.model_validate({**base, **changes})


def test_url_at_the_byte_limit_is_accepted_and_one_more_is_rejected() -> None:
    prefix = "https://m.example/"
    assert _offer(url=prefix + "a" * (MAX_URL_BYTES - len(prefix)))
    with pytest.raises(ValidationError):
        _offer(url=prefix + "a" * (MAX_URL_BYTES - len(prefix) + 1))


def test_url_limit_counts_bytes_not_characters() -> None:
    with pytest.raises(ValidationError):
        _offer(url="https://m.example/" + "đ" * 1400)  # 1.400 ký tự = 2.800 byte


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "a\x00b"},
        {"site_sku": "a\x00"},
        {"raw_specs": {"k": "v\x00"}},
        {"raw_specs": {"k\x00": "v"}},
        {"raw_specs": {"k": ["ok", {"deep": "x\x00"}]}},
    ],
)
def test_nul_character_is_rejected_anywhere_in_text_fields(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _offer(**changes)


@pytest.mark.parametrize("field", ["price", "list_price"])
def test_prices_above_bigint_are_rejected_and_the_maximum_is_accepted(field: str) -> None:
    assert _offer(**{field: INT8_MAX})
    with pytest.raises(ValidationError):
        _offer(**{field: INT8_MAX + 1})


@pytest.mark.parametrize("field", ["price_min", "price_max", "offset"])
def test_product_query_integers_are_capped_at_bigint(field: str) -> None:
    assert ProductQuery.model_validate({field: INT8_MAX})
    with pytest.raises(ValidationError):
        ProductQuery.model_validate({field: INT8_MAX + 1})


def test_spec_filter_integer_value_is_capped_in_both_directions() -> None:
    assert SpecFilter(field="ram_gb", op="gte", value=INT8_MAX)
    for value in (INT8_MAX + 1, -INT8_MAX - 1):
        with pytest.raises(ValidationError):
            SpecFilter(field="ram_gb", op="gte", value=value)
