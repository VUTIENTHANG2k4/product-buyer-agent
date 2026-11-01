"""QA small-fixes-5: biên cho `_CORE_I` (BUG-S4-3), `label_values` (BUG-S4-4) và tên switch bàn
phím (BUG-S4-7).

Test `xfail(strict=True)` mã `BUG-S5-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import time
import unicodedata
from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.extract import extract_specs, is_weak, merge_specs
from app.normalize.specs.keyboard import extract_keyboard
from app.normalize.specs.laptop import cpu_is_family_only
from app.normalize.specs.parsing import label_values

LAPTOP = Category.laptop


def cpu(title: str, raw: dict[str, Any] | None = None) -> str | None:
    value = extract_specs(LAPTOP, title, raw or {}).specs.get("cpu_model")
    assert value is None or isinstance(value, str)
    return value


def switch_name(title: str, raw: dict[str, str] | None = None) -> str | None:
    return extract_keyboard(title, raw or {}).switch_name


# ---------------------------------------------------------------- 1. CPU dòng N (BUG-S4-3)
@pytest.mark.parametrize(
    "title",
    [
        "Laptop Acer Aspire Go 15 i3 N305/8GB",
        "Laptop Acer Aspire Go 15 i3-N305/8GB",
        "Laptop Acer Aspire Go 15 i3-n305/8GB",
        "Laptop Acer Aspire Go 15 I3-N305/8GB",
        "Laptop Acer Aspire Go 15 i3–N305/8GB",
        "Laptop Acer Aspire Go 15 i3 - N305/8GB",
        "Laptop Acer Aspire Go 15 Intel Core i3-N305 (8GB)",
        "Laptop Acer Aspire Go 15 Intel(R) Core(TM) i3-N305",
        "Laptop Acer Aspire Go 15 i3N305 8GB",
        "ｌａｐｔｏｐ Acer Ｉ３－Ｎ３０５ 8GB",
        "Laptop Acer Aspire Go 15 Core i3-N305, 8GB",
        "Laptop Acer Aspire Go 15 i3-N305.",
    ],
)
def test_intel_n_series_is_read_whatever_the_spacing_case_and_width(title: str) -> None:
    assert cpu(title) == "i3-N305"


def test_n_series_cpu_gets_the_intel_vendor() -> None:
    assert extract_specs(LAPTOP, "Laptop Acer i3-N300 8GB", {}).specs["cpu_vendor"] == "intel"


def test_decomposed_unicode_around_the_cpu_name_does_not_break_the_match() -> None:
    title = unicodedata.normalize("NFD", "Laptop Acer Aspire Go 15 màn hình đẹp i3-N305 8GB")

    assert cpu(title) == "i3-N305"


@pytest.mark.parametrize(
    "value",
    ["i3-N3050", "i3 N30", "i3-N3", "i3 N", "i5-NS305", "i3-N305U", "i3-N305X5", "i3-N3O5"],
)
def test_a_longer_or_shorter_n_number_is_not_cut_into_a_wrong_cpu(value: str) -> None:
    assert cpu(f"Laptop Acer {value} 8GB") is None


def test_legacy_celeron_n_series_keeps_its_own_name() -> None:
    assert cpu("Laptop Acer Aspire 1 Celeron N4020/4GB") == "Celeron N4020"
    assert cpu("Laptop Acer Aspire 1 Intel Celeron N3050") == "Celeron N3050"
    assert cpu("Laptop Acer Aspire 1 Pentium Silver N5030") == "Pentium N5030"


def test_a_bare_intel_n_chip_without_the_i_prefix_is_not_turned_into_an_i_series_cpu() -> None:
    result = cpu("Laptop Acer Aspire Go 15 Intel N100 i5 8GB")

    assert result is None


def test_classic_i_series_names_are_unchanged() -> None:
    assert cpu("Laptop Acer i5-12450H/16GB") == "i5-12450H"
    assert cpu("Laptop Acer i7 13700H") == "i7-13700H"
    assert cpu("Laptop Acer i9-14900HX 32GB") == "i9-14900HX"
    assert cpu("Laptop Acer Core i5-1235U") == "i5-1235U"
    assert cpu("Laptop Acer i5 Gen 12") is None


def test_the_first_cpu_in_the_title_wins_when_two_i_series_names_appear() -> None:
    assert cpu("Laptop i3-N305 i3-N300 i5-1235U") == "i3-N305"
    assert cpu("Laptop i5-1235U (so với i3-N305)") == "i5-1235U"


def test_core_ultra_still_beats_an_n_series_name_in_the_same_title() -> None:
    assert cpu("Laptop Acer i3 N305 and Core Ultra 5 125H") == "Core Ultra 5 125H"


def test_an_n_series_cpu_in_the_spec_table_is_read_when_the_title_has_none() -> None:
    assert cpu("Laptop Acer Aspire Go 15 8GB", {"CPU": "Intel Core i3-N305"}) == "i3-N305"
    assert cpu("Laptop Acer 8GB", {"Dòng CPU": "Intel Core i3", "CPU": "i3 N305"}) == "i3-N305"


def test_a_stored_weak_family_name_is_replaced_by_the_n_series_model() -> None:
    merged = merge_specs(LAPTOP, {"cpu_model": "Intel Core i3"}, {"cpu_model": "i3-N305"})

    assert merged["cpu_model"] == "i3-N305"
    assert is_weak(LAPTOP, "cpu_model", "Intel Core i3") is True
    assert is_weak(LAPTOP, "cpu_model", "i3-N305") is False


def test_a_stored_n_series_model_is_not_overwritten_by_a_weaker_name() -> None:
    merged = merge_specs(LAPTOP, {"cpu_model": "i3-N305"}, {"cpu_model": "Intel Core i3"})

    assert merged["cpu_model"] == "i3-N305"


def test_a_long_title_with_the_n_series_cpu_at_the_end_is_read_quickly() -> None:
    title = "Laptop " + "i3 " * 600 + "Acer i3-N305"
    started = time.perf_counter()

    result = cpu(title)

    assert time.perf_counter() - started < 1.0
    assert result is None or result.startswith("i3-")


@pytest.mark.parametrize("filler", [" ", "　"])
def test_cpu_name_check_on_a_value_with_a_long_run_of_spaces_stays_fast(filler: str) -> None:
    started = time.perf_counter()

    cpu_is_family_only("Intel Core i3" + filler * 10_000 + "x")

    assert time.perf_counter() - started < 0.5


# ---------------------------------------------------------------- 2. label_values (BUG-S4-4)
GARBAGE: list[Any] = [
    16,
    0,
    -1,
    3.5,
    float("nan"),
    float("inf"),
    True,
    False,
    None,
    b"16 GB",
    bytearray(b"16 GB"),
    ["16 GB"],
    ("16 GB",),
    {"value": "16 GB"},
    {"a": {"b": ["16 GB"]}},
    {"16 GB"},
    object(),
]


def test_label_values_keeps_only_string_values_and_skips_every_other_type() -> None:
    raw: dict[Any, Any] = {f"RAM {i}": v for i, v in enumerate(GARBAGE)}
    raw["RAM ok"] = "16 GB"

    assert list(label_values(raw, ("ram",))) == ["16 GB"]


def test_label_values_skips_entries_whose_label_is_not_a_string() -> None:
    raw: dict[Any, Any] = {1: "16 GB", None: "16 GB", ("RAM",): "16 GB", b"RAM": "16 GB"}
    raw["RAM"] = "8 GB"

    assert list(label_values(raw, ("ram",))) == ["8 GB"]


def test_label_values_of_a_table_made_only_of_odd_values_is_empty() -> None:
    raw: dict[Any, Any] = {f"RAM {i}": v for i, v in enumerate(GARBAGE)}

    assert list(label_values(raw, ("ram",))) == []


def test_label_values_still_skips_blank_and_limit_labels_for_string_values() -> None:
    raw = {"RAM": "   ", "RAM tối đa": "64 GB", "Nâng cấp RAM": "32 GB", "Dung lượng RAM": "8 GB"}

    assert list(label_values(raw, ("ram",))) == ["8 GB"]


def test_label_values_keeps_priority_order_of_aliases_with_odd_entries_in_between() -> None:
    raw: dict[Any, Any] = {"Tốc độ": 3200, "Bộ nhớ RAM": "16 GB", "RAM": None, "Dung lượng": "8 GB"}

    assert list(label_values(raw, ("ram", "dung luong"))) == ["16 GB", "8 GB"]


CLEAN_TABLES: dict[Category, tuple[str, dict[str, str]]] = {
    LAPTOP: (
        "Laptop Acer Aspire 7 A715",
        {
            "Dung lượng RAM": "16 GB",
            "Ổ cứng": "1TB SSD",
            "CPU": "Intel Core i5-12450H",
            "Tần số quét": "144Hz",
            "Màn hình": '15.6" IPS',
            "Trọng lượng": "2.1 kg",
            "Hệ điều hành": "Windows 11 Home",
            "Card đồ họa": "NVIDIA RTX 3050 4GB",
        },
    ),
    Category.mouse: (
        "Chuột Logitech G304",
        {"Trọng lượng": "99 g", "Kết nối": "Wireless 2.4GHz", "Số nút": "6", "Đèn LED": "RGB"},
    ),
    Category.keyboard: (
        "Bàn phím cơ AKKO 3068",
        {"Kết nối": "Bluetooth", "Loại switch": "Gateron Red switch", "Đèn nền": "RGB"},
    ),
    Category.headset: (
        "Tai nghe Razer Kraken",
        {"Kết nối": "USB", "Micro": "Có", "Driver": "40 mm"},
    ),
}


@pytest.mark.parametrize("category", list(CLEAN_TABLES))
def test_odd_values_under_alias_labels_change_nothing_in_the_extraction(
    category: Category,
) -> None:
    title, clean = CLEAN_TABLES[category]
    dirty: dict[str, Any] = dict(clean)
    for label in clean:
        for index, value in enumerate(GARBAGE):
            dirty[f"{label} (phụ {index})"] = value

    expected = extract_specs(category, title, clean)
    actual = extract_specs(category, title, dirty)

    assert expected.specs  # bảng sạch phải cho ra thông số thật, không phải so hai tập rỗng
    assert actual.specs == expected.specs
    assert actual.missing == expected.missing
    assert actual.confidence == expected.confidence


@pytest.mark.parametrize("category", list(CLEAN_TABLES))
def test_a_table_of_only_odd_values_equals_extraction_from_the_title_alone(
    category: Category,
) -> None:
    title, clean = CLEAN_TABLES[category]
    odd: dict[str, Any] = {
        label: GARBAGE[index % len(GARBAGE)] for index, label in enumerate(clean)
    }

    assert extract_specs(category, title, odd).specs == extract_specs(category, title, {}).specs


def test_a_nested_object_under_the_cpu_label_is_not_read_as_a_cpu() -> None:
    raw: dict[str, Any] = {"CPU": {"name": "Intel Core i5-12450H"}, "Dung lượng RAM": ["16 GB"]}

    specs = extract_specs(LAPTOP, "Laptop Acer Aspire 7 A715", raw).specs

    assert "cpu_model" not in specs
    assert "ram_gb" not in specs


def test_label_fields_ignore_odd_values() -> None:
    raw: dict[str, Any] = {"Dung lượng RAM": 16, "Ổ cứng": "512GB SSD"}

    result = extract_specs(LAPTOP, "Laptop Acer Aspire 7 A715 i5-12450H", raw)

    assert "ram_gb" not in result.label_fields
    assert "storage_gb" in result.label_fields


# ---------------------------------------------------------------- 3. tên switch (BUG-S4-7)
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ Cherry MX2A switch", "Cherry MX2A"),
        ("BÀN PHÍM CƠ CHERRY MX2A SWITCH", "CHERRY MX2A"),
        ("bàn phím cơ cherry mx2a brown switch", "mx2a brown"),
        ("Bàn phím Kailh Box V2 switch", "Box V2"),
        ("Bàn phím Gateron G Pro switch", "G Pro"),
        ("Bàn phím Akko CS Jelly Pink switch", "Jelly Pink"),
        ("Bàn phím Epomaker Flamingo 87 switch", "Flamingo 87"),
        ("Bàn phím Kailh Box Jade 2 switch", "Jade 2"),
        ("Bàn phím cơ Gateron KS3 switch", "Gateron KS3"),
        ("Bàn phím cơ Gateron KS-3 switch", "Gateron KS-3"),
        ("Bàn phím cơ Razer Green switch", "Razer Green"),
        ("Bàn phím cơ Kailh 80 switch", "Kailh 80"),
        ("Bàn phím cơ JWK 2022 switch", "JWK 2022"),
    ],
)
def test_real_switch_names_with_letters_and_digits_are_kept(title: str, expected: str) -> None:
    assert switch_name(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ ＡＫＫＯ ３０６８ Ｒｅａｐｅｒ ｓｗｉｔｃｈ", "Reaper"),
        ("bàn phím cơ akko 3068 reaper switch", "reaper"),
        ("BÀN PHÍM CƠ AKKO 3068 REAPER SWITCH", "REAPER"),
        ("Bàn phím cơ AKKO MOD007 Reaper switch", "Reaper"),
        ("Bàn phím cơ ACR75 Pegasus switch", "Pegasus"),
        ("Bàn phím cơ Wooting 60HE Lekker switch", "60HE Lekker"),
        ("Bàn phím Keychron K2 V2 Gateron Brown Switch", "Gateron Brown"),
        ("Bàn phím cơ AKKO 3068 Hotswap Reaper switch", "Reaper"),
        ("Bàn phím cơ AKKO 3068 CS Jelly switch", "CS Jelly"),
        ("Bàn phím cơ 3068 Reaper switch Gateron Red switch", "Reaper"),
    ],
)
def test_a_leading_model_number_is_dropped_whatever_the_case_width_or_neighbours(
    title: str, expected: str
) -> None:
    assert switch_name(title) == expected


def test_a_model_number_dropped_from_a_decomposed_title_gives_the_same_name() -> None:
    composed = "Bàn phím cơ AKKO 3068 Mượt Reaper switch"
    decomposed = unicodedata.normalize("NFD", composed)

    assert switch_name(decomposed) == switch_name(composed) == "Mượt Reaper"


def test_the_switch_label_in_the_spec_table_drops_the_model_number_too() -> None:
    assert switch_name("Bàn phím cơ", {"Switch": "3068 Reaper switch"}) == "Reaper"
    assert switch_name("Bàn phím cơ", {"Loại switch": "EK75 Pegasus switch"}) == "Pegasus"


def test_switch_name_in_the_title_wins_over_the_table_after_dropping_the_model() -> None:
    assert switch_name("AKKO 3068 Reaper switch", {"Switch": "Gateron Red switch"}) == "Reaper"


def test_only_the_first_switch_phrase_of_the_title_is_used() -> None:
    assert switch_name("Phím AKKO 3068 Reaper switch hoặc EK75 Pegasus switch") == "Reaper"


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ " + "AKKO 3068 " * 400 + "Reaper switch",
        "Bàn phím cơ " + "3068" * 5000 + " switch",
        "Bàn phím cơ " + "a1 " * 3000 + "switch",
        "Bàn phím cơ " + "Reaper-" * 2000 + "switch",
    ],
)
def test_long_titles_with_many_model_like_tokens_stay_fast(title: str) -> None:
    started = time.perf_counter()

    switch_name(title)

    assert time.perf_counter() - started < 1.5


@pytest.mark.parametrize("model", ["5075B", "3068B", "3098N", "5087S", "3061S"])
def test_a_model_number_ending_in_a_letter_is_not_part_of_the_switch_name(model: str) -> None:
    assert switch_name(f"Bàn phím cơ AKKO {model} Reaper switch") == "Reaper"


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ AKKO 3068 Black Switch",
        "Bàn phím cơ AKKO 3068 Pink switch",
        "Bàn phím cơ DAREU EK75 Pro switch",
        "Bàn phím cơ AKKO 3068 Hotswap switch",
    ],
)
def test_nothing_but_a_colour_or_generic_word_is_left_after_the_model_number_is_dropped(
    title: str,
) -> None:
    assert switch_name(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Gateron G Pro 3.0 switch",
        "Bàn phím cơ Gateron G Pro 2 switch",
        "Bàn phím cơ Outemu Blue 2 switch",
    ],
)
def test_a_switch_name_is_never_a_bare_number(title: str) -> None:
    name = switch_name(title)

    assert name is None or not name.replace(".", "").isdigit()


# ---------------------------------------------------------------- 4. màu + "V2" (T5.10)
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ Kailh Box White V2 switch", "Box White V2"),
        ("Bàn phím cơ KAILH BOX WHITE V2 SWITCH", "BOX WHITE V2"),
        ("Bàn phím cơ Kailh Box Red V3 switch", "Box Red V3"),
    ],
)
def test_a_switch_name_made_of_a_word_a_colour_and_a_version_keeps_all_three(
    title: str, expected: str
) -> None:
    assert switch_name(title) == expected


def test_a_switch_name_with_a_colour_and_a_version_is_read_from_the_spec_table_too() -> None:
    assert switch_name("Bàn phím cơ", {"Switch": "Kailh Box White V2 switch"}) == "Box White V2"


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Black V2 switch",
        "Bàn phím cơ Gaming Black V2 switch",
        "Bàn phím cơ Hotswap White V3 switch",
    ],
)
def test_a_colour_and_a_version_with_nothing_else_is_still_not_a_switch_name(title: str) -> None:
    assert switch_name(title) is None


def test_the_three_word_window_does_not_change_names_the_two_word_window_already_found() -> None:
    assert switch_name("Bàn phím Kailh Box V2 switch") == "Box V2"
    assert switch_name("Bàn phím Keychron K2 V2 Gateron Brown Switch") == "Gateron Brown"
    assert switch_name("Bàn phím Akko CS Jelly Pink switch") == "Jelly Pink"


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Rapoo Black V2 switch",
        "Bàn phím cơ RGB Black V2 switch",
        "Bàn phím cơ TKL White V2 switch",
        "Bàn phím cơ Mini Black V2 switch",
        "Bàn phím cơ Mechanical Black V2 switch",
        "Bàn phím cơ Clicky Purple V2 switch",
        "Bàn phím cơ Akko Black V2 switch",
    ],
)
def test_a_brand_or_keyboard_word_before_a_colour_and_a_version_is_not_a_switch_name(
    title: str,
) -> None:
    assert switch_name(title) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Red switch Blue switch", None),
        ("Akko switch Pegasus switch", "Akko"),
        ("Pegasus switch hotswap switch", "Pegasus"),
        ("Kailh switch Box White V2 switch", "Kailh"),
    ],
)
def test_the_first_switch_phrase_wins_when_the_word_switch_repeats_within_three_words(
    text: str, expected: str | None
) -> None:
    assert switch_name(f"Bàn phím cơ {text}") == expected
    assert switch_name("Bàn phím cơ", {"Switch": text}) == expected
