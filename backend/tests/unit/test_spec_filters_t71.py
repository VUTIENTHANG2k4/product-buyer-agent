"""T7.1: mô tả trường lọc từ khung specs và đọc tham số `spec.<field>__<op>`."""

import pytest

from app.domain.dto import SpecFilter
from app.domain.enums import Category
from app.domain.errors import ValidationFailed
from app.normalize.specs import SPEC_MODELS
from app.services.spec_filters import parse_spec_filters, spec_fields


def test_every_spec_model_field_is_described_with_ops_matching_its_kind() -> None:
    for category, model in SPEC_MODELS.items():
        names = {info.name for info in spec_fields(category)}
        assert set(model.model_fields) <= names, category
        for info in spec_fields(category):
            assert info.ops, (category, info.name)


def test_computed_gpu_rank_is_a_filterable_integer() -> None:
    fields = {info.name: info for info in spec_fields(Category.laptop)}

    assert fields["gpu_rank"].kind == "integer"
    assert "gte" in fields["gpu_rank"].ops


def test_category_without_a_spec_model_has_no_fields() -> None:
    assert spec_fields(Category.other) == ()


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"spec.gpu_rank__gte": "40"}, SpecFilter(field="gpu_rank", op="gte", value=40)),
        ({"spec.ram_gb": "16"}, SpecFilter(field="ram_gb", op="eq", value=16)),  # không có __op
        ({"spec.screen_in__lte": "15.6"}, SpecFilter(field="screen_in", op="lte", value=15.6)),
        ({"spec.screen_in__gte": "16.0"}, SpecFilter(field="screen_in", op="gte", value=16)),
        ({"spec.is_gaming": "TRUE"}, SpecFilter(field="is_gaming", op="eq", value=True)),
        (
            {"spec.cpu_vendor__in": "intel, amd"},
            SpecFilter(field="cpu_vendor", op="in", value=["intel", "amd"]),
        ),
    ],
)
def test_valid_params_become_spec_filters(params: dict[str, str], expected: SpecFilter) -> None:
    assert parse_spec_filters(params, Category.laptop) == [expected]


def test_other_query_params_are_ignored() -> None:
    assert parse_spec_filters({"q": "x", "sort": "price_asc", "category": "laptop"}, None) == []


@pytest.mark.parametrize(
    "params",
    [
        {"spec.nope": "1"},
        {"spec.ram_gb__between": "1"},
        {"spec.ram_gb__contains": "1"},
        {"spec.ram_gb__gte": "1.5"},
        {"spec.ram_gb__gte": "1e3"},
        {"spec.ram_gb__gte": "9" * 40},
        {"spec.is_gaming__gte": "1"},
        {"spec.is_gaming": "1"},
        {"spec.cpu_vendor": "arm"},
        {"spec.cpu_vendor__in": "intel,arm"},
        {"spec.cpu_vendor__in": " , "},
        {"spec.cpu_vendor__in": ",".join(["intel"] * 51)},
        {"spec.cpu_model": "a\x00b"},
        {"spec.cpu_model": "x" * 201},
        {"spec.": "1"},
    ],
)
def test_invalid_params_raise_validation_failed(params: dict[str, str]) -> None:
    with pytest.raises(ValidationFailed):
        parse_spec_filters(params, Category.laptop)


def test_spec_params_without_category_are_rejected() -> None:
    with pytest.raises(ValidationFailed, match="category"):
        parse_spec_filters({"spec.ram_gb": "16"}, None)
