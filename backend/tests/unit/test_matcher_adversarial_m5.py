"""Cặp tiêu đề dễ ghép nhầm (review M5): tên dòng máy dính số bị nhận là mã, màu switch bị bỏ."""

import pytest

from app.domain.enums import Category
from app.normalize.brand import detect_brand
from app.normalize.extract import extract_specs
from app.normalize.matcher import Candidate, decide_match
from app.normalize.model_code import extract_model_code, is_strong_code
from app.normalize.names import canonical_name


def merged(category: Category, existing_title: str, incoming_title: str) -> bool:
    """Offer `incoming_title` đến khi `existing_title` đã là Product 1 (đi qua chuẩn hóa thật)."""
    brand = detect_brand(existing_title)
    candidate = Candidate(
        1,
        canonical_name(existing_title, category),
        extract_model_code(category, existing_title),
        extract_specs(category, existing_title, {}).specs,
    )
    decision = decide_match(
        category,
        detect_brand(incoming_title),
        extract_model_code(category, incoming_title),
        canonical_name(incoming_title, category),
        extract_specs(category, incoming_title, {}).specs,
        [candidate] if brand == detect_brand(incoming_title) else [],
    )
    return decision.product_id == 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Laptop Lenovo ThinkPad E14 Gen10", "Laptop Lenovo ThinkPad E16 Gen10"),
        ("Laptop Lenovo ThinkPad E14 Gen10 i5 16GB", "Laptop Lenovo ThinkPad T14 Gen10 i5 16GB"),
        ("Laptop Samsung Galaxy Book4 Pro 14", "Laptop Samsung Galaxy Book4 Ultra 16"),
        ("Laptop Lenovo Yoga7 14", "Laptop Lenovo Yoga7 16 Pro"),
        ("Laptop Asus Zenbook14 OLED", "Laptop Asus Zenbook14 Flip"),
        ("Laptop Lenovo Legion 5 15IRX9", "Laptop Lenovo Legion Pro 5 15IRX9"),
        ("Laptop MSI Katana 15 B13VFK", "Laptop MSI Katana 17 B13VFK"),
        (
            "Laptop Lenovo Legion 5 15IRX9 (Core i7-14650HX/ 16GB/ 512GB/ RTX 4060)",
            "Laptop Lenovo Legion Pro 5 15IRX9 (Core i7-14650HX/ 16GB/ 512GB/ RTX 4060)",
        ),
    ],
)
def test_laptops_sharing_only_a_platform_or_series_token_are_not_merged(
    left: str, right: str
) -> None:
    assert not merged(Category.laptop, left, right)
    assert not merged(Category.laptop, right, left)


def test_weak_platform_code_is_not_merged_with_a_spec_less_listing() -> None:
    full = "Laptop Lenovo Legion 5 15IRX9 (Core i7-14650HX/ 16GB/ 512GB/ RTX 4060)"
    bare = "Laptop Lenovo Legion 5 15IRX9"
    assert not merged(Category.laptop, bare, full)
    assert not merged(Category.laptop, full, bare)


def test_strong_code_still_merges_across_sites_even_when_one_title_has_no_specs() -> None:
    full = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
    assert merged(Category.laptop, full, "Laptop Acer Aspire Lite 15 AL15-53P-56QH")


@pytest.mark.parametrize(
    "title",
    [
        "Laptop Lenovo ThinkPad E14 Gen10",
        "Laptop Samsung Galaxy Book4 Pro 14",
        "Laptop Lenovo Yoga7 14",
    ],
)
def test_series_names_with_a_number_are_not_model_codes(title: str) -> None:
    assert extract_model_code(Category.laptop, title) is None


@pytest.mark.parametrize(
    ("code", "strong"),
    [
        ("AL15-53P-56QH", True),
        ("FX610JH-TU008W", True),
        ("15-FA2452TX", True),
        ("83DV01MCVN", True),
        ("15IRX9", False),
        ("B13VFK", False),
        ("D44VLPA", False),
    ],
)
def test_is_strong_code(code: str, strong: bool) -> None:
    assert is_strong_code(code) is strong


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Bàn phím Corsair K70 RGB MX Red", "Bàn phím Corsair K70 RGB MX Blue"),
        ("Bàn phím cơ Akko 3068B Plus Red Axis", "Bàn phím cơ Akko 3068B Plus Blue Axis"),
        ("Bàn phím Keychron K2 Pro Gateron Red", "Bàn phím Keychron K2 Pro Gateron Brown"),
        ("Bàn phím cơ Akko 5075B Plus Cream Blue", "Bàn phím cơ Akko 5075B Plus Cream Yellow"),
    ],
)
def test_keyboards_differing_only_in_switch_colour_are_not_merged(left: str, right: str) -> None:
    assert not merged(Category.keyboard, left, right)
    assert not merged(Category.keyboard, right, left)


def test_switch_colour_stays_in_the_canonical_name() -> None:
    assert canonical_name("Bàn phím Corsair K70 RGB MX Red", Category.keyboard).endswith("MX Red")


def test_case_colour_of_the_same_keyboard_still_merges() -> None:
    assert merged(
        Category.keyboard,
        "Bàn phím cơ Akko 3068B Plus Black Gateron Red",
        "Bàn phím cơ Akko 3068B Plus Pink Gateron Red",
    )
