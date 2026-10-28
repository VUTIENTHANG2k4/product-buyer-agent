"""QA small-1: biên cho `detect_brand`, `canonical_name`, `name_key` (T5.5, T5.6).

Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-S1-n); khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail.
"""

import time
import unicodedata
from collections.abc import Callable
from itertools import combinations

import pytest

from app.domain.enums import Category
from app.normalize.brand import UNKNOWN_BRAND, detect_brand, find_brand
from app.normalize.names import canonical_name, name_key
from app.normalize.text import fold

LAPTOP, MOUSE, KEYBOARD, HEADSET = (
    Category.laptop,
    Category.mouse,
    Category.keyboard,
    Category.headset,
)


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


def key_of(title: str, category: Category) -> tuple[str, tuple[str, ...]]:
    """(hãng, khóa tên) đúng như pipeline tính: hãng từ tiêu đề, khóa từ tên chuẩn."""
    brand = detect_brand(title)
    return brand, name_key(canonical_name(title, category), brand)


def strip_accents(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in folded if not unicodedata.combining(c))


# ---- hai mẫu thật khác nhau không được cùng khóa tên ----
# Mỗi nhóm: danh sách mẫu; mỗi mẫu là các cách viết của cùng một sản phẩm.
KEYCHRON = "Bàn phím cơ Keychron K2 {} RGB Gateron Brown"
SUPERLIGHT = "Chuột Logitech G Pro X Superlight {}"
MODEL_GROUPS: dict[str, tuple[Category, list[list[str]]]] = {
    "keychron_layouts": (
        KEYBOARD,
        [
            [KEYCHRON.format("65%"), KEYCHRON.format("(65%)")],
            [KEYCHRON.format("75%"), KEYCHRON.format("(75%)")],
            [KEYCHRON.format("100%"), KEYCHRON.format("[100%]"), KEYCHRON.format("(100%)")],
            ["Bàn phím cơ Keychron K2 Pro 75% RGB Gateron Brown"],
            ["Bàn phím cơ Keychron K2 V2 75% RGB Gateron Brown"],
            ["Bàn phím cơ Keychron K2 75% RGB Gateron Red"],
            ["Bàn phím cơ Keychron K2 75% RGB Gateron Blue"],
        ],
    ),
    "logitech_codes": (
        MOUSE,
        [
            ["Chuột Logitech G304 Lightspeed", "Chuột Logitech (G304) Lightspeed"],
            ["Chuột Logitech G305 Lightspeed", "Chuột Logitech (G305) Lightspeed"],
            ["Chuột Logitech M331 Silent", "Chuột Logitech (M331) Silent"],
            ["Chuột Logitech G102"],
            ["Chuột Logitech G102 Lightsync"],
        ],
    ),
    "generations": (
        MOUSE,
        [
            [SUPERLIGHT.format("Gen1"), SUPERLIGHT.format("(Gen1)")],
            [SUPERLIGHT.format("Gen2"), SUPERLIGHT.format("(Gen2)")],
            [SUPERLIGHT.format("Gen 1")],
            [SUPERLIGHT.format("Gen 3")],
            [SUPERLIGHT.format("2")],
            ["Chuột Logitech G Pro X Superlight"],
        ],
    ),
    "razer_versions": (
        MOUSE,
        [
            ["Chuột Razer DeathAdder V2"],
            ["Chuột Razer DeathAdder V3"],
            ["Chuột Razer DeathAdder V2 Pro"],
            ["Chuột Razer DeathAdder V3 Pro"],
            ["Chuột Razer DeathAdder V2 Mini"],
            ["Chuột Razer DeathAdder Essential"],
            ["Chuột Razer DeathAdder V3 HyperSpeed"],
        ],
    ),
}


