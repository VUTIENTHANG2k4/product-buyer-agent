"""QA small-fixes-6: tên switch dạng "<từ> <màu> <phiên bản>" (T5.10) ở các biên chữ hoa/thường,
Unicode, màu tiếng Việt, hãng/từ mô tả đứng đầu, nhiều cụm "switch", từ rất dài và hiệu năng.

Test `xfail(strict=True)` mã `BUG-S6-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import random
import re
import time
import unicodedata

import pytest

from app.normalize.specs.keyboard import extract_keyboard
from app.normalize.specs.types import SwitchType

_VERSION_OR_NUMBER = re.compile(r"^(?:v\d+|\d+(?:[.,]\d+)?)$", re.IGNORECASE)


def switch_name(title: str, raw: dict[str, str] | None = None) -> str | None:
    return extract_keyboard(title, raw or {}).switch_name


# ---------------------------------------------------------------- 1. chữ hoa/thường, độ rộng, NFD
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ Kailh Box white v2 switch", "Box white v2"),
        ("Bàn phím cơ Kailh Box WHITE v2 SWITCH", "Box WHITE v2"),
        ("bàn phím cơ kailh box white v2 switch", "box white v2"),
        ("Bàn phím cơ Kailh Box White V2 SwItCh", "Box White V2"),
        ("Bàn phím cơ Ｋａｉｌｈ Ｂｏｘ Ｗｈｉｔｅ Ｖ２ switch", "Box White V2"),
        ("Bàn phím cơ Kailh Box White V2 ｓｗｉｔｃｈ", "Box White V2"),
        ("Bàn phím cơ Kailh\tBox\nWhite V2 switch", "Box White V2"),
        ("Bàn phím cơ Kailh Box White V2　switch", "Box White V2"),
        ("Bàn phím cơ Kailh Box White V2 switch.", "Box White V2"),
        ("Bàn phím cơ Kailh Box White V2 switch-x", "Box White V2"),
        ("Bàn phím cơ Kailh Box White V2 switch/Red", "Box White V2"),
    ],
)
def test_case_width_and_whitespace_variants_give_the_same_three_word_name(
    title: str, expected: str
) -> None:
    assert switch_name(title) == expected


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_a_vietnamese_colour_gives_the_same_name_in_every_normal_form(form: str) -> None:
    title = unicodedata.normalize(form, "Bàn phím cơ Kailh Box Trắng V2 switch")  # type: ignore[arg-type]

    assert switch_name(title) == "Box Trắng V2"


@pytest.mark.parametrize("version", ["V1", "V2", "v2", "V10", "V99", "V100", "v007"])
def test_any_numeric_version_is_kept_as_the_last_word(version: str) -> None:
    assert switch_name(f"Bàn phím cơ Kailh Box White {version} switch") == f"Box White {version}"


@pytest.mark.parametrize("version", ["V", "V2a", "V2.0", "V-2", "Vx", "2V", "Ver2"])
def test_a_word_that_is_not_a_plain_version_never_triggers_the_three_word_branch(
    version: str,
) -> None:
    name = switch_name(f"Bàn phím cơ Kailh Box White {version} switch")

    assert name is None or name.split()[-1] == version  # nếu có tên thì phải kết thúc bằng từ gốc
    assert name is None or len(name.split()) <= 2


# ---------------------------------------------------------------- 2. màu tiếng Việt, không dấu
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bàn phím cơ Kailh Box Trang V2 switch", "Box Trang V2"),
        ("Bàn phím cơ Pegasus Trắng V2 switch", "Pegasus Trắng V2"),
        ("Bàn phím cơ Kailh Box TRẮNG V2 switch", "Box TRẮNG V2"),
    ],
)
def test_vietnamese_colour_in_the_middle_is_kept(title: str, expected: str) -> None:
    assert switch_name(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Đen White V2 switch",
        "Bàn phím cơ Xanh Trắng V2 switch",
        "Bàn phím cơ Trắng Đen V2 switch",
        "Bàn phím cơ ĐEN TRẮNG V2 switch",
        "Bàn phím cơ Den Trang V2 switch",
        "Bàn phím cơ Red White V2 switch",
        "Bàn phím cơ Silver Black V2 switch",
    ],
)
def test_two_colours_and_a_version_have_no_real_name(title: str) -> None:
    assert switch_name(title) is None


# ---------------------------------------------------------------- 3. từ đầu là hãng/mô tả/số model
@pytest.mark.parametrize(
    "first",
    [
        "Akko",
        "Keychron",
        "Logitech",
        "Razer",
        "Rapoo",
        "Dareu",
        "Corsair",
        "Asus",
        "SteelSeries",
        "E-Dra",
    ],
)
def test_a_keyboard_brand_before_a_colour_and_a_version_is_not_a_switch_name(first: str) -> None:
    assert switch_name(f"Bàn phím cơ {first} Black V2 switch") is None
    assert switch_name(f"Bàn phím cơ {first.upper()} Black V2 switch") is None
    assert switch_name(f"Bàn phím cơ {first.lower()} Black V2 switch") is None


@pytest.mark.parametrize("maker", ["Cherry", "Kailh", "Gateron", "Outemu", "Akko"])
def test_a_known_maker_before_colour_and_version_never_yields_a_nameless_or_version_only_result(
    maker: str,
) -> None:
    name = switch_name(f"Bàn phím cơ {maker} White V2 switch")

    assert name is None or name.endswith("White V2")


@pytest.mark.parametrize(
    "first",
    [
        "3068",
        "3068B",
        "5075B",
        "EK75",
        "MOD007",
        "G915",
        "V2",
        "V3",
        "2",
        "3.0",
        "Pro",
        "Plus",
        "Max",
        "Hotswap",
        "Gaming",
        "RGB",
        "TKL",
        "Mini",
        "Wireless",
        "Bluetooth",
        "Linear",
        "Clicky",
        "Tactile",
        "Optical",
        "Magnetic",
        "Compact",
        "Custom",
    ],
)
def test_a_model_number_version_or_descriptive_first_word_gives_no_name(first: str) -> None:
    assert switch_name(f"Bàn phím cơ {first} White V2 switch") is None
    assert switch_name(f"Bàn phím cơ {first.lower()} white v2 switch") is None


def test_the_descriptive_word_check_ignores_case_and_accents_of_the_first_word() -> None:
    assert switch_name("Bàn phím cơ TKL Trắng V2 switch") is None
    assert switch_name("Bàn phím cơ không dây Trắng V2 switch") is None


def test_a_bare_version_with_a_colour_stays_nameless_even_with_a_valid_looking_prefix() -> None:
    # "Plus" là từ chung: không được lấy làm tên dù đứng trước màu + phiên bản.
    assert switch_name("Bàn phím cơ Akko 3068B Plus White V2 switch") is None
    assert switch_name("Bàn phím cơ Akko V3 Pro Cream Yellow V2 switch") is None


# ---- 4. nhiều cụm "switch", bảng thông số
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kailh Box White V2 switch Gateron Red switch", "Box White V2"),
        ("Kailh Box White V2 switch switch", "Box White V2"),
        ("Kailh Box White V2 switch Hotswap", "Box White V2"),
        ("Gateron Red switch Kailh Box White V2 switch", "Gateron Red"),
        ("Kailh Box White V2 switch Kailh Box Red V3 switch", "Box White V2"),
    ],
)
def test_the_first_switch_phrase_decides_in_titles_and_in_the_table(
    text: str, expected: str
) -> None:
    assert switch_name(f"Bàn phím cơ {text}") == expected
    assert switch_name("Bàn phím cơ", {"Loại switch": text}) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Kailh Box White V2 switches",
        "Bàn phím cơ Kailh Box White V2-switch",
        "Bàn phím cơ Kailh Box White V2 - switch",
        "Bàn phím cơ Kailh Box White (V2) switch",
        "Bàn phím cơ Kailh Box White V2, switch",
        "Bàn phím cơ Kailh Box White V2: switch",
    ],
)
def test_punctuation_or_plural_between_the_name_and_switch_gives_no_three_word_name(
    title: str,
) -> None:
    assert switch_name(title) is None


def test_a_nameless_title_falls_back_to_the_table_and_a_named_title_beats_the_table() -> None:
    table = {"Switch": "Kailh Box White V2 switch"}

    assert switch_name("Bàn phím cơ Black V2 switch", table) == "Box White V2"
    assert switch_name("Bàn phím cơ Gateron Red switch", table) == "Gateron Red"


def test_the_table_label_name_alone_is_not_enough_for_a_name() -> None:
    # Nhãn "Switch" là tên cột, giá trị không chứa chữ "switch" nên không có tên.
    assert switch_name("Bàn phím cơ", {"Switch": "Kailh Box White V2"}) is None


def test_extracting_from_the_result_again_gives_the_same_name() -> None:
    name = switch_name("Bàn phím cơ Kailh Box White V2 switch")
    assert name is not None

    assert switch_name(f"Bàn phím cơ {name} switch") == name


def test_the_three_word_branch_does_not_disturb_the_other_keyboard_fields() -> None:
    specs = extract_keyboard("Bàn phím cơ Akko 3068B TKL Hotswap RGB Kailh Box White V2 switch", {})

    assert specs.switch_name == "Box White V2"
    assert specs.switch_type is SwitchType.mechanical
    assert specs.hot_swap is True


# ---------------------------------------------------------------- 5. nhãn rất dài, số từ, hiệu năng
@pytest.mark.parametrize(
    ("length", "found"), [(1, True), (39, True), (40, True), (41, False), (45, False), (200, False)]
)
def test_a_word_longer_than_forty_characters_is_not_taken_as_part_of_the_name(
    length: int, found: bool
) -> None:
    word = "x" * length

    name = switch_name(f"Bàn phím cơ {word} White V2 switch")

    assert (name == f"{word} White V2") is found
    assert found or name is None


@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_one_overlong_word_anywhere_in_the_window_never_yields_a_garbled_name(
    position: str,
) -> None:
    long = "w" * 60
    words = {
        "first": f"{long} White V2",
        "middle": f"Box {long} V2",
        "last": f"Box White {long}",
    }[position]

    name = switch_name(f"Bàn phím cơ {words} switch")

    assert name is None or len(name) <= 3 * 40 + 2
    assert name is None or long not in name


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cơ Kailh Box White V2" + " " * 5000 + "switch",
        "Bàn phím cơ " + "Black V2 " * 200 + "Box White V2 switch",
        "Bàn phím cơ " + "V2 " * 600 + "switch",
        "Bàn phím cơ " + "Black " * 300 + "V2 switch",
        "Bàn phím cơ " + "a-" * 900 + " switch",
        "Bàn phím cơ " + ("x" * 39 + " ") * 40 + "switch",
        "Bàn phím cơ " + "switch " * 300,
        "switch " * 300,
        " " * 1500 + "x switch",
        "x" * 1500 + " y switch",
    ],
)
def test_long_titles_with_repeated_colour_version_tokens_stay_fast(title: str) -> None:
    started = time.perf_counter()

    switch_name(title)

    assert time.perf_counter() - started < 1.5


def test_a_very_long_spec_table_value_is_cut_and_stays_fast() -> None:
    started = time.perf_counter()

    switch_name("Bàn phím cơ", {"Switch": "Black V2 " * 50_000 + "Box White V2 switch"})

    assert time.perf_counter() - started < 1.5


def test_random_phrases_never_give_an_empty_or_version_only_name() -> None:
    rng = random.Random(20261101)
    tokens = [
        "Box", "White", "V2", "v10", "Red", "Black", "Kailh", "Akko", "Gateron", "switch",
        "Switch", "3068", "K2", "Pro", "Plus", "-", "2.0", "Hotswap", "Trắng", "Đen", "TKL",
        "RGB", "Cherry", "MX", "Logitech", "Reaper", "x" * 50, "７", "　", "(V2)", "V2,",
    ]  # fmt: skip
    for _ in range(4000):
        title = " ".join(rng.choice(tokens) for _ in range(rng.randint(1, 8))) + " switch"

        name = switch_name(title)

        if name is None:
            continue
        words = name.split()
        assert words, title
        assert name == name.strip(), title
        assert not all(_VERSION_OR_NUMBER.match(word) for word in words), (title, name)
        assert len(words) <= 3 and len(name) <= 3 * 40 + 2, (title, name)
