"""extract_specs / merge_specs / specs_confidence (app/normalize/extract.py)."""

import pytest

from app.domain.enums import Category
from app.normalize.extract import (
    INCOMPLETE_CEILING,
    extract_specs,
    merge_specs,
    missing_required,
    specs_confidence,
)
from app.normalize.specs import LaptopSpecs

FULL_LAPTOP = 'Laptop gaming Acer Aspire 7 (Core 5-210H/ RTX 3050 4GB/ 16GB/ 512GB/ 15.6" FHD)'
FULL_SPECS = {"cpu_model": "i5-1235U", "gpu_model": "RTX 3050", "ram_gb": 16, "storage_gb": 512}


def test_complete_laptop_has_full_confidence_and_nothing_missing() -> None:
    result = extract_specs(Category.laptop, FULL_LAPTOP)
    assert result.missing == ()
    assert result.confidence == 1.0
    assert result.specs["gpu_rank"] == 20
    assert result.specs["ram_gb"] == 16


def test_result_specs_have_no_null_values_and_validate_against_the_model() -> None:
    result = extract_specs(Category.laptop, FULL_LAPTOP)
    assert None not in result.specs.values()
    assert (
        LaptopSpecs.model_validate(result.specs).model_dump(mode="json", exclude_none=True)
        == result.specs
    )


def test_incomplete_laptop_reports_missing_fields_and_low_confidence() -> None:
    result = extract_specs(Category.laptop, "Laptop Acer Swift Air 14 (Core 5-320/ 12GB/ 512GB)")
    assert result.missing == ("gpu_model",)
    assert result.confidence == pytest.approx(0.37)
    assert result.confidence < 0.5


def test_nothing_extracted_gives_zero_confidence_and_all_required_missing() -> None:
    result = extract_specs(Category.laptop, "Laptop bí ẩn")
    assert result.specs == {}
    assert result.missing == ("cpu_model", "gpu_model", "ram_gb", "storage_gb")
    assert result.confidence == 0.0


def test_mouse_without_connection_is_missing_it() -> None:
    result = extract_specs(Category.mouse, "Chuột Logitech G102 Gen2 LightSync")
    assert result.missing == ("connection",)
    assert result.confidence == 0.0


def test_mouse_with_connection_is_complete() -> None:
    result = extract_specs(Category.mouse, "Chuột không dây Logitech G304")
    assert (result.missing, result.confidence) == ((), 1.0)


@pytest.mark.parametrize("category", [Category.phone, Category.other])
def test_categories_without_an_extractor_give_empty_specs(category: Category) -> None:
    result = extract_specs(category, "iPhone 15 Pro Max 256GB")
    assert (result.specs, result.confidence) == ({}, 0.0)


def test_confidence_is_below_the_threshold_whenever_a_field_is_missing() -> None:
    for specs in ({"connection": ["wired"]}, {"switch_type": "optical"}, {}):
        confidence = specs_confidence(Category.keyboard, specs)
        assert confidence <= INCOMPLETE_CEILING < 0.5


def test_empty_list_counts_as_missing() -> None:
    assert missing_required(Category.mouse, {"connection": []}) == ("connection",)
    assert missing_required(Category.mouse, {"connection": ["wired"]}) == ()


def test_extract_uses_raw_specs_table() -> None:
    result = extract_specs(
        Category.laptop,
        "Laptop Acer Aspire Lite 15 AL15-53P-56QH",
        {
            "Dung lượng RAM": "8 GB",
            "Dung lượng SSD": "512 GB",
            "Card đồ họa": "Intel® UHD Graphics",
            "Dòng CPU": "Core 5",
        },
    )
    # T5.4: "Dòng CPU: Core 5" chỉ là tên dòng, được giữ nhưng chưa đủ nên vẫn thiếu `cpu_model`.
    assert result.missing == ("cpu_model",)
    assert result.specs["cpu_model"] == "Core 5"
    assert result.specs["gpu_model"] == "Integrated"
    assert result.label_fields >= {"ram_gb", "storage_gb", "gpu_model", "cpu_model"}