@pytest.mark.parametrize("group", sorted(MODEL_GROUPS))
def test_different_real_models_never_share_a_name_key_and_spellings_of_one_model_do(
    group: str,
) -> None:
    category, models = MODEL_GROUPS[group]
    keys = [{key_of(spelling, category) for spelling in spellings} for spellings in models]

    assert all(len(spellings) == 1 for spellings in keys)  # một mẫu, một khóa
    singles = [next(iter(spellings)) for spellings in keys]
    for first, second in combinations(range(len(singles)), 2):
        assert singles[first] != singles[second], (models[first], models[second])


# ---- cùng một mẫu, cách viết khác nhau, phải cùng (hãng, khóa) ----
SAME_MODEL_TITLES: list[tuple[Category, str]] = [
    (MOUSE, "Chuột không dây Logitech G Pro X Superlight 2 Màu Đen"),
    (KEYBOARD, "Bàn phím cơ không dây Akko 3068B Plus Xanh Dương"),
    (HEADSET, "Tai nghe chụp tai Sony WH-1000XM5 Màu Bạc"),
    (MOUSE, "Chuột Razer DeathAdder V3 Pro Trắng"),
    (MOUSE, "[Hot] Chuột Gaming Razer Viper V2 Pro (Đen) | GearVN"),
    (KEYBOARD, "Bàn phím cơ Keychron K2 Pro 75% RGB Gateron Brown Switch"),
    (HEADSET, "Tai nghe Bluetooth chống ồn JBL Tune 770NC Xanh Lá"),
]
VARIANTS: dict[str, Callable[[str], str]] = {
    "nfd": lambda t: unicodedata.normalize("NFD", t),
    "unaccented": strip_accents,
    "upper": str.upper,
    "lower": str.lower,
    "spaces": lambda t: "  " + t.replace(" ", "   ") + "  ",
    "nbsp": lambda t: t.replace(" ", " "),
    "zero_width": lambda t: t.replace(" ", " ​"),
    "fullwidth": lambda t: "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in t),
    "leading_tag": lambda t: "[Mới 100%] " + t,
    "leading_paren_tag": lambda t: "(Chính hãng) " + t,
    "many_tags": lambda t: "[Hot][Sale] (Mới) " + t,
    "store_suffix": lambda t: t + " | Cửa hàng ABC",
}


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", SAME_MODEL_TITLES, ids=[t[:24] for _, t in SAME_MODEL_TITLES])
def test_notation_noise_does_not_change_brand_or_name_key(
    case: tuple[Category, str], variant: str
) -> None:
    category, title = case

    assert key_of(VARIANTS[variant](title), category) == key_of(title, category)


