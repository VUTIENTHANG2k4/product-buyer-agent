"""QA M5: ghép mẫu (matcher) với dữ liệu thật và cặp dễ ghép nhầm.

Bổ sung cho `test_model_code_names_matcher.py`, `test_matcher_adversarial_m5.py` và
`test_golden_pairs.py`. Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-M5-n, xem báo cáo QA
M5); khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import itertools
import random
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import pytest

from app.domain.enums import Category, MatchMethod, SiteKey
from app.normalize.brand import detect_brand
from app.normalize.extract import extract_specs
from app.normalize.matcher import Candidate, MatchDecision, decide_match, specs_compatible
from app.normalize.model_code import extract_model_code
from app.normalize.names import canonical_name
from tests.golden_support import load_pairs, real_titles

LAPTOP, MOUSE, KEYBOARD, HEADSET = (
    Category.laptop,
    Category.mouse,
    Category.keyboard,
    Category.headset,
)
SITES = (SiteKey.gearvn, SiteKey.anphat, SiteKey.fptshop)
CATEGORIES = (LAPTOP, MOUSE, KEYBOARD, HEADSET)


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


@dataclass(frozen=True)
class View:
    """Một offer đã qua chuẩn hóa như `resolve_product` làm."""

    brand: str
    name: str
    code: str | None
    specs: dict[str, Any]


def view(category: Category, title: str, raw: dict[str, str] | None = None) -> View:
    return View(
        brand=detect_brand(title),
        name=canonical_name(title, category),
        code=extract_model_code(category, title),
        specs=extract_specs(category, title, raw or {}).specs,
    )


def decide(
    category: Category, existing: View, incoming: View, existing_id: int = 1
) -> MatchDecision:
    """`incoming` đến khi `existing` đã là một Product (chỉ lấy ứng viên cùng hãng như pipeline)."""
    candidates = (
        [Candidate(existing_id, existing.name, existing.code, existing.specs)]
        if existing.brand == incoming.brand
        else []
    )
    return decide_match(
        category, incoming.brand, incoming.code, incoming.name, incoming.specs, candidates
    )


def merges(category: Category, first: str, second: str) -> tuple[bool, bool]:
    """(second ghép vào first, first ghép vào second)."""
    a, b = view(category, first), view(category, second)
    return decide(category, a, b).product_id == 1, decide(category, b, a).product_id == 1


# ---- đối xứng thứ tự đến (dữ liệu fixture thật) ----
def test_arrival_order_never_changes_the_decision_over_every_real_fixture_pair() -> None:
    asymmetric: list[tuple[str, str, str]] = []
    checked = 0
    for category in CATEGORIES:
        views = {
            title: view(category, title, raw)
            for site in SITES
            for title, raw in real_titles(site, category).items()
        }
        for (title_a, a), (title_b, b) in itertools.combinations(views.items(), 2):
            if a.brand != b.brand:
                continue
            checked += 1
            ab, ba = decide(category, a, b), decide(category, b, a)
            if (ab.product_id, ab.method) != (ba.product_id, ba.method):
                asymmetric.append((category.value, title_a, title_b))

    assert checked > 500  # đủ lớn để phép thử có ý nghĩa
    assert asymmetric == []


def test_every_golden_pair_gives_the_same_verdict_in_both_arrival_orders() -> None:
    wrong: list[str] = []
    for pair in load_pairs():
        sides = []
        for side in (pair.a, pair.b):
            raw = {} if side.synthetic_from_title else real_titles(side.site, pair.category)
            raw_specs = raw if side.synthetic_from_title else raw[side.title]
            sides.append(view(pair.category, side.title, raw_specs))
        a, b = sides
        verdicts = (
            decide(pair.category, a, b).product_id == 1,
            decide(pair.category, b, a).product_id == 1,
        )
        if verdicts != (pair.expect == "merge",) * 2:
            wrong.append(pair.id)

    assert wrong == []


# ---- cặp dễ ghép nhầm: không bao giờ ghép (cả hai chiều) ----
LOOKALIKES = [
    # hậu tố Pro/SE/Mini/Max/Ultra/X
    (MOUSE, "Chuột Razer DeathAdder V3", "Chuột Razer DeathAdder V3 Pro"),
    (MOUSE, "Chuột Razer Viper V3 Pro", "Chuột Razer Viper V3 HyperSpeed"),
    (MOUSE, "Chuột Pulsar X2", "Chuột Pulsar X2 Mini"),
    (MOUSE, "Chuột Pulsar X2 Mini", "Chuột Pulsar X2 Max"),
    (MOUSE, "Chuột Pulsar X2 V2", "Chuột Pulsar X2 V2 Mini"),
    (MOUSE, "Chuột ATK X1 V2 Ultimate", "Chuột ATK X1 V2 Ultimate+"),
    (
        HEADSET,
        "Tai nghe gaming không dây Akko Verge S9",
        "Tai nghe gaming không dây Akko Verge S9 Ultra",
    ),
    (MOUSE, "Chuột Logitech G Pro X Superlight", "Chuột Logitech G Pro X Superlight 2"),
    (MOUSE, "Chuột Logitech MX Master 3", "Chuột Logitech MX Master 3S"),
    (MOUSE, "Chuột Logitech G304", "Chuột Logitech G305"),
    (MOUSE, "Chuột Logitech G102 Gen 2", "Chuột Logitech G102 Gen 1"),
    (HEADSET, "Tai nghe Razer BlackShark V2", "Tai nghe Razer BlackShark V2 X"),
    (HEADSET, "Tai nghe Razer BlackShark V2", "Tai nghe Razer BlackShark V2 Pro"),
    (HEADSET, "Tai nghe Razer BlackShark V2 Pro", "Tai nghe Razer BlackShark V2 SE"),
    (HEADSET, "Tai nghe Razer Kraken V3", "Tai nghe Razer Kraken V3 X"),
    (HEADSET, "Tai nghe HyperX Cloud III", "Tai nghe HyperX Cloud III Wireless"),
    (HEADSET, "Tai nghe SteelSeries Arctis Nova 7", "Tai nghe SteelSeries Arctis Nova 7X"),
    (HEADSET, "Tai nghe SteelSeries Arctis Nova 7", "Tai nghe SteelSeries Arctis Nova 7P"),
    (KEYBOARD, "Bàn phím Logitech MX Keys", "Bàn phím Logitech MX Keys S"),
    (KEYBOARD, "Bàn phím Logitech MX Keys S", "Bàn phím Logitech MX Keys Mini"),
    (KEYBOARD, "Bàn phím Corsair K70 RGB TKL", "Bàn phím Corsair K70 RGB Pro"),
    (KEYBOARD, "Bàn phím Logitech G915 TKL", "Bàn phím Logitech G915"),
    (KEYBOARD, "Bàn phím Razer Huntsman V2 TKL", "Bàn phím Razer Huntsman V2 Analog"),
    # phiên bản, bố cục
    (KEYBOARD, "Bàn phím Keychron K2 V2", "Bàn phím Keychron K2 Pro"),
    (KEYBOARD, "Bàn phím Keychron K2 65%", "Bàn phím Keychron K2 75%"),
    (
        KEYBOARD,
        "Bàn phím cơ ASUS ROG Falchion Ace 75 HE V2",
        "Bàn phím cơ ASUS ROG Falchion Ace 75 HE V2X",
    ),
    # tên switch khác
    (KEYBOARD, "Bàn phím cơ Akko 3068B Plus Red Axis", "Bàn phím cơ Akko 3068B Plus Blue Axis"),
    (KEYBOARD, "Bàn phím cơ Akko 3068 Red Switch", "Bàn phím cơ Akko 3068 Blue Switch"),
    (KEYBOARD, "Bàn phím cơ Akko 3068 Switch Red", "Bàn phím cơ Akko 3068 Switch Blue"),
    (KEYBOARD, "Bàn phím cơ Corsair K70 Cherry MX Red", "Bàn phím cơ Corsair K70 Cherry MX Silver"),
    (KEYBOARD, "Bàn phím cơ Akko 3068 Gateron Brown", "Bàn phím cơ Akko 3068 Gateron Yellow"),
    # laptop: năm, cấu hình, dòng máy
    (LAPTOP, "Laptop Dell XPS 13 2023", "Laptop Dell XPS 13 2024"),
    (
        LAPTOP,
        "Laptop Apple MacBook Air 13 M2 2022 8GB 256GB",
        "Laptop Apple MacBook Air 13 M3 2024 8GB 256GB",
    ),
    (
        LAPTOP,
        "Laptop Apple MacBook Air 13 M2 8GB 256GB",
        "Laptop Apple MacBook Air 13 M2 8GB 512GB",
    ),
    (
        LAPTOP,
        "Laptop Apple MacBook Air 13 M2 8GB 256GB",
        "Laptop Apple MacBook Air 15 M2 8GB 256GB",
    ),
    (
        LAPTOP,
        "Laptop Apple MacBook Air 13 M2 8GB 256GB",
        "Laptop Apple MacBook Pro 13 M2 8GB 256GB",
    ),
    (
        LAPTOP,
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 16GB/ 512GB/ RTX 3050)",
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 8GB/ 512GB/ RTX 3050)",
    ),
    (
        LAPTOP,
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 16GB/ 512GB/ RTX 3050)",
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN006W (i5-12500H/ 16GB/ 512GB/ RTX 3050)",
    ),
    (
        LAPTOP,
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 16GB/ 512GB/ RTX 3050)",
        "Laptop Asus TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 16GB/ 512GB/ RTX 4060)",
    ),
]


@pytest.mark.parametrize(("category", "first", "second"), LOOKALIKES)
def test_lookalike_models_are_never_merged_in_either_order(
    category: Category, first: str, second: str
) -> None:
    assert merges(category, first, second) == (False, False)


# ---- cùng mẫu, viết khác nhau: phải ghép (cả hai chiều) ----
SAME_MODEL = [
    (MOUSE, "Chuột Logitech G304 X Superlight", "CHUỘT LOGITECH G304 X SUPERLIGHT"),
    (MOUSE, "Chuột Logitech G304 X Superlight", "  Chuột \t Logitech\u00a0G304   X Superlight "),
    (
        MOUSE,
        "Chuột không dây Logitech G304 X Superlight",
        "Chuot khong day Logitech G304 X Superlight",
    ),
    (MOUSE, "Chuột Logitech G304 X Superlight", "Chuột Logitech G304 X Superlight (Chính hãng)"),
    (
        MOUSE,
        "Chuột Logitech G304 X Superlight Black",
        "[Hot] Chuột Logitech G304 X Superlight White",
    ),
    (MOUSE, "Chuột Logitech G304 X Superlight (Black)", "Chuột Logitech G304 X Superlight (White)"),
    (
        KEYBOARD,
        "Bàn phím cơ Akko 3068B Plus Black Gateron Red",
        "Bàn phím cơ Akko 3068B Plus Pink Gateron Red",
    ),
    (
        HEADSET,
        "Tai nghe Logitech PRO X3 Lightspeed Black",
        "Tai nghe Logitech G Pro X3 LightSpeed Magenta",
    ),
    (
        LAPTOP,
        "Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB)",
        "LAPTOP ACER ASPIRE LITE 15 al15-53p-56qh (core 5 120u/ 8gb/ 512gb)",
    ),
]


@pytest.mark.parametrize(("category", "first", "second"), SAME_MODEL)
def test_same_model_written_differently_merges_in_either_order(
    category: Category, first: str, second: str
) -> None:
    assert merges(category, first, second) == (True, True)


def test_nfd_and_nfc_titles_of_one_model_merge() -> None:
    title = "Chuột không dây HyperWork Silentium MS01 Đen"

    assert merges(MOUSE, title, unicodedata.normalize("NFD", title)) == (True, True)


# ---- lỗi đã tái hiện ----
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Bàn phím cơ Akko 3098 Kailh Box White", "Bàn phím cơ Akko 3098 Kailh Box Red"),
        ("Bàn phím cơ Akko 3098 Kailh Box White", "Bàn phím cơ Akko 3098 Kailh Box Brown"),
        ("Bàn phím cơ Akko 3068 Jelly Pink", "Bàn phím cơ Akko 3068 Jelly Purple"),
        ("Bàn phím cơ Akko 3068 Gateron Ink Black", "Bàn phím cơ Akko 3068 Gateron Ink Red"),
        ("Bàn phím cơ Akko 3068 Gateron Milky Yellow", "Bàn phím cơ Akko 3068 Gateron Milky Red"),
    ],
)
def test_switch_names_that_contain_a_colour_word_are_kept_apart(first: str, second: str) -> None:
    assert merges(KEYBOARD, first, second) == (False, False)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Chuột Logitech Lightspeed (G304)", "Chuột Logitech Lightspeed (G305)"),
        ("Chuột Logitech Silent (M331)", "Chuột Logitech Silent (M221)"),
        ("Chuột Logitech G102 (Gen2)", "Chuột Logitech G102 (Gen1)"),
    ],
)
@bug(
    "BUG-M5-3",
    "names._unwrap_parentheses coi mọi nhóm ngoặc một từ chữ+số 4–14 ký tự là 'mã phụ tùng' và "
    "xóa (names.py:162 `_is_part_code`); tên mẫu đặt trong ngoặc ('(G304)', '(M331)') cũng mất "
    "nên hai chuột khác mẫu có cùng khóa tên và bị ghép",
)
def test_model_names_written_in_parentheses_are_not_discarded_as_part_codes(
    first: str, second: str
) -> None:
    assert merges(MOUSE, first, second) == (False, False)


# ---- ứng viên đặc biệt ----
def candidate(product_id: int, name: str, code: str | None = None, **specs: Any) -> Candidate:
    return Candidate(product_id, name, code, specs)


def test_equal_names_pick_the_lowest_product_id_whatever_the_candidate_order() -> None:
    candidates = [candidate(pid, "Logitech G304 X Superlight") for pid in (7, 3, 9, 5)]
    shuffler = random.Random(2026)

    for _ in range(10):
        shuffler.shuffle(candidates)
        decision = decide_match(
            MOUSE, "Logitech", None, "Logitech G304 X Superlight", {}, candidates
        )
        assert (decision.product_id, decision.method) == (3, MatchMethod.fuzzy)


def test_only_the_candidate_with_the_same_model_name_is_chosen() -> None:
    candidates = [
        candidate(1, "Logitech G304"),
        candidate(2, "Logitech G304 X Superlight"),
        candidate(3, "Logitech G305"),
    ]

    decision = decide_match(MOUSE, "Logitech", None, "Logitech G304 X Superlight", {}, candidates)

    assert decision.product_id == 2


def laptop_specs(ram: int) -> dict[str, Any]:
    return extract_specs(LAPTOP, f"Laptop X (i5-13420H/ {ram}GB/ 512GB/ RTX 3050)", {}).specs


def test_same_code_with_other_ram_falls_through_to_the_codeless_twin_and_back() -> None:
    name = "Acer Aspire Lite 15 AL15-53P-56QH"
    p1 = Candidate(1, name, "AL15-53P-56QH", laptop_specs(8))
    p2 = Candidate(2, name, None, laptop_specs(16))

    sixteen = decide_match(LAPTOP, "Acer", "AL15-53P-56QH", name, laptop_specs(16), [p1, p2])
    eight = decide_match(LAPTOP, "Acer", "AL15-53P-56QH", name, laptop_specs(8), [p1, p2])
    thirty_two = decide_match(LAPTOP, "Acer", "AL15-53P-56QH", name, laptop_specs(32), [p1, p2])

    assert (sixteen.product_id, sixteen.method, sixteen.code_taken) == (2, MatchMethod.fuzzy, True)
    assert (eight.product_id, eight.method) == (1, MatchMethod.model_code)
    assert (thirty_two.product_id, thirty_two.method, thirty_two.code_taken) == (
        None,
        MatchMethod.new,
        True,
    )


def test_two_different_codes_never_merge_even_with_identical_names_and_specs() -> None:
    name = "Acer Aspire Lite 15"
    existing = Candidate(1, name, "AL15-53P-56QH", laptop_specs(8))

    decision = decide_match(LAPTOP, "Acer", "AL15-410P-R1W8", name, laptop_specs(8), [existing])

    assert decision.product_id is None and decision.code_taken is False


def test_incoming_code_can_still_join_a_codeless_product_with_the_same_name() -> None:
    name = "Acer Aspire Lite 15 AL15-53P-56QH"
    existing = Candidate(1, name, None, laptop_specs(8))

    decision = decide_match(LAPTOP, "Acer", "AL15-53P-56QH", name, laptop_specs(8), [existing])

    assert (decision.product_id, decision.method) == (1, MatchMethod.fuzzy)


def test_unknown_brand_merges_only_on_the_same_model_code() -> None:
    same_name = [candidate(1, "Infinity Shadow")]
    with_code = [candidate(1, "Infinity Shadow", "ISH-100")]

    by_name = decide_match(MOUSE, "Unknown", None, "Infinity Shadow", {}, same_name)
    by_code = decide_match(MOUSE, "Unknown", "ISH-100", "Other Name", {}, with_code)
    by_other_code = decide_match(MOUSE, "Unknown", "ISH-200", "Infinity Shadow", {}, with_code)

    assert by_name.product_id is None
    assert (by_code.product_id, by_code.method) == (1, MatchMethod.model_code)
    assert by_other_code.product_id is None


@pytest.mark.parametrize(
    "stored",
    [{}, {"connection": None}, {"connection": []}],
    ids=["empty-specs", "none", "empty-list"],
)
def test_candidate_without_required_specs_still_merges_accessories_by_name(
    stored: dict[str, Any],
) -> None:
    decision = decide_match(
        MOUSE,
        "Logitech",
        None,
        "Logitech G304",
        {"connection": ["wireless_2_4"]},
        [Candidate(1, "Logitech G304", None, stored)],
    )

    assert decision.product_id == 1


def test_laptop_without_specs_merges_only_through_a_strong_code() -> None:
    name = "Acer Aspire Lite 15 AL15-53P-56QH"
    spec_less = Candidate(1, name, None, {})

    by_name = decide_match(LAPTOP, "Acer", None, name, laptop_specs(8), [spec_less])
    by_code = decide_match(
        LAPTOP,
        "Acer",
        "AL15-53P-56QH",
        name,
        laptop_specs(8),
        [Candidate(1, name, "AL15-53P-56QH", {})],
    )

    assert by_name.product_id is None
    assert (by_code.product_id, by_code.method) == (1, MatchMethod.model_code)


def test_list_specs_are_compared_as_sets_and_none_means_unknown() -> None:
    both = ["wired", "bluetooth"]
    assert specs_compatible(KEYBOARD, {"connection": both}, {"connection": both[::-1]})
    assert not specs_compatible(KEYBOARD, {"connection": ["wired"]}, {"connection": both})
    assert specs_compatible(
        KEYBOARD, {"connection": ["wired"], "switch_type": None}, {"connection": ["wired"]}
    )
    assert not specs_compatible(
        KEYBOARD,
        {"connection": ["wired"], "switch_type": "optical"},
        {"connection": ["wired"], "switch_type": "mechanical"},
    )


# ---- dữ liệu đã lưu hỏng ----
@pytest.mark.parametrize(
    "stored",
    [
        {"connection": "wired"},
        {"connection": 5},
        {"connection": {}},
        {"connection": [None]},
        {"connection": ["wireless_2_4", "wireless_2_4"]},
    ],
    ids=["string", "int", "dict", "list-with-none", "duplicate-values"],
)
def test_malformed_stored_scalar_or_flat_specs_never_crash_the_matcher(
    stored: dict[str, Any],
) -> None:
    decision = decide_match(
        MOUSE,
        "Logitech",
        None,
        "Logitech G304",
        {"connection": ["wireless_2_4"]},
        [Candidate(1, "Logitech G304", None, stored)],
    )

    assert decision.method in {MatchMethod.fuzzy, MatchMethod.new}


@pytest.mark.parametrize(
    "stored",
    [{"connection": [["a"]]}, {"connection": [{"x": 1}]}],
    ids=["nested-list", "dict-in-list"],
)
def test_malformed_nested_stored_specs_do_not_raise(stored: dict[str, Any]) -> None:
    decision = decide_match(
        MOUSE,
        "Logitech",
        None,
        "Logitech G304",
        {"connection": ["wireless_2_4"]},
        [Candidate(1, "Logitech G304", None, stored)],
    )

    assert decision.method in {MatchMethod.fuzzy, MatchMethod.new}


# ---- hiệu năng ----
def test_deciding_against_500_candidates_is_fast() -> None:
    candidates = [
        candidate(pid, f"Logitech G{pid} X Superlight Lightspeed Edition") for pid in range(1, 501)
    ]

    started = time.perf_counter()
    for n in range(20):
        decide_match(
            MOUSE,
            "Logitech",
            None,
            f"Logitech G{n + 1} X Superlight Lightspeed Edition",
            {},
            candidates,
        )
        decide_match(MOUSE, "Logitech", None, f"Logitech G{9000 + n} X Superlight", {}, candidates)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"{elapsed:.2f}s"


# ---- fuzz có hạt giống cố định ----
JUNK = [
    "Laptop", "Chuột", "Bàn phím", "Tai nghe", "gaming", "cơ", "không dây", "có dây", "Wireless",
    "Logitech", "Razer", "ASUS", "Acer", "HP", "Dell", "HyperX", "Akko", "MSI", "Lenovo",
    "G304", "X2", "V3", "Pro", "Mini", "Max", "SE", "Ultra", "AL15-53P-56QH", "15IRX9",
    "5-120U", "i5-13420H", "Ryzen 7 7435HS", "RTX 4060", "RTX4050", "8GB", "16GB", "1TB", "144Hz",
    "(", ")", "[", "]", "/", "|", "-", "+", "%", ",", "&", "*", "'", '"', "#",
    "Black", "Đen", "Đỏ", "Switch", "Gateron", "MX", "TKL", "75%", "3 mode", "2.4G", "Bluetooth",
    "USB", "3.5mm", "7.1", "TWS", "ANC", "mic", "99g", "26000 DPI", "910-006247", "(PMW920)",
    "[Hot]", "(Mới)", "\x00", "\x07", "🙂", "٣", "0", "00", "-1", "99999999999999999999", "1e309",
    "nan", "", " ", "\t", "\n",
]  # fmt: skip


def junk_text(rng: random.Random, words: int) -> str:
    separators = [" ", " ", " ", "", "/", " | "]
    text = "".join(rng.choice(JUNK) + rng.choice(separators) for _ in range(rng.randint(0, words)))
    form = rng.choice(["NFC", "NFD", "NFKC", None, None])
    return unicodedata.normalize(form, text) if form else text


def test_random_junk_titles_never_crash_the_normalize_and_match_chain() -> None:
    rng = random.Random(1234)
    categories = [*CATEGORIES, Category.phone, Category.other]
    for _ in range(1500):
        category = rng.choice(categories)
        title = junk_text(rng, 14)
        raw = {junk_text(rng, 2): junk_text(rng, 5) for _ in range(rng.randint(0, 5))}
        mine = view(category, title, raw)
        others = []
        for product_id in range(1, rng.randint(1, 5)):
            other = view(category, junk_text(rng, 10))
            others.append(Candidate(product_id, other.name, other.code, other.specs))

        decision = decide_match(category, mine.brand, mine.code, mine.name, mine.specs, others)

        assert (decision.product_id is None) == (decision.method is MatchMethod.new)
        assert decision.product_id is None or decision.product_id in {c.product_id for c in others}
        assert decision.score is None or 0.0 <= decision.score <= 1.0


MODEL_LINES = {
    MOUSE: [
        ("Logitech", "G304 X Superlight"), ("Logitech", "G304 Lightspeed"), ("Logitech", "G102"),
        ("Logitech", "G102 Gen 2"), ("Logitech", "MX Master 3S"), ("Logitech", "MX Master 3"),
        ("Razer", "Viper V3 Pro"), ("Razer", "Viper V3 HyperSpeed"), ("Razer", "Viper Mini"),
        ("Razer", "Viper Mini SE"), ("Pulsar", "X2"), ("Pulsar", "X2 Mini"), ("Pulsar", "X2 V2"),
        ("Pulsar", "Xlite V2 Mini"), ("Pulsar", "Xlite V2"), ("Akko", "Nest"), ("Akko", "Nest Pro"),
        ("Akko", "Dash V9 Max"), ("Akko", "Dash V9"),
    ],
    KEYBOARD: [
        ("Akko", "3068B Plus Gateron Red"), ("Akko", "3068B Plus Gateron Brown"),
        ("Akko", "3068B Plus Red Axis"), ("Akko", "3068B Plus Blue Axis"),
        ("Akko", "3087 v2 Cream Yellow"), ("Akko", "3087 v2 Cream Blue"),
        ("Logitech", "G512 X 75 TMR"), ("Logitech", "G512 X 98 TMR"),
        ("Logitech", "G Pro X2 Rapid"), ("Logitech", "Pro X2 Rapid TKL"),
        ("Razer", "Huntsman V2 TKL"), ("Razer", "Huntsman V2 Analog"), ("Razer", "Huntsman V2"),
        ("Razer", "Huntsman Mini 60%"),
    ],
    HEADSET: [
        ("HyperX", "Cloud III"), ("HyperX", "Cloud III Wireless"), ("HyperX", "Cloud II"),
        ("HyperX", "Cloud Alpha"), ("Razer", "BlackShark V2 Pro"), ("Razer", "BlackShark V2 X"),
        ("Razer", "BlackShark V2"), ("Razer", "Kraken V3"), ("Razer", "Kraken V3 X"),
        ("Razer", "Kraken V3 Pro"), ("Logitech", "G Pro X3 Lightspeed"),
        ("Logitech", "G Pro X Wireless"),
    ],
}  # fmt: skip
TYPE_WORDS = {
    MOUSE: ["Chuột", "Chuột gaming", "Chuột không dây", "Mouse"],
    KEYBOARD: ["Bàn phím", "Bàn phím cơ", "Bàn phím gaming"],
    HEADSET: ["Tai nghe", "Tai nghe gaming"],
}
COLOUR_WORDS = ["", "", "Black", "White", "Đen", "Trắng", "Pink", "Silver"]
WARRANTY_WORDS = ["", "", "(Chính hãng)", "- Chính hãng", "(910-006247)"]


def test_random_listing_variants_merge_within_a_model_line_and_never_across_lines() -> None:
    rng = random.Random(7)
    wrong: list[tuple[str, str]] = []
    missed: list[tuple[str, str]] = []

    def variant(category: Category, brand: str, model: str) -> str:
        parts = [rng.choice(TYPE_WORDS[category]), brand, model, rng.choice(COLOUR_WORDS)]
        text = " ".join(part for part in [*parts, rng.choice(WARRANTY_WORDS)] if part)
        return rng.choice([text, text, text.upper(), text.lower()])

    for category, lines in MODEL_LINES.items():
        for i, (brand_a, model_a) in enumerate(lines):
            for j, (brand_b, model_b) in enumerate(lines):
                if brand_a != brand_b:
                    continue
                for _ in range(6):
                    a, b = variant(category, brand_a, model_a), variant(category, brand_b, model_b)
                    verdict = merges(category, a, b)
                    if i != j and any(verdict):
                        wrong.append((a, b))
                    if i == j and verdict != (True, True):
                        missed.append((a, b))

    assert wrong == []
    assert missed == []
