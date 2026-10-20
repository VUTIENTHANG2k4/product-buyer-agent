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
    assert result.missing == ()
    assert result.specs["gpu_model"] == "Integrated"


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