@pytest.mark.parametrize(
    ("with_colour", "without"),
    [
        ("Chuột Razer Basilisk V3 Xanh", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Xanh Basilisk V3", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Basilisk V3 Xanh Lá", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Basilisk V3 Xanh Dương", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Basilisk V3 (Xanh Ngọc)", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Basilisk V3 Xanh Đen Trắng", "Chuột Razer Basilisk V3"),
        ("Chuột Razer Basilisk V3 Đen/Trắng", "Chuột Razer Basilisk V3"),
    ],
)
def test_colours_including_xanh_phrases_are_not_part_of_the_model(
    with_colour: str, without: str
) -> None:
    assert key_of(with_colour, MOUSE) == key_of(without, MOUSE)


def test_a_model_called_la_is_not_swallowed_as_a_colour_without_xanh() -> None:
    assert key_of("Chuột Razer Lá", MOUSE) != key_of("Chuột Razer", MOUSE)
    assert key_of("Chuột Razer Basilisk Dương", MOUSE) != key_of("Chuột Razer Basilisk", MOUSE)


def test_switch_colours_stay_in_the_key_but_shell_colours_do_not() -> None:
    red = key_of("Bàn phím Keychron K2 V2 Gateron Red", KEYBOARD)
    blue = key_of("Bàn phím Keychron K2 V2 Gateron Blue", KEYBOARD)
    shell = key_of("Bàn phím Keychron K2 V2 Đen Gateron Red", KEYBOARD)

    assert red != blue and red == shell


# ---- phụ kiện không nhận hãng ----
@pytest.mark.parametrize(
    "title",
    [
        "Bộ sạc laptop Dell 65W",
        "Sạc laptop Dell 65W",
        "Pin laptop Dell XPS 13",
        "Cáp sạc Dell USB-C",
        "Túi chống sốc laptop Dell 15.6 inch",
        "Balo laptop Dell Pro",
        "Ốp lưng iPhone 15 Pro",
        "Ốp lưng cho iPhone Apple",
        "Bàn phím cho MacBook",
        "Bàn phím dành cho iPad Logitech",
        "Chuột tương thích MacBook",
        "Đế tản nhiệt laptop Dell",
        "Hub chuyển đổi USB-C Dell",
        "Lót chuột Razer Goliathus",
        "Dock Dell WD19",
    ],
)
def test_accessories_do_not_get_the_brand_of_the_device_they_fit(title: str) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Laptop Dell Inspiron 15", "Dell"),
        ("LAPTOP DELL INSPIRON 15", "Dell"),
        ("laptop gaming asus tuf f15", "ASUS"),
        ("Chuột có dây Dell MS116", "Dell"),
        ("Hàng chính hãng Chuột Logitech G102", "Logitech"),
        ("Tai nghe HP HyperX Cloud II", "HyperX"),
        ("Tai nghe True Wireless Sony WF-1000XM5", "Sony"),
        ("Bộ bàn phím chuột Dell KM3322W", "Dell"),
        ("Chuột HP X1000", "HP"),
        ("Chuột HPE X1000", UNKNOWN_BRAND),
        ("Dellinspiron", UNKNOWN_BRAND),
        ("Bàn phím cơ e dra", UNKNOWN_BRAND),
        ("", UNKNOWN_BRAND),
        ("   ", UNKNOWN_BRAND),
        ("[Hot]", UNKNOWN_BRAND),
        ("★", UNKNOWN_BRAND),
    ],
)
def test_detect_brand_on_realistic_and_degenerate_titles(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


def test_find_brand_reach_is_bounded_and_stops_at_connectors() -> None:
    far = ["laptop", *["mo"] * 7, "dell"]  # hãng ở vị trí thứ 9: ngoài tầm
    near = ["laptop", *["mo"] * 6, "dell"]  # vị trí thứ 8: vừa đủ

    assert find_brand(far) is None
    assert find_brand(near) == (7, "Dell")
    assert find_brand(["chuot", "cho", "dell"]) is None
    assert find_brand([]) is None
    assert find_brand(["dell"] * 3) == (0, "Dell")


# ---- chuỗi suy biến không ném lỗi và không cho tên rỗng khi tiêu đề không rỗng ----
HOSTILE = [
    "|",
    " | ",
    " | | | ",
    "(",
    ")",
    "((((",
    "))))",
    "[[[[",
    "]]]]",
    "[]",
    "()",
    "[] ()",
    "(())",
    "[(])",
    "([)]",
    "Razer ((Basilisk))",
    "Razer [Hot [Sale]] Basilisk",
    "Razer Xanh) (Basilisk",
    "100%",
    "Mới 100%",
    "Xanh",
    "Xanh Lá",
    "Đen",
    "(Đen)",
    "910-007735",
    "(910-007735)",
    "-",
    "---",
    "\x00",
    "\x00Razer\x00 Basilisk",
    "​",
    "Razer​Basilisk",
    "﻿Razer Basilisk",
    "😀" * 50,
    "Ｒａｚｅｒ　Ｂａｓｉｌｉｓｋ",
    "R" * 5000,
    "Razer " + "Basilisk " * 3000,
]


@pytest.mark.parametrize("title", HOSTILE, ids=[repr(t[:20]) for t in HOSTILE])
@pytest.mark.parametrize("category", [LAPTOP, MOUSE, KEYBOARD, HEADSET, Category.other])
def test_hostile_titles_never_raise_and_stay_deterministic(title: str, category: Category) -> None:
    brand = detect_brand(title)
    name = canonical_name(title, category)
    key = name_key(name, brand)

    assert isinstance(name, str) and isinstance(key, tuple)
    assert (brand, name, key) == (
        detect_brand(title),
        canonical_name(title, category),
        name_key(name, brand),
    )
    if title.strip("\x00​﻿ ") and category is not LAPTOP:
        assert name  # "không rỗng: về cuối dùng nguyên tiêu đề đã gọn"


# ---- hiệu năng: tuyến tính với đầu vào lớn ----
@pytest.mark.parametrize(
    "payload",
    [
        "Chuột " * 200_000,
        "[" * 1_000_000,
        "(" * 1_000_000,
        "[a]" * 300_000,
        "(a " * 300_000,
        " | " * 300_000,
        " " * 1_000_000,
        "[" + " " * 1_000_000,
        "★" * 1_000_000,
    ],
    ids=["words", "open[", "open(", "tags", "open(a", "pipes", "spaces", "[+spaces", "stars"],
)
def test_names_are_linear_on_megabyte_inputs(payload: str) -> None:
    started = time.perf_counter()
    for category in (MOUSE, LAPTOP):
        brand = detect_brand(payload[:5000])
        name_key(canonical_name(payload, category), brand)

    assert time.perf_counter() - started < 5


def test_find_brand_is_linear_on_a_million_words() -> None:
    started = time.perf_counter()

    assert find_brand(["laptop"] * 1_000_000) is None
    assert time.perf_counter() - started < 5


@pytest.mark.parametrize("symbol", ["★", "🔥", "•", "※", "★★★"])
def test_leading_decoration_symbols_do_not_enter_the_name_key(symbol: str) -> None:
    title = "Chuột Razer DeathAdder V3 Pro Trắng"

    assert key_of(f"{symbol} {title}", MOUSE) == key_of(title, MOUSE)
    assert not canonical_name(f"{symbol} {title}", MOUSE).startswith(symbol)


@pytest.mark.parametrize(
    "title",
    [
        "🔥 [Hot] Laptop Dell Inspiron 15",
        "★ [Mới] Laptop Dell Inspiron 15",
        "- [Hot] Laptop Dell Inspiron 15",
        "★ (Chính hãng) Chuột Razer Basilisk",
    ],
)
def test_a_decoration_symbol_before_a_promo_tag_does_not_hide_the_brand(title: str) -> None:
    assert detect_brand(title) != UNKNOWN_BRAND


@pytest.mark.parametrize(
    "suffix", [" – Đen", " — Đen", " • Đen", " + Đen", " Black & White", " |", " - – Đen"]
)
def test_standalone_punctuation_tokens_are_not_part_of_the_name_key(suffix: str) -> None:
    base = "Chuột Razer Viper V2 Pro"

    assert key_of(base + suffix, MOUSE) == key_of(base, MOUSE)


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Laptop: Dell Inspiron 15", "Dell"),
        ("Chuột, Razer Basilisk V3", "Razer"),
        ("Laptop/Dell Inspiron 15", "Dell"),
    ],
)
def test_punctuation_glued_to_the_type_word_does_not_hide_the_brand(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


def test_detect_brand_only_looks_at_a_bounded_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    real_fold = fold

    def spy(text: str) -> str:
        seen.append(len(text))
        return real_fold(text)

    monkeypatch.setattr("app.normalize.brand._fold", spy)

    assert detect_brand("Chuột Razer Basilisk " + "ộ" * 1_000_000) == "Razer"
    assert max(seen) <= 10_000


def test_unhyphenated_model_names_in_brackets_keep_different_models_apart() -> None:
    first = key_of("Tai nghe Sony (WH1000XM5)", HEADSET)
    second = key_of("Tai nghe Sony (WH1000XM4)", HEADSET)

    assert first != second


@pytest.mark.parametrize("colour", ["Đen", "Trắng", "Black", "White", "Hồng"])
def test_shell_colour_after_a_named_switch_is_not_part_of_the_name_key(colour: str) -> None:
    base = "Bàn phím cơ Keychron K2 V2 Gateron Red Switch"

    assert key_of(f"{base} {colour}", KEYBOARD) == key_of(base, KEYBOARD)
