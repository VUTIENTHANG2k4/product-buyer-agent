"""QA lượt việc nhỏ 2 (T5.8): khóa tên, hãng và khối lượng chuột; tìm ghép sai và ghép hụt.

Dùng tiêu đề kiểu GearVN / FPT Shop / An Phát. Test đỏ do lỗi ứng dụng giữ bằng
`xfail(strict=True)` mã `BUG-S2-n`: XPASS báo đỏ, khi sửa xong thì gỡ dấu xfail.
"""

import time
import unicodedata
from typing import Any, Literal

import pytest

from app.domain.enums import Category, SiteKey
from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.extract import extract_specs
from app.normalize.matcher import Candidate, decide_match
from app.normalize.model_code import extract_model_code
from app.normalize.names import canonical_name, name_key
from app.normalize.specs.mouse import extract_mouse
from tests.golden_support import real_titles

LAPTOP, MOUSE, KEYBOARD, HEADSET = (
    Category.laptop,
    Category.mouse,
    Category.keyboard,
    Category.headset,
)


def key_of(title: str, category: Category) -> tuple[str, ...]:
    return name_key(canonical_name(title, category), detect_brand(title))


def merges(category: Category, first: str, second: str) -> bool:
    """`True` nếu matcher ghép `second` vào sản phẩm đã có từ `first` (đi qua cả chuẩn hóa)."""

    def view(title: str) -> tuple[str, str, str | None, dict[str, Any]]:
        return (
            detect_brand(title),
            canonical_name(title, category),
            extract_model_code(category, title),
            extract_specs(category, title, {}).specs,
        )

    brand_a, name_a, code_a, specs_a = view(first)
    brand_b, name_b, code_b, specs_b = view(second)
    if brand_a != brand_b:
        return False
    decision = decide_match(
        category, brand_b, code_b, name_b, specs_b, [Candidate(1, name_a, code_a, specs_a)]
    )
    return decision.product_id is not None


# ---------------------------------------------------------------- token chỉ có dấu câu
@pytest.mark.parametrize(
    "symbol", ["–", "—", "•", "&", "+", "...", "…", "®", "™", "★", "🔥", "~", "::", "//", "?!", "*"]
)
def test_a_token_made_only_of_punctuation_or_symbols_never_changes_the_key(symbol: str) -> None:
    base = key_of("Chuột Razer Viper V2 Pro", MOUSE)

    assert key_of(f"Chuột Razer Viper {symbol} V2 Pro", MOUSE) == base
    assert key_of(f"Chuột Razer Viper V2 Pro {symbol}", MOUSE) == base


@pytest.mark.parametrize("word", ["Pro+", "2+", "5G", "V2.1", "8K", "Mini", "SE", "X"])
def test_a_token_with_a_letter_or_digit_is_kept_in_the_key(word: str) -> None:
    assert key_of(f"Chuột Razer Viper {word}", MOUSE) != key_of("Chuột Razer Viper", MOUSE)


def test_a_title_made_only_of_symbols_keeps_a_non_empty_name_and_an_empty_key() -> None:
    assert canonical_name("– • +", MOUSE) == "– • +"
    assert name_key("– • +", UNKNOWN_BRAND) == ()


def test_an_empty_key_never_merges_two_different_products() -> None:
    assert not merges(MOUSE, "Chuột Razer – • +", "Chuột Razer ~ ®")


def test_plus_dock_accessory_word_still_separates_the_bundle() -> None:
    assert not merges(MOUSE, "Chuột Razer Viper V3 Pro + Mouse Dock", "Chuột Razer Viper V3 Pro")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            "Chuột Logitech G Pro X Superlight 2 (Đen) – 910-006630",
            "Chuột Logitech G Pro X Superlight 2 Đen",
        ),
        ("Chuột Razer Viper V3 Pro • Black", "Chuột Razer Viper V3 Pro Black"),
        ("Chuột Razer DeathAdder V3 Pro & Black", "Chuột Razer DeathAdder V3 Pro Trắng"),
        ("Chuột Logitech MX Master 3S – Graphite", "Chuột Logitech MX Master 3S Đen"),
    ],
)
def test_same_model_with_decoration_or_colour_still_merges(first: str, second: str) -> None:
    assert merges(MOUSE, first, second)


# ---------------------------------------------------------------- _is_part_code (≤ 3 cụm)
@pytest.mark.parametrize(
    "code",
    [
        "PMW920",  # 6 ký tự: ngưỡng dưới
        "pmw3389",  # chữ thường
        "PMW3389DM",  # 3 cụm
        "PAW3311DB",
        "HERO25K",
        "ABCDE1",
        "ABCDEFGHIJKL12",  # 14 ký tự: ngưỡng trên
        "（PMW3389）",  # ngoặc toàn chiều rộng (NFKC)
    ],
)
def test_sensor_style_codes_in_brackets_are_dropped(code: str) -> None:
    wrapped = code if code.startswith("（") else f"({code})"

    assert key_of(f"Chuột Logitech G Pro {wrapped}", MOUSE) == key_of("Chuột Logitech G Pro", MOUSE)


