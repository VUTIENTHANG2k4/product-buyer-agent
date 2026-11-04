"""QA lượt việc nhỏ 7 (T5.8, BUG-S2-5): màu đứng sau "<màu> Switch" là màu vỏ hay tên switch.

Luật mới: màu thứ hai là màu vỏ khi là màu tiếng Việt, hoặc khi màu thứ nhất đứng ngay sau
hãng/dòng switch (`Gateron/MX/Cherry/Kailh/Cream…`); ngược lại nó là tên switch và nằm trong khóa.
"""

import itertools
import unicodedata

import pytest

from app.domain.enums import Category, SiteKey
from app.normalize.brand import detect_brand
from app.normalize.names import canonical_name, name_key
from tests.golden_support import real_titles

KEYBOARD = Category.keyboard


def key_of(title: str) -> tuple[str, ...]:
    return name_key(canonical_name(title, KEYBOARD), detect_brand(title))


def same_key(first: str, second: str) -> bool:
    return key_of(f"Bàn phím cơ {first}") == key_of(f"Bàn phím cơ {second}")


# ---------------------------------------------------------------- màu vỏ (bị bỏ khỏi khóa)
@pytest.mark.parametrize(
    "shell",
    [
        "Đen",
        "đen",
        "Den",
        "DEN",
        "đỏ",
        "Do",
        "Trắng",
        "Xám",
        "Hồng",
        "Vàng",
        "Tím",
        "Bạc",
        "Nâu",
        "Cam",
        "Kem",
        "Xanh",
        "Xanh Dương",
        "Xanh Lá",
        "xanh dương",
    ],
)
def test_vietnamese_shell_colour_after_a_named_switch_is_dropped_from_the_key(shell: str) -> None:
    assert same_key(f"Keychron K2 Gateron Red Switch {shell}", "Keychron K2 Gateron Red Switch")


@pytest.mark.parametrize("switch_word", ["Switch", "SW", "Sw", "sw", "switch", "SWITCH"])
def test_the_switch_word_spelling_does_not_change_the_shell_colour_rule(switch_word: str) -> None:
    title = f"Keychron K2 Gateron Red {switch_word} Black"

    assert key_of(f"Bàn phím cơ {title}") == key_of(
        f"Bàn phím cơ Keychron K2 Gateron Red {switch_word}"
    )
    assert key_of(f"Bàn phím cơ {title}") != key_of(
        f"Bàn phím cơ Keychron K2 Gateron Brown {switch_word}"
    )


@pytest.mark.parametrize("maker", ["Gateron", "Cherry", "MX", "Kailh", "Outemu", "JWK", "Cream"])
def test_english_shell_colour_after_a_known_switch_maker_colour_is_dropped(maker: str) -> None:
    with_shell = f"Keychron K2 {maker} Red Switch Black"

    assert same_key(with_shell, f"Keychron K2 {maker} Red Switch White")
    assert same_key(with_shell, f"Keychron K2 {maker} Red Switch")


@pytest.mark.parametrize(
    "line", ["Optical", "Box", "Jelly", "Ink", "Milky", "Crystal", "Silent", "Gateron", "Cherry MX"]
)
def test_every_switch_line_word_makes_the_next_colour_a_named_switch(line: str) -> None:
    assert same_key(f"Akko 3068 {line} Red Switch Black", f"Akko 3068 {line} Red Switch")


def test_a_different_first_colour_still_separates_models_whatever_the_shell_colour() -> None:
    assert not same_key(
        "Akko 3068 Gateron Red Switch Black", "Akko 3068 Gateron Brown Switch Black"
    )
    assert not same_key("Akko 3068 Gateron Red Switch Đen", "Akko 3068 Gateron Brown Switch Đen")


def test_the_shell_colour_may_equal_the_switch_colour() -> None:
    assert same_key("Akko 3068 Gateron Red Switch Red", "Akko 3068 Gateron Red Switch")


# ---------------------------------------------------------------- tên switch (giữ trong khóa)
@pytest.mark.parametrize(
    ("first", "second"),
    [
        # màu thứ nhất không đứng sau hãng/dòng switch và màu thứ hai là tiếng Anh: tên switch
        ("Akko 3068 Black Switch Red", "Akko 3068 Black Switch Blue"),
        ("Akko 3068 Black SW Red", "Akko 3068 Black SW Blue"),
        ("Akko 3068 Black sw Red", "Akko 3068 Black sw Brown"),
        ("Akko 3068 BLACK SWITCH RED", "Akko 3068 BLACK SWITCH BLUE"),
        ("Akko 3068 V2 Black Switch Red", "Akko 3068 V2 Black Switch Brown"),
        # "Switch" làm chữ đứng trước màu thứ nhất không phải là hãng switch
        ("Akko 3068 Switch Red Switch Black", "Akko 3068 Switch Red Switch White"),
        ("Akko 3068 Switch Red Switch Red", "Akko 3068 Switch Red Switch Blue"),
    ],
)
def test_second_english_colour_without_a_named_first_colour_is_the_switch_name(
    first: str, second: str
) -> None:
    assert not same_key(first, second)


