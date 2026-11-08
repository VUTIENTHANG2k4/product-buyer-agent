"""QA X1: điện thoại ở tầng agent (ý định, LLM giả, tool, hiển thị gọn).

Test `xfail(strict=True)` mã `BUG-X1-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

from typing import Any

import pytest

from app.agent.fake_llm import plan_from_text
from app.agent.intent import postprocess_intent
from app.agent.tools import search_catalog
from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category, SiteKey
from app.services.views import MAX_KEY_SPECS, key_specs


def phone_intent(*filters: SpecFilter, **fields: Any) -> QueryIntent:
    return QueryIntent.model_validate(
        {
            "plan_steps": ["Tìm"],
            "category": "phone",
            "tier": 1,
            "spec_filters": list(filters),
            **fields,
        }
    )


def filters_after(message: str, *filters: SpecFilter) -> list[tuple[str, str, Any]]:
    result = postprocess_intent(phone_intent(*filters), message)
    return [(spec.field, spec.op, spec.value) for spec in result.spec_filters]


# ---- ý định ----
@pytest.mark.parametrize(
    ("message", "given", "expected"),
    [
        ("iPhone 2TB", SpecFilter(field="storage_gb", op="gte", value=2), 2000),
        ("điện thoại 1 TB", SpecFilter(field="storage_gb", op="gte", value=1), 1000),
        ("điện thoại 512GB", SpecFilter(field="storage_gb", op="gte", value=512), 512),
        ("điện thoại 16GB ram 1TB", SpecFilter(field="storage_gb", op="gte", value=1), 1000),
    ],
)
def test_phone_storage_unit_conversion(message: str, given: SpecFilter, expected: int) -> None:
    ((_, _, value),) = filters_after(message, given)
    assert value == expected


def test_terabyte_in_the_message_does_not_scale_ram_or_battery() -> None:
    result = filters_after(
        "điện thoại 1TB ram 8GB pin 5000mAh",
        SpecFilter(field="ram_gb", op="gte", value=8),
        SpecFilter(field="battery_mah", op="gte", value=5000),
    )
    assert result == [("ram_gb", "gte", 8), ("battery_mah", "gte", 5000)]


def test_exact_battery_wording_is_kept_but_plain_battery_means_at_least() -> None:
    given = SpecFilter(field="battery_mah", op="eq", value=5000)
    assert filters_after("điện thoại pin 5000mAh", given) == [("battery_mah", "gte", 5000)]
    assert filters_after("điện thoại pin chính xác 5000mAh", given) == [("battery_mah", "eq", 5000)]


def test_screen_size_filter_is_left_as_the_model_gave_it() -> None:
    given = SpecFilter(field="screen_in", op="lte", value=6.1)
    assert filters_after("điện thoại màn hình nhỏ dưới 6.1 inch", given) == [
        ("screen_in", "lte", 6.1)
    ]


def test_phone_intent_never_gets_an_invented_gpu_filter() -> None:
    assert filters_after("điện thoại chơi game như RTX 4060") == []


def test_unknown_sites_are_dropped_for_phones_but_nguyen_kim_and_fpt_are_kept() -> None:
    result = postprocess_intent(
        phone_intent(sites=["fptshop", "nguyenkim", "gearvn", "anphat", "viettelstore"]),
        "điện thoại",
    )
    assert SiteKey.nguyenkim in result.sites and SiteKey.fptshop in result.sites
    assert SiteKey.viettelstore not in result.sites


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-X1-13: câu giải thích 'Chưa hỗ trợ Shopee' luôn liệt kê (GearVN, FPT Shop, An Phát) "
        "dù điện thoại chỉ có ở FPT Shop và Nguyễn Kim"
    ),
)
def test_unsupported_site_note_names_the_sources_that_really_sell_phones() -> None:
    result = postprocess_intent(phone_intent(), "điện thoại samsung trên shopee")
    note = next(step for step in result.plan_steps if "Shopee" in step)
    assert "Nguyễn Kim" in note and "GearVN" not in note


# ---- LLM giả ----
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("tai nghe cho iphone", Category.headset),
        ("bàn phím cho điện thoại", Category.keyboard),
        ("laptop hay điện thoại", Category.laptop),
        ("ĐIỆN THOẠI", Category.phone),
        ("DIEN THOAI samsung", Category.phone),
    ],
)
def test_fake_planner_picks_the_first_matching_group(text: str, category: Category) -> None:
    assert plan_from_text(text).category is category


def test_fake_planner_asks_back_for_a_tablet_instead_of_guessing_a_phone() -> None:
    result = plan_from_text("máy tính bảng samsung")
    assert result.needs_clarification is True and result.category is None


# ---- tool ----
@pytest.mark.parametrize("bad", ["other", "tablet", "", None, 5])
def test_search_catalog_rejects_non_tier_one_categories(bad: Any) -> None:
    with pytest.raises(ValueError, match="category"):
        search_catalog.SearchCatalogArgs.model_validate({"category": bad})


# ---- hiển thị gọn ----
def test_key_specs_of_a_phone_ignore_empty_values_and_extra_fields() -> None:
    specs = {
        "ram_gb": None,
        "storage_gb": 128,
        "chipset": [],
        "screen_in": 6.1,
        "battery_mah": 0,
        "os": "iOS",
        "sim": "2 SIM",
    }
    # 0 là giá trị có thật trong dữ liệu: backend chỉ bỏ None và danh sách rỗng.
    assert list(key_specs(Category.phone, specs)) == [
        "storage_gb",
        "screen_in",
        "battery_mah",
        "os",
    ]


def test_key_specs_of_a_phone_with_every_field_is_capped() -> None:
    full = {
        "ram_gb": 8,
        "storage_gb": 128,
        "chipset": "A18",
        "screen_in": 6.1,
        "battery_mah": 3500,
        "os": "iOS",
    }
    assert len(key_specs(Category.phone, full)) == MAX_KEY_SPECS == 6


def test_key_specs_of_an_empty_phone_is_empty() -> None:
    assert key_specs(Category.phone, {}) == {}


def test_key_specs_of_a_category_without_a_declared_list_use_stored_order() -> None:
    assert list(key_specs(Category.other, {"b": 1, "a": 2})) == ["b", "a"]
