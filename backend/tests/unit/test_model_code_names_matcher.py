"""Mã model, tên chuẩn và quyết định ghép (app/normalize/{model_code,names,matcher}.py)."""

import pytest

from app.domain.enums import Category, MatchMethod
from app.normalize.brand import brand_words, detect_brand
from app.normalize.matcher import (
    Candidate,
    decide_match,
    name_similarity,
    same_model_name,
    specs_compatible,
)
from app.normalize.model_code import extract_model_code, hint_code, laptop_code_span
from app.normalize.names import canonical_name, name_key
from app.normalize.url import clean_url, scheme_twin


# ---- model_code ----
@pytest.mark.parametrize(
    ("title", "code"),
    [
        (
            'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD)',
            "AL15-53P-56QH",
        ),
        (
            "Laptop gaming Acer Nitro ProPanel ANV15-52-556L (Core 5-210H/ RTX 5050 8GB)",
            "ANV15-52-556L",
        ),
        (
            'Laptop Acer Aspire Lite 14 AL14-44P-R0SP R7 7730U/8GB/512GB/14.5" FHD/Win11',
            "AL14-44P-R0SP",
        ),
        (
            'Laptop Asus TUF Gaming 16 FX610JH-TU008W i5-14450HX/16GB/512GB/16"/Win 11',
            "FX610JH-TU008W",
        ),
        ("Laptop HP VICTUS 15-fa2452TX D44VLPA (Intel Core i5-13420H | 16GB)", "D44VLPA"),
        ("Laptop HP 250R G10 C3SH7AT (Intel Core 5 120U | 16GB)", "C3SH7AT"),
        (
            "Laptop Lenovo LOQ 15IRX9 83DV01MCVN (Intel Core i7-14650HX | RTX 4050 6GB)",
            "83DV01MCVN",
        ),
        (
            "Laptop gaming Lenovo LOQ 15ARP10E 83S0006RVN (Ryzen 7-7735HS/ RTX 3050 6GB)",
            "83S0006RVN",
        ),
        ("Laptop Dell Inspiron 14 5441 5MNK1 (Snapdragon X Plus | 16GB)", "5MNK1"),
        ("Laptop Dell XPS 13 9350 71100521 (Intel Core Ultra 5 226V | 16GB)", "71100521"),
        ("Laptop Dell XPS 13 DX13260- DX3C5376W1 (Intel Core 5 320 | 16GB)", "DX3C5376W1"),
        ("Laptop LG Gram Book 15U50U-G.AV55A5 (Intel Core Ultra5-115U | 16GB)", "15U50U-G.AV55A5"),
        ("Laptop MSI Cyborg 15 Max C13WE-422VN (Intel Core i7-13620H | RTX 5050)", "C13WE-422VN"),
        (
            "Laptop ASUS ExpertBook P1503CVAY-308D4256-63WS (Intel Core 3 100U | 8GB)",
            "P1503CVAY-308D4256-63WS",
        ),
    ],
)
def test_laptop_model_code_from_title(title: str, code: str) -> None:
    assert extract_model_code(Category.laptop, title) == code


@pytest.mark.parametrize(
    "title",
    [
        "Laptop Acer Gaming Nitro (Core 5-210H/ 16GB)",  # không có mã
        "Laptop X i5-14450HX/16GB/512GB",  # chỉ có CPU/RAM/ổ cứng
        "Laptop X 7730U/8GB",
        "",
    ],
)
def test_laptop_without_a_code_gets_none(title: str) -> None:
    assert extract_model_code(Category.laptop, title) is None


@pytest.mark.parametrize("category", [Category.mouse, Category.keyboard, Category.headset])
def test_accessories_have_no_model_code_even_with_a_part_number(category: Category) -> None:
    assert extract_model_code(category, "Chuột Logitech SIGNATURE M650L 910-006247") is None


def test_hint_wins_over_the_title_and_is_normalized() -> None:
    title = "Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB)"
    assert extract_model_code(Category.laptop, title, "mk-la 001") == "MK-LA001"


