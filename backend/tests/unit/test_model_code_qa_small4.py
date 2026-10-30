"""QA small-fixes-4: mã model (phụ kiện bỏ hint, laptop ưu tiên hint hợp lệ) với dữ liệu lệch và
tiếng Việt có dấu / không dấu / tổ hợp."""

import unicodedata

import pytest

from app.domain.enums import Category
from app.normalize.model_code import MAX_CODE_LENGTH, extract_model_code, is_strong_code

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
ACCESSORIES = [Category.mouse, Category.keyboard, Category.headset, Category.phone, Category.other]


@pytest.mark.parametrize("category", ACCESSORIES)
@pytest.mark.parametrize("hint", ["910-007735", "MX-MASTER-3S", "FX608JHR", "", "x" * 100, None])
def test_non_laptop_categories_never_return_a_model_code_from_a_hint(
    category: Category, hint: str | None
) -> None:
    assert extract_model_code(category, "Chuột Logitech G304 AL15-53P-56QH", hint) is None


@pytest.mark.parametrize("category", ACCESSORIES)
def test_non_laptop_categories_never_read_a_code_from_the_title(category: Category) -> None:
    assert extract_model_code(category, ACER) is None
    assert extract_model_code(category, "Logitech G304 910-005880 Black") is None


def test_one_mouse_in_two_colours_gets_no_code_even_when_each_colour_has_its_own_hint() -> None:
    black = extract_model_code(Category.mouse, "Chuột Logitech G304 Black", "910-005880")
    white = extract_model_code(Category.mouse, "Chuột Logitech G304 White", "910-005881")

    assert black is None and white is None


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("mock-asus-tuf16", "MOCK-ASUS-TUF16"),
        ("  FX608JHR  ", "FX608JHR"),
        ("FX 608 JHR", "FX608JHR"),
        ("fx608jhr-rv003w", "FX608JHR-RV003W"),
        ("A12", "A12"),
    ],
)
def test_a_laptop_hint_with_letters_and_digits_wins_and_is_normalised(
    hint: str, expected: str
) -> None:
    assert extract_model_code(Category.laptop, ACER, hint) == expected


@pytest.mark.parametrize(
    "hint",
    [
        None,
        "",
        "   ",
        "-",
        "N/A",
        "ABC",
        "12345678",
        "0000",
        "x" * (MAX_CODE_LENGTH + 1),
        "AB",
        "A1",
        "KhongCo",
    ],
)
def test_a_laptop_hint_without_both_letters_and_digits_or_out_of_range_falls_back_to_the_title(
    hint: str | None,
) -> None:
    assert extract_model_code(Category.laptop, ACER, hint) == "AL15-53P-56QH"


def test_a_hint_of_exactly_the_maximum_length_is_accepted() -> None:
    hint = "A1" * (MAX_CODE_LENGTH // 2)

    assert extract_model_code(Category.laptop, ACER, hint) == hint


@pytest.mark.parametrize(
    "title",
    [
        ACER,
        unicodedata.normalize("NFD", ACER),
        ACER.upper(),
        ACER.lower(),
        ACER.replace("AL15-53P-56QH", "AL15-53P-56QH,"),
        "[Giảm 10%/ Tặng chuột] " + ACER,
        "(Mới 100%) " + ACER,
        "Laptop gaming Acer Aspire Lite 15 AL15-53P-56QH | i5 | 8GB",
        "Laptop Acer Aspire Lite 15 AL15-53P-56QH/Core 5-120U/8GB/512GB",
        "Laptop Acer Aspire Lite 15 ＡＬ15-53P-56QH (Core 5-120U)",
    ],
)
def test_the_title_code_survives_case_tags_unicode_forms_and_separators(title: str) -> None:
    assert extract_model_code(Category.laptop, title) == "AL15-53P-56QH"


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        "Laptop",
        "Laptop gaming",
        "Laptop Acer Aspire Lite 15 (Core 5-120U/8GB/512GB)",
        "-" * 500,
    ],
)
def test_a_laptop_title_without_a_code_gives_none(title: str) -> None:
    assert extract_model_code(Category.laptop, title) is None


def test_a_very_long_title_is_handled_and_still_finds_the_code_in_its_head() -> None:
    assert extract_model_code(Category.laptop, ACER + " x" * 100_000) == "AL15-53P-56QH"


def test_a_code_longer_than_the_maximum_is_not_a_code() -> None:
    assert extract_model_code(Category.laptop, "Laptop Acer " + "AB1-" * 20) is None


@pytest.mark.parametrize(
    ("code", "strong"),
    [
        ("AL15-53P-56QH", True),
        ("83DV01MCVN", True),
        ("FX608JHR-RV003W", True),
        ("15IRX9", False),
        ("B13VFK", False),
        ("D44VLPA", False),
        ("", False),
        ("ABCDEFG", False),
        ("1234567", True),
        ("A1234", False),
    ],
)
def test_strong_codes_are_hyphenated_or_long_with_enough_digits(code: str, strong: bool) -> None:
    assert is_strong_code(code) is strong
