"""QA small-fixes-4: giá trị yếu, `merge_specs`, `label_fields`, xung đột GPU (T5.4a).

Test `xfail(strict=True)` mã `BUG-S4-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import copy
import unicodedata
from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.extract import (
    extract_specs,
    is_weak,
    merge_specs,
    missing_required,
    specs_confidence,
)
from app.normalize.specs.laptop import cpu_is_family_only

LAPTOP = Category.laptop
CORE_TITLE = "Laptop Acer Aspire 7 A715 i5-12450H/16GB/512GB"


# ---- giá trị yếu ----
@pytest.mark.parametrize(
    "value",
    [
        "Intel Core i5",
        "Intel Core i7",
        "Ryzen 7",
        "AMD Ryzen 5",
        "Core 5",
        "Core Ultra 7",
        "Intel Core Ultra 5",
        "Intel Core i5 12th Gen",
        "Bộ vi xử lý Intel Core i5",
        "Apple Silicon",
        "intel core i3",
        "INTEL CORE I9",
    ],
)
def test_a_cpu_that_names_only_a_family_is_weak(value: str) -> None:
    assert cpu_is_family_only(value) is True
    assert is_weak(LAPTOP, "cpu_model", value) is True


@pytest.mark.parametrize(
    "value",
    [
        "i5-1235U",
        "Core i7-1355U",
        "Core Ultra 7 155H",
        "Core 5 120U",
        "Ryzen 7 7735HS",
        "Ryzen AI 9 HX 370",
        "Apple M3 Pro",
        "Snapdragon X Plus X1P-64-100",
        "Celeron N4500",
        "Pentium Gold 7505",
        "Intel Core i7-13700H",
        "AMD Ryzen 5 5500U",
    ],
)
def test_a_cpu_with_a_concrete_model_is_not_weak(value: str) -> None:
    assert cpu_is_family_only(value) is False
    assert is_weak(LAPTOP, "cpu_model", value) is False


@pytest.mark.parametrize("value", [None, 5, 1.5, True, [], ["Core i5"], {"a": 1}, ""])
def test_weak_check_ignores_values_that_are_not_cpu_strings(value: object) -> None:
    assert cpu_is_family_only(value) is False
    assert is_weak(LAPTOP, "cpu_model", value) is False


def test_weak_values_exist_only_for_the_laptop_cpu() -> None:
    for category in (Category.mouse, Category.keyboard, Category.headset, Category.phone):
        assert is_weak(category, "cpu_model", "Intel Core i5") is False
    assert is_weak(LAPTOP, "ram_gb", "Intel Core i5") is False
    assert is_weak(LAPTOP, "unknown_field", "Intel Core i5") is False


@pytest.mark.xfail(
    strict=True,
    reason="BUG-S4-3: 'Intel Core i3-N305' (tên CPU đầy đủ) bị coi là giá trị yếu",
)
def test_a_full_cpu_name_with_a_letter_prefixed_number_is_not_weak() -> None:
    assert cpu_is_family_only("Intel Core i3-N305") is False


def test_a_family_only_cpu_counts_as_missing_and_keeps_confidence_below_half() -> None:
    specs = {
        "cpu_model": "Intel Core i5",
        "gpu_model": "Integrated",
        "ram_gb": 16,
        "storage_gb": 512,
    }

    assert missing_required(LAPTOP, specs) == ("cpu_model",)
    assert specs_confidence(LAPTOP, specs) == 0.37
    assert specs_confidence(LAPTOP, {**specs, "cpu_model": "i5-1235U"}) == 1.0


# ---- merge_specs ----
def test_a_concrete_value_replaces_a_weak_one_but_never_the_other_way_round() -> None:
    assert merge_specs(LAPTOP, {"cpu_model": "Intel Core i5"}, {"cpu_model": "i5-1235U"}) == {
        "cpu_model": "i5-1235U"
    }
    assert merge_specs(LAPTOP, {"cpu_model": "i5-1235U"}, {"cpu_model": "Intel Core i7"}) == {
        "cpu_model": "i5-1235U"
    }


def test_two_weak_values_keep_the_existing_one() -> None:
    assert merge_specs(LAPTOP, {"cpu_model": "Core i5"}, {"cpu_model": "Core i3"}) == {
        "cpu_model": "Core i5"
    }


def test_two_concrete_values_keep_the_existing_one() -> None:
    merged = merge_specs(LAPTOP, {"cpu_model": "i5-1235U"}, {"cpu_model": "i7-13700H"})
    assert merged == {"cpu_model": "i5-1235U"}


def test_empty_new_values_never_erase_old_ones_and_empty_old_lists_are_filled() -> None:
    assert merge_specs(Category.mouse, {"connection": ["wired"]}, {"connection": []}) == {
        "connection": ["wired"]
    }
    assert merge_specs(Category.mouse, {"connection": []}, {"connection": ["wired"]}) == {
        "connection": ["wired"]
    }
    assert merge_specs(LAPTOP, {"cpu_model": "Core i5"}, {"cpu_model": None, "ram_gb": None}) == {
        "cpu_model": "Core i5"
    }


def test_merge_recomputes_gpu_rank_and_drops_keys_the_schema_does_not_know() -> None:
    merged = merge_specs(
        LAPTOP, {"gpu_model": "RTX 4060", "gpu_rank": 99, "bogus": 1}, {"ram_gb": 16, "other": 2}
    )

    assert merged == {"gpu_model": "RTX 4060", "gpu_rank": 40, "ram_gb": 16}


def test_stored_values_of_the_wrong_type_are_dropped_and_refilled_from_the_new_ones() -> None:
    merged = merge_specs(
        LAPTOP, {"ram_gb": "8", "storage_gb": -1}, {"ram_gb": 16, "storage_gb": 512}
    )

    assert merged == {"ram_gb": 16, "storage_gb": 512}


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        ({"cpu_model": "Core i5", "ram_gb": 8}, {"cpu_model": "i5-1235U", "ram_gb": 16}),
        ({"gpu_model": "RTX 4060"}, {"gpu_model": "RTX 4050", "is_gaming": True}),
        ({}, {"ram_gb": 16}),
        ({"ram_gb": 16}, {}),
    ],
)
def test_merge_is_idempotent_and_does_not_mutate_its_inputs(
    existing: dict[str, Any], new: dict[str, Any]
) -> None:
    existing_copy, new_copy = copy.deepcopy(existing), copy.deepcopy(new)

    once = merge_specs(LAPTOP, existing, new)

    assert existing == existing_copy and new == new_copy
    assert merge_specs(LAPTOP, once, new) == once
    assert merge_specs(LAPTOP, once, {}) == once


def test_category_without_a_schema_merges_plain_dicts() -> None:
    assert merge_specs(Category.other, {"a": 1}, {"a": 2, "b": 3}) == {"a": 1, "b": 3}


# ---- label_fields ----
def test_label_fields_is_empty_without_a_spec_table_or_when_it_repeats_the_title() -> None:
    assert extract_specs(LAPTOP, CORE_TITLE, None).label_fields == frozenset()
    assert extract_specs(LAPTOP, CORE_TITLE, {}).label_fields == frozenset()
    same = extract_specs(LAPTOP, CORE_TITLE, {"Dung lượng RAM": "16 GB"})
    assert same.specs["ram_gb"] == 16 and "ram_gb" not in same.label_fields


def test_label_fields_lists_the_fields_the_spec_table_changed_or_added() -> None:
    result = extract_specs(
        LAPTOP,
        CORE_TITLE,
        {"Dung lượng RAM": "32 GB", "Card đồ họa": "NVIDIA GeForce RTX 4050 6GB"},
    )

    assert result.specs["ram_gb"] == 32
    assert result.specs["gpu_model"] == "RTX 4050"
    assert {"ram_gb", "gpu_model", "gpu_rank", "gpu_vram_gb"} <= result.label_fields
    assert "cpu_model" not in result.label_fields and "storage_gb" not in result.label_fields


@pytest.mark.parametrize(
    "label",
    [
        "Card đồ họa",
        "Card do hoa",
        "CARD ĐỒ HỌA",
        unicodedata.normalize("NFD", "Card đồ họa"),
        "Card đồ họa",
    ],
)
def test_spec_table_labels_match_with_or_without_diacritics_and_in_any_unicode_form(
    label: str,
) -> None:
    result = extract_specs(LAPTOP, CORE_TITLE, {label: "NVIDIA GeForce RTX 4050 6GB"})

    assert result.specs["gpu_model"] == "RTX 4050"
    assert "gpu_model" in result.label_fields


# ---- GPU nhãn / tiêu đề ----
@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("Laptop ASUS TUF F15 i5-12500H/16GB/512GB/RTX 3050", "Intel UHD Graphics"),
        ("Laptop ASUS Vivobook X1504 i5-1235U/16GB/512GB/Intel UHD Graphics", "RTX 3050 4GB"),
        ("Laptop Acer Nitro 5 i5-12450H/16GB/512GB/GTX 1650", "AMD Radeon Graphics"),
        ("Laptop Lenovo IdeaPad 3 Ryzen 5 5500U/8GB/512GB/Intel Arc Graphics", "NVIDIA RTX 3050"),
    ],
)
def test_a_discrete_versus_integrated_clash_leaves_the_gpu_empty_and_missing(
    title: str, label: str
) -> None:
    result = extract_specs(LAPTOP, title, {"Card đồ họa": label})

    assert "gpu_model" not in result.specs
    assert "gpu_rank" not in result.specs and "gpu_vram_gb" not in result.specs
    assert "gpu_model" in result.missing
    assert "gpu_model" not in result.label_fields


def test_two_different_discrete_gpus_let_the_spec_table_win() -> None:
    result = extract_specs(
        LAPTOP,
        "Laptop ASUS TUF F15 i5-12500H/16GB/512GB/RTX 4060",
        {"Card đồ họa": "NVIDIA RTX 4050 6GB"},
    )

    assert (result.specs["gpu_model"], result.specs["gpu_rank"]) == ("RTX 4050", 30)
    assert result.specs["gpu_vram_gb"] == 6
    assert "gpu_model" in result.label_fields


def test_a_clash_does_not_mark_the_laptop_as_gaming_from_the_losing_side() -> None:
    result = extract_specs(
        LAPTOP,
        "Laptop ASUS Vivobook X1504 i5-1235U/16GB/512GB/Intel UHD Graphics",
        {"Card đồ họa": "RTX 3050 4GB"},
    )

    assert "is_gaming" not in result.specs


# ---- giá trị lạ trong bảng thông số ----
@pytest.mark.xfail(
    strict=True,
    reason="BUG-S4-4: raw_specs có giá trị không phải chuỗi làm extract_specs ném TypeError",
)
@pytest.mark.parametrize("value", [16, None, ["16 GB"], True, {"a": 1}])
def test_extract_specs_tolerates_non_string_spec_table_values(value: object) -> None:
    result = extract_specs(LAPTOP, CORE_TITLE, {"Dung lượng RAM": value})  # type: ignore[dict-item]

    assert result.specs["ram_gb"] == 16