@pytest.mark.parametrize(
    "value", ["Core 5", "Intel Core i5", "Ryzen 7", "AMD Ryzen™ 5", "Core Ultra 7", "Celeron"]
)
def test_cpu_family_without_model_number_counts_as_missing(value: str) -> None:
    assert missing_required(Category.laptop, {**FULL_SPECS, "cpu_model": value}) == ("cpu_model",)
    assert specs_confidence(Category.laptop, {**FULL_SPECS, "cpu_model": value}) < 0.5


@pytest.mark.parametrize(
    "value",
    [
        "i5-1235U",
        "Core 5 120U",
        "Core Ultra 7 155H",
        "Ryzen 7 7735HS",
        "Ryzen AI 9 HX 370",
        "Apple M2",
        "Celeron N4500",
        "MediaTek Kompanio 520",  # không phải tên dòng quen thuộc: không đoán là yếu
    ],
)
def test_full_cpu_names_are_not_weak(value: str) -> None:
    assert missing_required(Category.laptop, {**FULL_SPECS, "cpu_model": value}) == ()


def test_merge_replaces_a_cpu_family_with_a_full_cpu_name_but_not_the_reverse() -> None:
    family = {**FULL_SPECS, "cpu_model": "Core i5"}
    full = {**FULL_SPECS, "cpu_model": "i5-1235U"}
    assert merge_specs(Category.laptop, family, full)["cpu_model"] == "i5-1235U"
    assert merge_specs(Category.laptop, full, family)["cpu_model"] == "i5-1235U"
    assert merge_specs(Category.laptop, family, {"cpu_model": "Ryzen 5"})["cpu_model"] == "Core i5"


def test_label_fields_are_the_fields_the_table_changed_or_added() -> None:
    title = "Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB)"
    result = extract_specs(Category.laptop, title, {"Dung lượng RAM": "16 GB"})
    assert result.specs["ram_gb"] == 16
    assert "ram_gb" in result.label_fields
    assert "storage_gb" not in result.label_fields  # chỉ có trong tiêu đề
    assert extract_specs(Category.laptop, title).label_fields == frozenset()


def test_merge_fills_gaps_and_keeps_existing_values() -> None:
    existing = {"cpu_model": "i5-13420H", "ram_gb": 16}
    new = {"cpu_model": "i7-13700H", "ram_gb": 32, "storage_gb": 512, "gpu_model": "RTX 4050"}
    merged = merge_specs(Category.laptop, existing, new)
    assert merged["cpu_model"] == "i5-13420H"
    assert merged["ram_gb"] == 16
    assert merged["storage_gb"] == 512
    assert merged["gpu_model"] == "RTX 4050"


def test_merge_recomputes_gpu_rank_from_the_final_gpu_model() -> None:
    merged = merge_specs(Category.laptop, {"gpu_model": "RTX 3050", "gpu_rank": 999}, {})
    assert merged["gpu_rank"] == 20


def test_merge_ignores_empty_values_in_both_sides() -> None:
    merged = merge_specs(Category.mouse, {"connection": []}, {"connection": ["wired"]})
    assert merged == {"connection": ["wired"]}


def test_merge_for_category_without_model_is_a_plain_union() -> None:
    assert merge_specs(Category.other, {"a": 1}, {"a": 2, "b": 3}) == {"a": 1, "b": 3}


def test_merge_specs_drops_a_stored_value_of_the_wrong_type_instead_of_failing() -> None:
    merged = merge_specs(
        Category.laptop,
        {"ram_gb": "8GB", "storage_type": "nvme"},
        {"ram_gb": 16, "screen_in": 15.6},
    )
    assert merged["ram_gb"] == 16 and merged["screen_in"] == 15.6