@pytest.mark.parametrize("category", [Category.mouse, Category.keyboard, Category.headset])
def test_accessories_ignore_the_part_number_hint_because_it_differs_per_colour(
    category: Category,
) -> None:
    # T5.4: MPN phụ kiện theo màu (Logitech 910-005880 đen / 910-005881 trắng).
    assert extract_model_code(category, "Chuột X", "MK-MO004") is None
    assert extract_model_code(category, "Chuột Logitech G502 X", "910-005880") is None


@pytest.mark.parametrize("hint", [None, "", "33297", "00930661", "ab", "x" * 60])
def test_hint_without_letters_and_digits_is_ignored(hint: str | None) -> None:
    assert hint_code(hint) is None


def test_laptop_code_span_gives_the_name_up_to_the_code() -> None:
    span = laptop_code_span("Laptop gaming Lenovo LOQ 15ARP10E 83S0006RVN (Ryzen 7-7735HS/ 16GB)")
    assert span == ("Lenovo LOQ 15ARP10E 83S0006RVN", "83S0006RVN")


# ---- names ----
@pytest.mark.parametrize(
    ("title", "category", "name"),
    [
        (
            "Laptop gaming Acer Aspire 7 A715-59G-59RD (Core 5-210H/ 16GB)",
            Category.laptop,
            "Acer Aspire 7 A715-59G-59RD",
        ),
        (
            "Chuột gaming không dây Logitech G304 X Superlight Black",
            Category.mouse,
            "Logitech G304 X Superlight",
        ),
        (
            "Chuột Logitech G Pro X3 SUPERSTRIKE Midnight Black",
            Category.mouse,
            "Logitech G Pro X3 SUPERSTRIKE",
        ),
        ("Chuột Gaming Predator Cestus 330 (PMW920)", Category.mouse, "Predator Cestus 330"),
        ("Chuột MSI Clutch GM40 GAMING (White/Black)", Category.mouse, "MSI Clutch GM40 GAMING"),
        (
            "Chuột Logitech SIGNATURE M650L Wireless/Bluetooth - màu đen 910-006247",
            Category.mouse,
            "Logitech SIGNATURE M650L Wireless Bluetooth",
        ),
        ("[Mới 100%] Tai nghe HyperX Cloud III Black", Category.headset, "HyperX Cloud III"),
        (
            "Bàn phím cơ AULA F75 Grey White Milk White switch",
            Category.keyboard,
            "AULA F75 Milk White switch",
        ),
        (
            "Bàn phím cơ Logitech G512 X 98 TMR White Tactile switch",
            Category.keyboard,
            "Logitech G512 X 98 TMR Tactile switch",
        ),
    ],
)
def test_canonical_name_drops_prefix_colour_and_codes(
    title: str, category: Category, name: str
) -> None:
    assert canonical_name(title, category) == name


def test_canonical_name_is_never_empty() -> None:
    assert canonical_name("Đen", Category.mouse) == "Đen"
    assert canonical_name("", Category.mouse) == ""


@pytest.mark.parametrize(
    ("name", "brand", "key"),
    [
        ("Logitech G304 X Superlight", "Logitech", ("g304", "x", "superlight")),
        ("Logitech G Pro X3 LightSpeed", "Logitech", ("pro", "x3", "lightspeed")),
        ("Logitech PRO X3 Lightspeed", "Logitech", ("pro", "x3", "lightspeed")),
        ("HP HYPERX Cloud Earbuds III S", "HyperX", ("cloud", "earbuds", "iii", "s")),
        ("Acer Predator Cestus 330", "Acer", ("predator", "cestus", "330")),
        (
            "DareU Flex 75 Triple Mode Pegasus switch",
            "DareU",
            ("flex", "75", "trimode", "pegasus", "switch"),
        ),
        ("Chuột không dây Pulsar X2 Mini Đen", "Pulsar", ("wireless", "x2", "mini")),
    ],
)
def test_name_key(name: str, brand: str, key: tuple[str, ...]) -> None:
    assert name_key(name, brand) == key


def test_name_key_is_cached_because_the_matcher_recomputes_it_for_every_candidate() -> None:
    # T5.4: tránh tính lại khóa tên của mọi ứng viên cho mỗi offer khi nạp hàng nghìn offer.
    name_key.cache_clear()
    name_key("Logitech G304 X Superlight", "Logitech")
    name_key("Logitech G304 X Superlight", "Logitech")
    assert name_key.cache_info().hits == 1