@pytest.mark.parametrize(
    "code",
    ["G502X", "WH1000XM5", "WF1000XM4", "S23FE", "ABCDEFGHIJKLM12", "WH-1000XM5", "PMW_3389"],
)
def test_short_long_or_many_group_names_in_brackets_are_kept(code: str) -> None:
    assert key_of(f"Tai nghe Sony ({code})", HEADSET) != key_of("Tai nghe Sony", HEADSET)


@pytest.mark.parametrize(
    ("category", "first", "second"),
    [
        (
            HEADSET,
            "Tai nghe Bluetooth Sony chống ồn (WHCH720N)",
            "Tai nghe Bluetooth Sony chống ồn (WHCH520N)",
        ),
        (MOUSE, "Chuột Logitech không dây (MXMASTER3S)", "Chuột Logitech không dây (MXMASTER3)"),
    ],
)
def test_bracketed_model_names_with_few_groups_still_separate_models(
    category: Category, first: str, second: str
) -> None:
    assert not merges(category, first, second)


def test_bracketed_names_with_four_groups_still_separate_models_end_to_end() -> None:
    assert not merges(
        HEADSET,
        "Tai nghe Bluetooth Sony chống ồn (WH1000XM5)",
        "Tai nghe Bluetooth Sony chống ồn (WH1000XM4)",
    )


# ---------------------------------------------------------------- màu vỏ sau "<màu> Switch"
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Keychron K2 V2 Gateron Red Switch Đen", "Keychron K2 V2 Gateron Red Switch Trắng"),
        ("Keychron K2 V2 Gateron Red SW Black", "Keychron K2 V2 Gateron Red SW White"),
        ("Keychron K2 V2 Gateron Red Switch Black", "Keychron K2 V2 Gateron Red Switch"),
        ("Akko 3068 V2 Cream Blue Switch Hồng", "Akko 3068 V2 Cream Blue Switch Trắng"),
        ("Akko 3068 V2 Cream Blue Switch Xanh Dương", "Akko 3068 V2 Cream Blue Switch"),
    ],
)
def test_shell_colour_after_a_named_switch_does_not_split_the_model(
    first: str, second: str
) -> None:
    assert merges(KEYBOARD, f"Bàn phím cơ {first}", f"Bàn phím cơ {second}")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Keychron K2 V2 Gateron Red Switch Đen", "Keychron K2 V2 Gateron Brown Switch Đen"),
        ("Keychron K2 Switch Red", "Keychron K2 Switch Brown"),
        ("Keychron K2 Red Switch", "Keychron K2 Brown Switch"),
        ("Akko 3068 Cream Yellow Switch Đen", "Akko 3068 Cream Blue Switch Đen"),
        ("Akko 3068 Jelly Pink Switch Đen", "Akko 3068 Jelly Purple Switch Đen"),
        ("Akko 3068 Silver Switch Đen", "Akko 3068 Pink Switch Đen"),
        ("Akko 3068 Optical Switch Red", "Akko 3068 Optical Switch Blue"),
        ("Akko 3068 Silent Switch Red", "Akko 3068 Silent Switch Black"),
        ("Akko 3068 Cherry MX Switch Red", "Akko 3068 Cherry MX Switch Blue"),
        ("Akko 3068 SW Red", "Akko 3068 SW Blue"),
    ],
)
def test_different_switches_never_merge_whatever_the_colour_word_order(
    first: str, second: str
) -> None:
    assert not merges(KEYBOARD, f"Bàn phím cơ {first}", f"Bàn phím cơ {second}")


@pytest.mark.xfail(
    strict=True,
    reason="BUG-S2-5: '<màu> Switch <màu>' luôn coi màu thứ hai là màu vỏ, nên 'Black Switch Red' "
    "và 'Black Switch Blue' (switch Red/Blue) bị ghép làm một; cần quyết định thiết kế "
    "(ví dụ chỉ coi là màu vỏ khi màu thứ hai là tiếng Việt)",
)
def test_colour_word_before_and_after_switch_with_english_names_is_ambiguous_not_merged() -> None:
    assert not merges(
        KEYBOARD,
        "Bàn phím cơ Akko 3068 Black Switch Red",
        "Bàn phím cơ Akko 3068 Black Switch Blue",
    )


