"""QA small-fixes-4: `switch_name` của bàn phím (tiêu đề có " - ", Unicode, rất dài)
và thời gian chạy regex trên chuỗi dài.

Test `xfail(strict=True)` mã `BUG-S4-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import time
import unicodedata

import pytest

from app.normalize.specs.keyboard import extract_keyboard

TIME_BUDGET_S = 1.5


def switch_name(title: str, raw_specs: dict[str, str] | None = None) -> str | None:
    return extract_keyboard(title, raw_specs or {}).switch_name


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ AKKO 3068 - Reaper switch", "Reaper"),
        ("Bàn phím cơ Akko 3068 – Reaper Switch", "Reaper"),
        ("Bàn phím Akko - - - Reaper Switch", "Reaper"),
        ("Bàn phím cơ e-dra EK387 Huano Blue switch - Hotswap", "Huano Blue"),
        ("Bàn phím cơ Gateron Milk White switch", "Milk White"),
        ("Bàn phím Logitech G Pro X GX Tactile switch", "GX Tactile"),
        ("Bàn phím cơ Jwick Blue Switch", "Jwick Blue"),
        ("Bàn phím cơ AKKO 3068 Cherry MX Brown Switch", "MX Brown"),
        ("BÀN PHÍM CƠ GAMING PEGASUS SWITCH", "PEGASUS"),
    ],
)
def test_switch_name_is_at_most_the_two_words_before_switch(title: str, expected: str) -> None:
    assert switch_name(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím Plus V3 Switch",
        "Bàn phím Hot-swap switch",
        "Bàn phím cơ Hotswap Switch",
        "Bàn phím Wireless Switch",
        "Bàn phím cơ Pro Max Switch",
        "Bàn phím cơ Đen Switch",
        "Bàn phím Gateron Milk White (switch)",
        "Switch",
        "",
        "   ",
        "-",
    ],
)
def test_switch_name_is_empty_when_only_generic_words_surround_the_word_switch(
    title: str,
) -> None:
    assert switch_name(title) is None


def test_switch_name_reads_composed_and_decomposed_vietnamese_the_same() -> None:
    composed = "Bàn phím cơ Đen Mượt Switch"
    decomposed = unicodedata.normalize("NFD", composed)

    assert switch_name(composed) == switch_name(decomposed) == "Mượt"


def test_switch_name_is_found_in_the_spec_table_when_the_title_has_none() -> None:
    assert switch_name("Bàn phím cơ AKKO 3068", {"Loại switch": "Gateron Red switch"}) == (
        "Gateron Red"
    )


def test_switch_name_prefers_the_title_over_the_spec_table() -> None:
    assert switch_name("Bàn phím cơ Reaper switch", {"Switch": "Gateron Red switch"}) == "Reaper"


def test_switch_name_never_returns_a_name_made_of_punctuation_or_versions_only() -> None:
    for title in ["Bàn phím V3 Switch", "Bàn phím v2 V3 switch", "Bàn phím _ switch", "- switch"]:
        assert switch_name(title) is None, title


def test_long_titles_with_many_switch_words_finish_quickly_and_name_is_short() -> None:
    title = "Bàn phím cơ " + "Akko Reaper switch " * 400
    started = time.perf_counter()

    result = switch_name(title)

    assert time.perf_counter() - started < TIME_BUDGET_S
    assert result is not None and len(result.split()) <= 2


COMBINING_ACUTE = chr(0x301)
PATHOLOGICAL_TITLES = {
    "one_long_word": "a" * 10_000,
    "single_letter_words": "a " * 10_000,
    "hyphen_chain": "a-" * 10_000,
    "switch_words": "switch " * 3_000,
    "dash_words": "- " * 10_000,
    "words_then_dash": ("a " * 400 + "-") * 20,
    "accented_word": chr(0xE9) * 10_000,
    "combining_marks": ("e" + COMBINING_ACUTE) * 10_000,
}


@pytest.mark.parametrize("title", PATHOLOGICAL_TITLES.values(), ids=PATHOLOGICAL_TITLES.keys())
def test_pathological_titles_run_in_linear_looking_time(title: str) -> None:
    started = time.perf_counter()

    extract_keyboard(title, {})

    assert time.perf_counter() - started < TIME_BUDGET_S


@pytest.mark.xfail(
    strict=True,
    reason="BUG-S4-7: so/ma model dung ngay truoc ten switch bi tinh vao ten switch",
)
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("B\u00e0n ph\u00edm c\u01a1 AKKO 3068 Reaper switch", "Reaper"),
        ("B\u00e0n ph\u00edm c\u01a1 Logitech G915 Tactile switch", "Tactile"),
        ("B\u00e0n ph\u00edm c\u01a1 DAREU EK75 Pegasus switch", "Pegasus"),
    ],
)
def test_a_model_number_just_before_the_switch_name_is_not_part_of_it(
    title: str, expected: str
) -> None:
    assert switch_name(title) == expected


def test_many_long_unbroken_spec_table_values_labelled_switch_finish_quickly() -> None:
    raw = {f"Switch {i}": "a" * 2000 for i in range(24)}
    started = time.perf_counter()

    extract_keyboard("Bàn phím cơ AKKO 3068", raw)

    assert time.perf_counter() - started < TIME_BUDGET_S


def test_long_unbroken_value_of_a_single_switch_label_is_still_fast() -> None:
    started = time.perf_counter()

    extract_keyboard("Bàn phím cơ AKKO 3068", {"Switch": "a" * 50_000})

    assert time.perf_counter() - started < TIME_BUDGET_S


@pytest.mark.parametrize(
    ("title", "switch_type"),
    [
        ("Bàn phím cơ AKKO 3068 - Reaper switch", "mechanical"),
        ("Bàn phím AKKO 3068 - HE Magnetic Switch", "magnetic"),
        ("Bàn phím cơ quang Wooting - Optical Switch", "optical"),
        ("Bàn phím Logitech K380 - Bluetooth", None),
    ],
)
def test_a_dash_in_the_title_does_not_change_the_switch_type(
    title: str, switch_type: str | None
) -> None:
    result = extract_keyboard(title, {}).switch_type

    assert (result.value if result else None) == switch_type
