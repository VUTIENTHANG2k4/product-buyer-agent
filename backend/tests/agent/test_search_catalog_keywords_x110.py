"""X1.10: `search_catalog` nhận từ khóa (`keywords` → `CatalogFilters.q`).

Hội thoại 50 (2026-11-09) "tai nghe gaming giá dưới 1 triệu": planner tách `keywords: ["gaming"]`
nhưng tool không có tham số từ khóa, nên Gemini xoay xở bằng `has_mic` và danh sách hãng tự đặt.
"""

import pytest
from langchain_core.tools import BaseTool
from pydantic import ValidationError
from sqlmodel import Session

from app.agent.executor import summarize_result
from app.agent.tools.search_catalog import SearchCatalogArgs
from app.domain.dto import SpecFilter
from app.domain.enums import Category
from tests.agent.conftest import call


async def test_a_keyword_keeps_only_products_with_that_word_in_the_name(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    every = await call(tools, "search_catalog", category=Category.headset.value, limit=20)
    gaming = await call(
        tools, "search_catalog", category=Category.headset.value, keywords=["gaming"], limit=20
    )

    assert 0 < gaming["total"] < every["total"]
    assert all("gaming" in item["name"].lower() for item in gaming["items"])
    assert gaming["applied_filters"]["q"] == "gaming"
    assert "keywords_relaxed" not in gaming


async def test_an_unaccented_keyword_matches_an_accented_name(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    accented = await call(
        tools, "search_catalog", category=Category.headset.value, keywords=["GAMING "], limit=20
    )
    plain = await call(
        tools, "search_catalog", category=Category.headset.value, keywords=["gaming"], limit=20
    )

    assert accented["total"] == plain["total"] > 0


async def test_a_keyword_that_empties_the_result_is_dropped_and_reported(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    every = await call(
        tools, "search_catalog", category=Category.mouse.value, price_max=1_000_000, limit=20
    )
    relaxed = await call(
        tools,
        "search_catalog",
        category=Category.mouse.value,
        price_max=1_000_000,
        keywords=["khongcotrongtenxyz"],
        limit=20,
    )

    assert relaxed["total"] == every["total"] > 0
    assert relaxed["keywords_relaxed"] is True
    assert relaxed["ignored_keywords"] == ["khongcotrongtenxyz"]
    assert relaxed["applied_filters"]["price_max"] == 1_000_000  # điều kiện khác vẫn giữ
    assert "q" not in relaxed["applied_filters"]
    assert "đã bỏ từ khóa" in summarize_result("search_catalog", relaxed)


async def test_without_keywords_an_empty_result_is_not_marked_relaxed(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    empty = await call(tools, "search_catalog", category=Category.mouse.value, price_max=1)

    assert empty["total"] == 0
    assert "keywords_relaxed" not in empty


def test_keywords_are_trimmed_and_deduplicated() -> None:
    args = SearchCatalogArgs.model_validate(
        {"category": "headset", "keywords": ["  gaming ", "Gaming", "", "  ", "7.1"]}
    )

    assert args.keywords == ["gaming", "7.1"]


def test_gaming_for_a_laptop_becomes_the_is_gaming_spec_filter() -> None:
    args = SearchCatalogArgs.model_validate({"category": "laptop", "keywords": ["Gaming", "oled"]})

    assert args.keywords == ["oled"]
    assert args.spec_filters == [SpecFilter(field="is_gaming", op="eq", value=True)]


def test_gaming_for_a_laptop_does_not_duplicate_an_existing_is_gaming_filter() -> None:
    args = SearchCatalogArgs.model_validate(
        {
            "category": "laptop",
            "keywords": ["gaming"],
            "spec_filters": [{"field": "is_gaming", "op": "eq", "value": True}],
        }
    )

    assert args.keywords == []
    assert len(args.spec_filters) == 1


@pytest.mark.parametrize(
    "keywords", [[f"k{i}" for i in range(6)], ["x" * 41]], ids=["too-many", "too-long"]
)
def test_too_many_or_too_long_keywords_are_rejected(keywords: list[str]) -> None:
    with pytest.raises(ValidationError):
        SearchCatalogArgs.model_validate({"category": "headset", "keywords": keywords})


async def test_invalid_keywords_come_back_as_a_validation_error(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(
        tools, "search_catalog", category=Category.headset.value, keywords=["x" * 41]
    )

    assert result["ok"] is False
    assert result["error"] == "VALIDATION_ERROR"
