"""Điện thoại ở tầng agent và dịch vụ (X1.5, ADR-0011): ý định tầng 1, tool, prompt, hiển thị."""

import pytest
from pydantic import ValidationError

from app.agent.fake_llm import plan_from_text
from app.agent.intent import (
    DEFAULT_CLARIFICATION,
    SEARCHABLE_SITES,
    TIER1_CATEGORIES,
    default_plan_steps,
    postprocess_intent,
)
from app.agent.planner import render_planner_prompt
from app.agent.tools import search_catalog
from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category, SiteKey
from app.services.rematch_service import REMATCH_CATEGORIES
from app.services.views import KEY_SPEC_FIELDS, MAX_KEY_SPECS, key_specs


def intent(**fields: object) -> QueryIntent:
    return QueryIntent.model_validate({"plan_steps": ["Tìm trong danh mục"], **fields})


# ---- ý định ----
def test_phone_is_a_tier_one_category() -> None:
    assert Category.phone in TIER1_CATEGORIES
    result = postprocess_intent(intent(category="phone", tier=1), "điện thoại samsung")
    assert (result.category, result.tier) == (Category.phone, 1)


def test_a_phone_intent_marked_tier_two_still_falls_back_to_other() -> None:
    result = postprocess_intent(intent(category="phone", tier=2), "x")
    assert (result.category, result.tier) == (Category.other, 2)


def test_nguyen_kim_is_a_searchable_site_for_phones() -> None:
    assert SiteKey.nguyenkim in SEARCHABLE_SITES
    result = postprocess_intent(
        intent(category="phone", tier=1, sites=["nguyenkim", "viettelstore"]), "điện thoại"
    )
    assert result.sites == [SiteKey.nguyenkim]  # Viettel Store không có dữ liệu (ADR-0011)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("ram_gb", "điện thoại RAM 8GB"),
        ("storage_gb", "điện thoại 256GB"),
        ("battery_mah", "điện thoại pin 5000mAh"),
    ],
)
def test_phone_memory_and_battery_default_to_at_least(field: str, message: str) -> None:
    given = intent(
        category="phone", tier=1, spec_filters=[SpecFilter(field=field, op="eq", value=5000)]
    )
    (spec,) = postprocess_intent(given, message).spec_filters
    assert (spec.field, spec.op) == (field, "gte")


def test_exact_wording_keeps_equality_for_phone_memory() -> None:
    given = intent(
        category="phone", tier=1, spec_filters=[SpecFilter(field="ram_gb", op="eq", value=8)]
    )
    (spec,) = postprocess_intent(given, "điện thoại RAM đúng 8GB").spec_filters
    assert spec.op == "eq"


def test_storage_in_terabytes_becomes_gigabytes_for_phones() -> None:
    given = intent(
        category="phone", tier=1, spec_filters=[SpecFilter(field="storage_gb", op="gte", value=1)]
    )
    (spec,) = postprocess_intent(given, "iPhone 1TB").spec_filters
    assert spec.value == 1000


def test_default_plan_and_clarification_name_phones() -> None:
    steps = default_plan_steps(intent(category="phone", tier=1))
    assert steps[0] == "Tìm điện thoại trong danh mục đã thu thập"
    assert "điện thoại" in DEFAULT_CLARIFICATION


# ---- LLM giả (E2E, ảnh chụp) ----
@pytest.mark.parametrize(
    ("text", "price_max", "price_min"),
    [
        ("điện thoại samsung dưới 15 triệu", 15_000_000, None),
        ("dien thoai tren 8 trieu", None, 8_000_000),
        ("iPhone 16 128GB", None, None),
        ("smartphone", None, None),
    ],
)
def test_fake_planner_routes_phones_to_tier_one(
    text: str, price_max: int | None, price_min: int | None
) -> None:
    result = plan_from_text(text)
    assert (result.category, result.tier, result.needs_clarification) == (Category.phone, 1, False)
    assert (result.price_max, result.price_min) == (price_max, price_min)


# ---- tool ----
def test_search_catalog_accepts_phones_but_still_not_other_categories() -> None:
    assert search_catalog.SearchCatalogArgs(category=Category.phone).category is Category.phone
    with pytest.raises(ValidationError):
        search_catalog.SearchCatalogArgs(category=Category.other)
    assert "phones" in search_catalog.DESCRIPTION


# ---- prompt ----
def test_planner_prompt_lists_phone_as_tier_one_with_its_spec_fields() -> None:
    prompt = render_planner_prompt()
    assert "`phone`" in prompt and "battery_mah" in prompt and "nguyenkim" in prompt
    assert "điện thoại…" not in prompt  # không còn liệt kê điện thoại ở nhóm tầng 2


# ---- dịch vụ ----
def test_phone_rematch_and_key_specs_are_configured() -> None:
    assert Category.phone in REMATCH_CATEGORIES
    assert KEY_SPEC_FIELDS[Category.phone] == (
        "ram_gb",
        "storage_gb",
        "chipset",
        "screen_in",
        "battery_mah",
        "os",
    )


def test_key_specs_of_a_phone_skip_missing_values_and_keep_the_order() -> None:
    specs = {"storage_gb": 256, "os": "Android", "ram_gb": 8, "screen_in": 6.7, "chipset": None}
    shown = key_specs(Category.phone, specs)
    assert list(shown) == ["ram_gb", "storage_gb", "screen_in", "os"]
    assert len(shown) <= MAX_KEY_SPECS


def test_frontend_key_spec_order_matches_the_backend() -> None:
    """`KEY_SPEC_ORDER` (frontend/src/features/catalog/specs.ts) lặp lại `KEY_SPEC_FIELDS`."""
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[3] / "frontend/src/features/catalog/specs.ts"
    block = re.search(r"KEY_SPEC_ORDER[^{]*\{(.*?)\n\}", source.read_text(encoding="utf-8"), re.S)
    assert block is not None
    frontend = {
        name: tuple(re.findall(r"'(\w+)'", fields))
        for name, fields in re.findall(r"(\w+): \[([^\]]*)\]", block.group(1))
    }
    assert frontend == {category.value: fields for category, fields in KEY_SPEC_FIELDS.items()}