# ---------------------------------------------------------------- detect_brand: dấu ngắt
@pytest.mark.parametrize(
    "title",
    [
        "Laptop: Dell Inspiron 15 3520",
        "Laptop:Dell Inspiron 15 3520",
        "Laptop/Dell Inspiron 15 3520",
        "Laptop,Dell Inspiron 15 3520",
        "Laptop; Dell Inspiron 15 3520",
        "Laptop ; ; Dell Inspiron 15 3520",
        "Laptop::Dell Inspiron 15 3520",
        "LAPTOP:DELL Inspiron 15 3520",
        "laptop/dell inspiron 15 3520",
        "Laptop：Dell Inspiron 15 3520",  # dấu hai chấm toàn chiều rộng
        "Laptop／Dell Inspiron 15 3520",  # gạch chéo toàn chiều rộng
        "Laptop,​Dell Inspiron 15 3520",  # ký tự rộng 0
        "[Mới 100%] Laptop: Dell Inspiron 15 3520",
        "🔥 Laptop/Dell Inspiron 15 3520",
        "Gaming/Laptop:Dell Inspiron 15 3520",
        "Máy tính xách tay: Dell Inspiron 15 3520",
    ],
)
def test_separators_between_type_words_and_brand_are_skipped(title: str) -> None:
    assert detect_brand(title) == "Dell"


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím: cho MacBook",
        "Bàn phím,cho MacBook Pro",
        "Chuột:cho MacBook",
        "Chuột, dành cho Dell",
        "Ốp lưng: iPhone 15",
        "Ốp/iPhone 15",
        "Túi: Laptop Dell 15.6",
        "Sạc: Dell 65W",
        "Bộ sạc/Dell 65W",
        "Cáp; Dell USB-C",
        "Chuột/phụ kiện cho Razer",
    ],
)
def test_accessory_and_connector_words_still_stop_the_search_after_a_separator(
    title: str,
) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


@pytest.mark.parametrize("title", ["", " ", "/", ",,,", ";:/", "Chuột:", ":", "Laptop,,, ;;"])
def test_titles_without_a_brand_or_only_separators_give_unknown(title: str) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


def test_a_brand_only_found_after_the_search_window_stays_unknown() -> None:
    assert (
        detect_brand("Laptop gaming mới nhất năm nay giá rẻ bất ngờ Dell Inspiron") == UNKNOWN_BRAND
    )


def test_a_separator_does_not_widen_the_skip_window() -> None:
    words = "/".join(["x"] * 12)

    assert detect_brand(f"Laptop/{words}/Dell") == UNKNOWN_BRAND


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_brand_and_name_key_do_not_depend_on_the_unicode_form(
    form: Literal["NFC", "NFD", "NFKC", "NFKD"],
) -> None:
    title = "Chuột không dây: Logitech G Pro X Superlight 2 – Đen (Hàng chính hãng)"
    converted = unicodedata.normalize(form, title)

    assert detect_brand(converted) == "Logitech"
    assert key_of(converted, MOUSE) == key_of(title, MOUSE)


@pytest.mark.parametrize("filler", ["ộ", "a", "/", ",", "́", " "])
def test_a_huge_title_stays_fast_for_brand_name_and_key(filler: str) -> None:
    title = "Chuột Razer Basilisk " + filler * 3_000_000
    started = time.perf_counter()

    brand = detect_brand(title)
    name = canonical_name(title, MOUSE)
    key_of(title, MOUSE)

    assert brand == "Razer" and name
    assert time.perf_counter() - started < 5


def test_a_huge_title_made_only_of_separators_is_fast_and_unknown() -> None:
    started = time.perf_counter()

    assert detect_brand("/," * 2_000_000) == UNKNOWN_BRAND
    assert time.perf_counter() - started < 5


# ---------------------------------------------------------------- đồng bộ detect_brand và tên
@pytest.mark.parametrize(
    ("category", "glued", "plain"),
    [
        (MOUSE, "Chuột:Razer Viper V2 Pro", "Chuột Razer Viper V2 Pro"),
        (MOUSE, "Chuột,Razer Viper V2 Pro", "Chuột Razer Viper V2 Pro"),
        (LAPTOP, "Laptop:Dell Inspiron 15 3520", "Laptop Dell Inspiron 15 3520"),
        (MOUSE, "Chuột Logitech G304:Lightspeed", "Chuột Logitech G304 Lightspeed"),
    ],
)
def test_name_key_agrees_with_detect_brand_about_glued_separators(
    category: Category, glued: str, plain: str
) -> None:
    assert key_of(glued, category) == key_of(plain, category)