def test_brand_words_include_company_aliases() -> None:
    assert brand_words("HyperX") == {"hyperx", "hp"}
    assert brand_words("Acer") == {"acer"}


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Tai nghe HP HYPERX Cloud Earbuds III Black", "HyperX"),
        ("Tai nghe HP Z3200 Stereo", "HP"),
        ("Bàn phím cơ AULA F75", "AULA"),
        ("Chuột ATK GHOST Extreme+ Purple", "ATK"),
        ("Chuột không dây công thái học Logitech Lift Vertical", "Logitech"),
        ("Chuột Bluetooth Silent Rapoo M650 Lucky Cat", "Rapoo"),
        ("Micro HyperX SoloCast 2", "HyperX"),
        ("Laptop LG Gram Book 15U50U-G.AV55A5", "LG"),
        ("Chuột không dây Microsoft PL2 ARC", "Microsoft"),
        ("Chuột Pulsar X2 Red", "Pulsar"),
    ],
)
def test_brands_seen_in_the_real_fixtures_are_recognised(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


# ---- matcher ----
def candidate(product_id: int, name: str, code: str | None = None, **specs: object) -> Candidate:
    return Candidate(product_id, name, code, specs)


def test_same_model_code_merges_with_full_score() -> None:
    existing = [candidate(7, "Acer Aspire Lite 15 AL15-53P-56QH", "AL15-53P-56QH", ram_gb=8)]
    decision = decide_match(
        Category.laptop,
        "Acer",
        "AL15-53P-56QH",
        "Acer Aspire Lite 15 AL15-53P-56QH",
        {"ram_gb": 8},
        existing,
    )
    assert (decision.product_id, decision.method, decision.score) == (
        7,
        MatchMethod.model_code,
        1.0,
    )


def test_same_code_with_conflicting_required_spec_is_a_new_product_that_cannot_take_the_code() -> (
    None
):
    existing = [candidate(7, "Acer Aspire Lite 15 AL15-53P-56QH", "AL15-53P-56QH", ram_gb=8)]
    decision = decide_match(
        Category.laptop,
        "Acer",
        "AL15-53P-56QH",
        "Acer Aspire Lite 15 AL15-53P-56QH",
        {"ram_gb": 16},
        existing,
    )
    assert decision.product_id is None
    assert decision.method is MatchMethod.new
    assert decision.code_taken is True


def test_different_explicit_codes_never_merge_even_with_similar_names() -> None:
    existing = [candidate(1, "Acer Aspire Lite 15 AL15-53P-56QH", "AL15-53P-56QH")]
    decision = decide_match(
        Category.laptop,
        "Acer",
        "AL15-410P-R1W8",
        "Acer Aspire Lite 15 AL15-410P-R1W8",
        {},
        existing,
    )
    assert decision.product_id is None


def test_colour_variants_merge_by_name() -> None:
    existing = [candidate(3, "Pulsar X2")]
    decision = decide_match(Category.mouse, "Pulsar", None, "Pulsar X2", {}, existing)
    assert (decision.product_id, decision.method) == (3, MatchMethod.fuzzy)
    assert decision.score == 1.0


def test_best_candidate_wins_and_ties_go_to_the_lowest_id() -> None:
    existing = [candidate(9, "Pulsar X2"), candidate(4, "Pulsar X2")]
    assert decide_match(Category.mouse, "Pulsar", None, "Pulsar X2", {}, existing).product_id == 4


@pytest.mark.parametrize(
    ("incoming", "existing"),
    [
        ("Pulsar X2 Mini", "Pulsar X2"),  # tên này là tập con của tên kia
        ("Logitech G Pro X2", "Logitech G Pro X3"),  # khác số hiệu
        ("HyperX Cloud Earbuds III", "HyperX Cloud Earbuds III S"),
    ],
)
def test_similar_but_different_names_stay_separate(incoming: str, existing: str) -> None:
    brand = incoming.split()[0]
    decision = decide_match(Category.mouse, brand, None, incoming, {}, [candidate(1, existing)])
    assert decision.product_id is None and decision.method is MatchMethod.new


def test_unknown_brand_is_never_fuzzy_matched() -> None:
    decision = decide_match(
        Category.mouse, "Unknown", None, "Infinity Shadow", {}, [candidate(1, "Infinity Shadow")]
    )
    assert decision.product_id is None


def test_unknown_brand_can_still_merge_by_exact_model_code() -> None:
    decision = decide_match(
        Category.laptop,
        "Unknown",
        "XYZ-12345",
        "Foo XYZ-12345",
        {},
        [candidate(2, "Foo", "XYZ-12345")],
    )
    assert (decision.product_id, decision.method) == (2, MatchMethod.model_code)


def test_conflicting_connection_blocks_a_name_match() -> None:
    existing = [candidate(1, "Logitech G304 X Superlight", connection=["wired"])]
    decision = decide_match(
        Category.mouse,
        "Logitech",
        None,
        "Logitech G304 X Superlight",
        {"connection": ["wireless_2_4"]},
        existing,
    )
    assert decision.product_id is None


def test_unknown_connection_does_not_block_a_name_match() -> None:
    existing = [candidate(1, "Logitech G304 X Superlight", connection=["wireless_2_4"])]
    decision = decide_match(
        Category.mouse, "Logitech", None, "Logitech G304 X Superlight", {}, existing
    )
    assert decision.product_id == 1


def test_laptop_without_code_needs_all_required_specs_to_match() -> None:
    full = {"cpu_model": "i5-1235U", "gpu_model": "RTX 3050", "ram_gb": 16, "storage_gb": 512}
    existing = [candidate(1, "Foo Bar 15", **full)]
    assert (
        decide_match(Category.laptop, "Foo", None, "Foo Bar 15", dict(full), existing).product_id
        == 1
    )
    partial = {"ram_gb": 16, "storage_gb": 512}
    assert (
        decide_match(Category.laptop, "Foo", None, "Foo Bar 15", partial, existing).product_id
        is None
    )


def test_laptop_with_only_a_cpu_family_is_not_fuzzy_matched() -> None:
    # T5.4: "Core i5" không phân biệt cấu hình nên không đủ để ghép mờ laptop (ưu tiên chính xác).
    family = {"cpu_model": "Core i5", "gpu_model": "RTX 3050", "ram_gb": 16, "storage_gb": 512}
    existing = [candidate(1, "Foo Bar 15", **family)]
    decision = decide_match(Category.laptop, "Foo", None, "Foo Bar 15", dict(family), existing)
    assert decision.product_id is None


def test_no_candidates_means_new() -> None:
    decision = decide_match(Category.mouse, "Pulsar", None, "Pulsar X2", {}, [])
    assert (decision.product_id, decision.method, decision.score) == (None, MatchMethod.new, None)


def test_specs_compatible_compares_lists_as_sets() -> None:
    left = {"connection": ["wired", "bluetooth"]}
    right = {"connection": ["bluetooth", "wired"]}
    assert specs_compatible(Category.mouse, left, right)
    assert not specs_compatible(Category.mouse, left, {"connection": ["wired"]})
    assert specs_compatible(Category.mouse, left, {})
    assert not specs_compatible(Category.mouse, left, right | {"connection": []}, strict=True)


def test_same_model_name_requires_non_empty_keys_and_similarity() -> None:
    assert not same_model_name((), ("a1",))
    assert same_model_name(("g304", "x"), ("x", "g304"))
    assert name_similarity(("g304", "x"), ("x", "g304")) == 1.0
    assert not same_model_name(("g304", "x"), ("g305", "x"))


# ---- url ----
def test_scheme_twin_swaps_http_and_https() -> None:
    assert scheme_twin("https://shop.example/p/a?x=1") == "http://shop.example/p/a?x=1"
    assert scheme_twin("http://shop.example/p/a") == "https://shop.example/p/a"
    assert (
        scheme_twin(scheme_twin(clean_url("https://shop.example/p/a")))
        == "https://shop.example/p/a"
    )
    assert scheme_twin("ftp://x/y") == "ftp://x/y"
