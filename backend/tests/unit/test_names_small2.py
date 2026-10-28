"""T5.8: các sửa khóa tên/hãng/số đo của lượt việc nhỏ 2 không làm khóa quá lỏng."""

import pytest

from app.domain.enums import Category
from app.normalize.brand import detect_brand
from app.normalize.names import canonical_name, name_key
from app.normalize.specs.mouse import extract_mouse


def key_of(title: str, category: Category) -> tuple[str, ...]:
    brand = detect_brand(title)
    return name_key(canonical_name(title, category), brand)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Tai nghe Sony (WH1000XM5)", "Tai nghe Sony (WH1000XM4)"),
        ("Tai nghe Sony WH-1000XM5", "Tai nghe Sony WH-1000XM4"),
        ("Chuột Logitech G304", "Chuột Logitech G305"),
    ],
)
def test_different_models_never_share_a_name_key(first: str, second: str) -> None:
    assert key_of(first, Category.headset if "nghe" in first else Category.mouse) != key_of(
        second, Category.headset if "nghe" in second else Category.mouse
    )


@pytest.mark.parametrize("code", ["(PMW920)", "(PMW3389)", "(HERO25K)", "(910-006479)"])
def test_sensor_and_part_codes_in_brackets_are_still_dropped(code: str) -> None:
    with_code = key_of(f"Chuột Logitech G Pro {code}", Category.mouse)

    assert with_code == key_of("Chuột Logitech G Pro", Category.mouse)


def test_only_punctuation_tokens_are_dropped_not_words() -> None:
    assert key_of("Chuột Razer Viper V2 Pro – Đen", Category.mouse) == key_of(
        "Chuột Razer Viper V2 Pro", Category.mouse
    )
    assert key_of("Chuột Razer Viper V2 Pro Mini", Category.mouse) != key_of(
        "Chuột Razer Viper V2 Pro", Category.mouse
    )


@pytest.mark.parametrize(
    "title", ["Laptop; Dell Inspiron 15", "Laptop - Dell Inspiron 15", "Laptop/ Dell Inspiron 15"]
)
def test_separators_between_the_type_word_and_the_brand_are_skipped(title: str) -> None:
    assert detect_brand(title) == "Dell"


def test_an_accessory_after_a_separator_still_does_not_take_the_brand() -> None:
    assert detect_brand("Bộ sạc: laptop Dell 65W") == "Unknown"


def test_switch_name_colours_stay_in_the_key_while_the_shell_colour_goes() -> None:
    red = key_of("Bàn phím cơ Keychron K2 V2 Gateron Red Switch Đen", Category.keyboard)
    brown = key_of("Bàn phím cơ Keychron K2 V2 Gateron Brown Switch Đen", Category.keyboard)

    assert red != brown  # tên switch phân biệt mẫu
    assert red == key_of("Bàn phím cơ Keychron K2 V2 Gateron Red Switch Trắng", Category.keyboard)
    # "Switch Red" (màu đứng sau chữ switch, không có tên switch trước đó) vẫn là tên switch.
    assert key_of("Bàn phím cơ Akko 3068 Switch Red", Category.keyboard) != key_of(
        "Bàn phím cơ Akko 3068 Switch Blue", Category.keyboard
    )


@pytest.mark.parametrize(
    ("title", "grams"),
    [
        ("Chuột Razer Viper V3 Pro 8K 50G 54g", 54),
        ("Chuột Logitech G Pro X Superlight 63G", 63),  # chỉ có "63G": vẫn đọc là gam
        ("Chuột Razer 2.4G 99g", 99),
    ],
)
def test_uppercase_g_attached_to_a_number_is_only_a_last_resort_weight(
    title: str, grams: int
) -> None:
    assert extract_mouse(title, {}).weight_g == grams


def test_a_huge_title_does_not_slow_brand_detection() -> None:
    assert detect_brand("Chuột Razer Basilisk " + "ộ" * 3_000_000) == "Razer"
