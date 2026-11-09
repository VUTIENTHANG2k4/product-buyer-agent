"""X1.8: LLM hay đặt hãng vào `spec_filters` (`field="brand"`) thay vì `brands`.

Eval P01 "điện thoại Samsung dưới 10 triệu" (2026-11-09, 10 lần): 6/10 lần Gemini gọi
`search_catalog(spec_filters=[{field: brand, op: eq, value: Samsung}])`; trường `brand` không có
trong khung thông số nên kết quả rỗng và agent gọi lặp tới hết hạn mức (1 lần rớt). Tool phải hiểu
đó là bộ lọc hãng.
"""

import pytest
from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.tools.search_catalog import SearchCatalogArgs
from app.domain.dto import SpecFilter
from app.domain.enums import Category
from tests.agent.conftest import call


def brand_filter(op: str, value: object, field: str = "brand") -> dict[str, object]:
    return {"field": field, "op": op, "value": value}


@pytest.mark.parametrize(
    ("given", "brands"),
    [
        (brand_filter("eq", "Samsung"), ["Samsung"]),
        (brand_filter("eq", "Samsung", field="Brand"), ["Samsung"]),
        (brand_filter("eq", "Samsung", field="brands"), ["Samsung"]),
        (brand_filter("contains", "Samsung"), ["Samsung"]),
        (brand_filter("in", ["Samsung", "Xiaomi"]), ["Samsung", "Xiaomi"]),
        (brand_filter("contains_any", ["Samsung", "Xiaomi"]), ["Samsung", "Xiaomi"]),
    ],
)
def test_a_brand_spec_filter_is_moved_to_brands(
    given: dict[str, object], brands: list[str]
) -> None:
    args = SearchCatalogArgs.model_validate(
        {"category": "phone", "spec_filters": [given, {"field": "ram_gb", "op": "gte", "value": 8}]}
    )

    assert args.brands == brands
    assert args.spec_filters == [SpecFilter(field="ram_gb", op="gte", value=8)]


def test_moved_brands_are_merged_without_duplicates_and_capped_at_ten() -> None:
    args = SearchCatalogArgs.model_validate(
        {
            "category": "phone",
            "brands": ["samsung"],
            "spec_filters": [brand_filter("in", ["Samsung", *(f"B{i}" for i in range(14))])],
        }
    )

    assert args.brands[0] == "samsung" and "Samsung" not in args.brands
    assert len(args.brands) == 10


def test_a_brand_range_filter_is_left_alone_and_other_fields_are_untouched() -> None:
    args = SearchCatalogArgs.model_validate(
        {
            "category": "laptop",
            "spec_filters": [
                brand_filter("gte", 3),
                {"field": "brandless", "op": "eq", "value": 1},
            ],
        }
    )

    assert args.brands == []
    assert [spec.field for spec in args.spec_filters] == ["brand", "brandless"]


async def test_search_with_the_brand_in_spec_filters_finds_the_same_phones_as_with_brands(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    proper = await call(
        tools, "search_catalog", category=Category.phone.value, brands=["Samsung"], limit=20
    )
    sloppy = await call(
        tools,
        "search_catalog",
        category=Category.phone.value,
        spec_filters=[brand_filter("eq", "Samsung")],
        limit=20,
    )

    assert proper["total"] >= 2  # seed dev có điện thoại Samsung
    assert sloppy["total"] == proper["total"]
    assert [i["product_id"] for i in sloppy["items"]] == [i["product_id"] for i in proper["items"]]
    assert sloppy["applied_filters"]["brands"] == ["Samsung"]