# ---------------------------------------------------------------- khối lượng chuột: "50G"
@pytest.mark.parametrize(
    ("title", "grams"),
    [
        ("Chuột Razer Viper V3 Pro 8K 50G 54g", 54),
        ("Chuột Logitech G Pro X Superlight 63G", 63),
        ("Chuột Razer 2.4G 99g", 99),
        ("Chuột Razer 63G 2.4G Wireless 8K", 63),
        ("Chuột Razer 2.4GHz 63G", 63),
        ("Chuột Razer 63G-2.4G", 63),
        ("Chuột Razer 5.1G 63G 2.4G", 63),
        ("Chuột Razer 1G 2G 3G 70G", 70),
        ("Chuột Razer (63G)", 63),
        ("Chuột Razer [63G]", 63),
        ("Chuột Razer 63G.", 63),
        ("chuột razer 63g", 63),  # chữ thường vẫn là gam
        ("Chuột Razer 63 G", 63),
        ("Chuột Razer ６３Ｇ", 63),  # chữ số toàn chiều rộng
        ("Chuột Razer Viper 58.5G", 58),
        ("Chuột Razer Viper 58,5G", 58),
        ("Chuột 4G LTE 80G", 80),
        ("Chuột Razer 50G Wireless", 50),  # chỉ có "50G": vẫn là gam (phương án cuối)
    ],
)
def test_uppercase_g_numbers_are_only_a_last_resort_weight(title: str, grams: int) -> None:
    assert extract_mouse(title, {}).weight_g == grams


@pytest.mark.parametrize(
    "title",
    [
        "Chuột Razer 12G",
        "Chuột Razer 0G",
        "Chuột Razer 63GB",
        "Chuột Razer 1000G",
        "Chuột Razer 4.5G",
    ],
)
def test_values_outside_the_plausible_range_or_other_units_give_no_weight(title: str) -> None:
    assert extract_mouse(title, {}).weight_g is None


def test_a_labelled_weight_beats_the_title_even_when_the_title_has_uppercase_g() -> None:
    assert extract_mouse("Chuột Razer 63G", {"Trọng lượng": "70g"}).weight_g == 70


def test_an_unreadable_weight_label_falls_back_to_the_title() -> None:
    assert extract_mouse("Chuột Razer 63G", {"Trọng lượng": "rất nhẹ"}).weight_g == 63


def test_g_force_numbers_do_not_shadow_a_lowercase_weight_later_in_the_title() -> None:
    assert extract_mouse("Chuột Razer 50G 8K 100g", {}).weight_g == 100


def test_two_titles_differing_only_in_g_force_vs_weight_get_the_same_weight_spec() -> None:
    first = extract_mouse("Chuột Razer Viper V3 Pro 8K 50G 54g", {})
    second = extract_mouse("Chuột Razer Viper V3 Pro 8K 54g", {})

    assert first.weight_g == second.weight_g == 54


@pytest.mark.parametrize("filler", ["1G ", "9" * 20 + "G ", "1.1"])
def test_weight_parsing_of_a_huge_title_is_fast(filler: str) -> None:
    started = time.perf_counter()

    assert extract_mouse("Chuột " + filler * 100_000 + " 63G", {}).weight_g in (63, None)
    assert time.perf_counter() - started < 5


# ---------------------------------------------------------------- hồi quy trên dữ liệu thật
REAL_SITES = (SiteKey.gearvn, SiteKey.fptshop, SiteKey.anphat)
REAL = [
    (site, category, title)
    for site in REAL_SITES
    for category in (LAPTOP, MOUSE, KEYBOARD, HEADSET)
    for title in sorted(real_titles(site, category))
]


def test_the_fixtures_provide_real_titles_to_sweep() -> None:
    assert len(REAL) >= 100


def test_every_real_title_has_a_stable_brand_name_and_key_under_unicode_forms() -> None:
    unstable: list[str] = []
    for _, category, title in REAL:
        decomposed = unicodedata.normalize("NFD", title)
        if (
            detect_brand(decomposed) != detect_brand(title)
            or canonical_name(decomposed, category) != canonical_name(title, category)
            or key_of(decomposed, category) != key_of(title, category)
        ):
            unstable.append(title)

    assert unstable == []


def test_appending_decoration_tokens_never_changes_a_real_key_or_brand() -> None:
    changed: list[str] = []
    for _, category, title in REAL:
        for tail in (" – ", " • ", " + ", " & "):
            if key_of(title + tail, category) != key_of(title, category) or detect_brand(
                title + tail
            ) != detect_brand(title):
                changed.append(title + tail)

    assert changed == []


def test_every_real_title_has_a_non_empty_name_and_a_brand() -> None:
    bad = [
        title
        for _, category, title in REAL
        if not canonical_name(title, category) or not detect_brand(title)
    ]

    assert bad == []


def test_real_mouse_weights_are_within_the_plausible_range_or_absent() -> None:
    weights = {
        title: extract_mouse(title, raw).weight_g
        for site in REAL_SITES
        for title, raw in real_titles(site, MOUSE).items()
    }

    assert all(w is None or 20 <= w <= 300 for w in weights.values())