def test_a_word_outside_the_colour_list_after_a_named_switch_stays_in_the_key() -> None:
    assert not same_key("Keychron K2 Gateron Red Switch Foo", "Keychron K2 Gateron Red Switch")
    assert not same_key(
        "Keychron K2 Gateron Red Switch Olive", "Keychron K2 Gateron Red Switch Coral"
    )


def test_a_colour_after_a_non_colour_word_that_follows_the_switch_is_a_shell_colour() -> None:
    assert same_key(
        "Keychron K2 Gateron Red Switch Pro Black", "Keychron K2 Gateron Red Switch Pro"
    )


def test_each_shell_colour_after_a_named_switch_is_dropped_but_a_third_word_is_kept() -> None:
    base = key_of("Bàn phím cơ Keychron K2 Gateron Red Switch")

    assert key_of("Bàn phím cơ Keychron K2 Gateron Red Switch Black Foo") == (*base, "foo")


# ---------------------------------------------------------------- tiêu đề ngắn / chỉ có switch
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Switch Red", ("switch", "red")),
        ("Red Switch", ("red", "switch")),
        ("Switch", ("switch",)),
        ("SW", ("sw",)),
        ("Red", ()),
        ("Black Switch Red", ("black", "switch", "red")),
        ("Red Switch Black", ("red", "switch", "black")),
        ("Switch Switch Red", ("switch", "switch", "red")),
        ("Switch Red Switch", ("switch", "red", "switch")),
        ("Switch Đen", ("switch", "den")),  # không có màu thứ nhất: luật cũ, giữ màu
        ("Switch Đỏ Switch", ("switch", "do", "switch")),
    ],
)
def test_very_short_titles_never_raise_and_keep_switch_names(
    title: str, expected: tuple[str, ...]
) -> None:
    assert name_key(title, "Unknown") == expected


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("", ""),
        (" ", ""),
        ("Red", "Red"),
        ("Switch", "Switch"),
        ("- Switch -", "Switch"),
        ("Switch /", "Switch"),
        ("/ Red Switch", "Red Switch"),
    ],
)
def test_degenerate_titles_give_a_name_without_error(title: str, name: str) -> None:
    assert canonical_name(title, KEYBOARD) == name


def test_repeated_switch_words_do_not_drop_a_colour_that_follows_the_second_one() -> None:
    # Hai chữ Switch liền nhau: không có "màu thứ nhất" ngay trước chữ Switch thứ hai nên màu sau
    # nó vẫn là tên switch.
    assert not same_key("Keychron K2 Switch Switch Red", "Keychron K2 Switch Switch Blue")


# ---------------------------------------------------------------- Unicode
@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_vietnamese_shell_colour_rule_is_independent_of_unicode_form(form: str) -> None:
    title = "Bàn phím cơ Keychron K2 Gateron Red Switch Xanh Dương"
    converted = unicodedata.normalize(form, title)  # type: ignore[arg-type]

    assert key_of(converted) == key_of("Bàn phím cơ Keychron K2 Gateron Red Switch")


# ---------------------------------------------------------------- khóa ổn định khi chuẩn hóa lại
SHELLS = ["Đen", "Black", "Trắng", "White", "Xanh Dương", ""]
HEADS = ["Keychron K2 Gateron Red", "Keychron K2 Cherry MX Brown", "Akko 3068 Cream Blue"]


@pytest.mark.parametrize("head", HEADS)
def test_name_key_of_the_canonical_name_is_stable_when_canonicalised_again(head: str) -> None:
    unstable = []
    for switch_word, shell in itertools.product(["Switch", "SW"], SHELLS):
        title = f"Bàn phím cơ {head} {switch_word} {shell}".strip()
        brand = detect_brand(title)
        once = canonical_name(title, KEYBOARD)
        twice = canonical_name(once, KEYBOARD)
        if name_key(once, brand) != name_key(twice, brand):
            unstable.append(title)

    assert unstable == []


@pytest.mark.parametrize("head", HEADS)
def test_shell_colours_of_the_same_model_all_share_one_canonical_key(head: str) -> None:
    keys = {
        key_of(f"Bàn phím cơ {head} Switch {shell}".strip())
        for shell in ["Đen", "Black", "Trắng", "White", "Hồng", "Pink", ""]
    }

    assert len(keys) == 1


# ---------------------------------------------------------------- dữ liệu thật
def test_real_keyboard_titles_with_switch_words_keep_a_stable_key() -> None:
    titles = [
        title
        for site in (SiteKey.gearvn, SiteKey.fptshop, SiteKey.anphat)
        for title in real_titles(site, KEYBOARD)
        if "switch" in title.lower() or " sw " in f" {title.lower()} "
    ]
    unstable = [
        title
        for title in titles
        if name_key(canonical_name(title, KEYBOARD), detect_brand(title))
        != name_key(canonical_name(canonical_name(title, KEYBOARD), KEYBOARD), detect_brand(title))
    ]

    assert titles
    assert unstable == []
