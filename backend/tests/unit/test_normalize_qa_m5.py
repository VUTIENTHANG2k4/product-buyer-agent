"""QA M5: ca biên cho chuẩn hóa (trích thông số, hãng, mã model, tên chuẩn).

Bổ sung cho `test_extract_*.py`, `test_normalize_brand.py`, `test_model_code_names_matcher.py`.
Test `xfail(strict=True)` là lỗi đã tái hiện (mã BUG-M5-n, xem báo cáo QA M5); khi sửa xong, XPASS
làm test đỏ và phải gỡ dấu xfail.
"""

import time
import unicodedata
from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.brand import detect_brand
from app.normalize.extract import extract_specs, merge_specs, missing_required
from app.normalize.model_code import MAX_CODE_LENGTH, extract_model_code
from app.normalize.names import canonical_name, name_key
from app.normalize.specs import SPEC_MODELS
from app.normalize.specs.parsing import clean

LAPTOP, MOUSE, KEYBOARD, HEADSET = (
    Category.laptop,
    Category.mouse,
    Category.keyboard,
    Category.headset,
)
EXTRACTABLE = (LAPTOP, MOUSE, KEYBOARD, HEADSET)


def bug(code: str, why: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{code}: {why}")


def strip_accents(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in folded if not unicodedata.combining(c))


def fullwidth(text: str) -> str:
    """Chuyển ASCII in được sang dạng toàn chiều rộng (NFKC đưa về lại ASCII)."""
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


# ---- tiêu đề rác: không lỗi, bất biến giữ nguyên ----
GARBAGE_TITLES = [
    pytest.param("", id="empty"),
    pytest.param("   \t\n ", id="whitespace"),
    pytest.param("\u200b\u200b", id="zero-width-space"),
    pytest.param("\ufeff", id="bom"),
    pytest.param("\u0301\u0301", id="combining-marks-only"),
    pytest.param("🙂🙂🙂", id="emoji"),
    pytest.param("-", id="dash"),
    pytest.param("()", id="empty-parens"),
    pytest.param("[]", id="empty-brackets"),
    pytest.param("[Hot]", id="only-a-tag"),
    pytest.param("////", id="slashes"),
    pytest.param(" | ", id="pipe"),
    pytest.param("Laptop", id="only-laptop"),
    pytest.param("Chuột", id="only-type-word"),
    pytest.param("Tai nghe", id="only-type-phrase"),
    pytest.param("x" * 5000, id="long-word"),
    pytest.param("RTX 4060 " * 800, id="long-repeated-gpu"),
    pytest.param("(" * 3000, id="deep-open-parens"),
    pytest.param("١٦GB ٥١٢GB", id="arabic-indic-digits"),
]


@pytest.mark.parametrize("category", EXTRACTABLE)
@pytest.mark.parametrize("title", GARBAGE_TITLES)
def test_garbage_titles_never_crash_and_keep_the_invariants(category: Category, title: str) -> None:
    result = extract_specs(category, title, {})

    SPEC_MODELS[category].model_validate(result.specs)  # khóa lạ bị bỏ, giá trị đúng miền
    assert all(value is not None for value in result.specs.values())
    assert result.missing == missing_required(category, result.specs)
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence == 1.0 or result.confidence < 0.5
    assert all(
        not isinstance(value, int | float) or isinstance(value, bool) or value > 0
        for name, value in result.specs.items()
        if name not in {"gpu_vram_gb", "gpu_rank"}
    )

    brand = detect_brand(title)
    assert isinstance(brand, str) and brand
    assert all(isinstance(token, str) for token in name_key(title, brand))
    code = extract_model_code(category, title)
    assert code is None or (
        code == code.upper() and " " not in code and len(code) <= MAX_CODE_LENGTH
    )
    if clean(title):
        assert canonical_name(title, category).strip()


# ---- số liệu rác trong bảng thông số ----
@pytest.mark.parametrize(
    ("category", "title", "raw_specs", "absent"),
    [
        (LAPTOP, "Laptop X (i5-13420H/ 0GB/ 512GB/ RTX 3050)", {}, "ram_gb"),
        (LAPTOP, "Laptop X (i5-13420H/ 16GB/ 0TB/ RTX 3050)", {}, "storage_gb"),
        (LAPTOP, "Laptop X (i5-13420H/ 99999GB/ 512GB)", {}, "ram_gb"),
        (LAPTOP, "Laptop X (i5-13420H/ -8GB/ 512GB)", {"RAM": "-0GB"}, "gpu_model"),
        (LAPTOP, "Laptop X", {"Dung lượng RAM": "4096GB"}, "ram_gb"),
        (LAPTOP, "Laptop X", {"Ổ cứng": "8GB eMMC"}, "storage_gb"),
        (LAPTOP, "Laptop X", {"Kích thước màn hình": "0 inch"}, "screen_in"),
        (LAPTOP, "Laptop X", {"Kích thước màn hình": "99 inch"}, "screen_in"),
        (LAPTOP, "Laptop X", {"Tần số quét": "0Hz"}, "refresh_hz"),
        (LAPTOP, "Laptop X", {"Trọng lượng": "0 kg"}, "weight_kg"),
        (MOUSE, "Chuột X", {"Trọng lượng": "0 g"}, "weight_g"),
        (MOUSE, "Chuột X", {"Trọng lượng": "99999 g"}, "weight_g"),
        (MOUSE, "Chuột X", {"DPI": "0"}, "dpi_max"),
        (MOUSE, "Chuột X", {"Số nút": "0"}, "buttons"),
        (HEADSET, "Tai nghe X", {"Driver": "00 mm"}, "driver_mm"),
    ],
)
def test_unreadable_numbers_are_dropped_instead_of_stored_as_zero_or_garbage(
    category: Category, title: str, raw_specs: dict[str, str], absent: str
) -> None:
    result = extract_specs(category, title, raw_specs)

    assert absent not in result.specs
    SPEC_MODELS[category].model_validate(result.specs)


def test_a_table_value_wins_over_the_title_but_cpu_comes_from_the_title() -> None:
    title = "Laptop X (i5-13420H/ 16GB/ 512GB/ RTX 4060)"
    raw = {
        "RAM": "8GB",
        "Ổ cứng": "1TB SSD",
        "Card đồ họa": "NVIDIA GeForce RTX 3050 6GB",
        "CPU": "Intel Core i7-13700H",
    }

    specs = extract_specs(LAPTOP, title, raw).specs

    assert (specs["ram_gb"], specs["storage_gb"], specs["gpu_model"]) == (8, 1000, "RTX 3050")
    assert specs["gpu_rank"] == 20
    assert specs["cpu_model"] == "i5-13420H"


def test_upgrade_limit_labels_never_override_the_installed_value() -> None:
    raw = {"Nâng cấp RAM": "Tối đa 64GB", "Dung lượng RAM": "16GB"}

    assert extract_specs(LAPTOP, "Laptop X", raw).specs["ram_gb"] == 16


def test_merge_never_overwrites_known_values_even_with_contradicting_new_ones() -> None:
    existing = {"cpu_model": "i5-13420H", "ram_gb": 8, "gpu_model": "RTX 3050"}
    new = extract_specs(LAPTOP, "Laptop X (i7-13700H/ 16GB/ 1TB/ RTX 4060)", {}).specs

    merged = merge_specs(LAPTOP, existing, new)

    assert (merged["cpu_model"], merged["ram_gb"], merged["gpu_model"]) == (
        "i5-13420H",
        8,
        "RTX 3050",
    )
    assert merged["storage_gb"] == 1000  # chỉ trường còn thiếu được điền
    assert merged["gpu_rank"] == 20  # hạng tính lại từ GPU cuối cùng, không dùng RTX 4060


# ---- Unicode: tổ hợp / dựng sẵn / không dấu / toàn chiều rộng ----
UNICODE_CASES = [
    pytest.param(
        MOUSE,
        "Chuột không dây Logitech G304 X Superlight - Màu Đen",
        {"Kết nối": "Không dây 2.4GHz", "Trọng lượng": "63 g"},
        id="mouse",
    ),
    pytest.param(
        KEYBOARD,
        "Bàn phím cơ không dây Akko 3068B Plus Hotswap Bluetooth 65% Màu Đen",
        {"Loại switch": "Cơ học", "Đèn nền": "Không"},
        id="keyboard",
    ),
    pytest.param(
        HEADSET,
        "Tai nghe không dây Razer BlackShark V2 Pro Chụp Tai Đen",
        {"Kết nối": "Không dây 2.4GHz", "Micro": "Không"},
        id="headset",
    ),
    pytest.param(
        LAPTOP,
        "Laptop gaming ASUS TUF Gaming F15 FX507ZC4-HN005W (i5-12500H/ 16GB/ 512GB)",
        {"Card đồ họa": "NVIDIA GeForce RTX 3050 6GB", "Ổ cứng": "512GB SSD NVMe"},
        id="laptop-with-vietnamese-labels",
    ),
]


def normalised_view(category: Category, title: str, raw: dict[str, str]) -> dict[str, Any]:
    return {
        "specs": extract_specs(category, title, raw).specs,
        "brand": detect_brand(title),
        "key": name_key(canonical_name(title, category), detect_brand(title)),
        "code": extract_model_code(category, title),
    }


@pytest.mark.parametrize(("category", "title", "raw"), UNICODE_CASES)
def test_composed_decomposed_and_unaccented_forms_give_the_same_result(
    category: Category, title: str, raw: dict[str, str]
) -> None:
    reference = normalised_view(category, title, raw)
    forms = {
        "NFD": lambda s: unicodedata.normalize("NFD", s),
        "NFKD": lambda s: unicodedata.normalize("NFKD", s),
        "unaccented": strip_accents,
    }

    for name, convert in forms.items():
        converted_raw = {convert(k): convert(v) for k, v in raw.items()}
        assert normalised_view(category, convert(title), converted_raw) == reference, name


@pytest.mark.parametrize(
    "title",
    [
        "Chuột Pulsar X2 Phiên bản đặc biệt",
        "Bàn phím cơ Akko 3068B Plus Phiên bản giới hạn",
    ],
)
def test_canonical_name_is_stored_in_nfc(title: str) -> None:
    decomposed = unicodedata.normalize("NFD", title)

    assert unicodedata.is_normalized("NFC", canonical_name(decomposed, MOUSE))
    assert canonical_name(decomposed, MOUSE) == canonical_name(title, MOUSE)


def test_fullwidth_brand_is_recognised() -> None:
    assert detect_brand(fullwidth("Laptop Acer Aspire Lite 15")) == "Acer"


def test_fullwidth_title_gives_the_same_specs_as_ascii() -> None:
    ascii_title = "Laptop X (i5-13420H/ 16GB/ 512GB/ RTX 3050)"

    assert extract_specs(LAPTOP, fullwidth(ascii_title), {}).specs == (
        extract_specs(LAPTOP, ascii_title, {}).specs
    )


# ---- hãng ----
@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("[HOT] Laptop Dell Inspiron 15", "Dell"),
        ("(Mới) [HOT] Laptop Dell Inspiron 15", "Dell"),
        ("Laptop\u00a0ASUS Vivobook", "ASUS"),
        ("LAPTOP ASUS VIVOBOOK", "ASUS"),
        ("Laptop\tASUS Vivobook", "ASUS"),
        ("Laptop A\u200bSUS Vivobook", "ASUS"),
        ("Logi MX Master 3S", "Logitech"),
        ("Dare-U EK87", "DareU"),
        ("Chuột không dây công thái học Logitech Lift", "Logitech"),
        ("Bàn phím cơ không dây bluetooth gaming Akko 3068", "Akko"),
        ("HP HyperX Cloud II", "HyperX"),
        ("HPE ProLiant DL380", "Unknown"),
        ("Bàn phím cho MacBook Air", "Unknown"),
        ("Phụ kiện Logitech G102", "Unknown"),
    ],
)
def test_brand_detection_handles_tags_whitespace_case_and_lookalikes(
    title: str, brand: str
) -> None:
    assert detect_brand(title) == brand


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Chuột có dây Dell MS116", "Dell"),
        ("Chuột quang Logitech B100", "Logitech"),
        ("Chuột văn phòng Logitech M185", "Logitech"),
        ("Bàn phím có dây Dell KB216", "Dell"),
        ("Bàn phím giả cơ Razer Ornata V3", "Razer"),
        ("Tai nghe chụp tai Sony WH-CH520", "Sony"),
        ("Tai nghe nhét tai JBL Tune 110", "JBL"),
        ("Tai nghe có dây Logitech H111", "Logitech"),
        ("Laptop văn phòng Dell Inspiron 15 3520", "Dell"),
        ("Máy tính xách tay ASUS Vivobook 15", "ASUS"),
        ("Combo bàn phím chuột không dây Logitech MK270", "Logitech"),
        ("Hàng chính hãng Chuột Logitech G102", "Logitech"),
        ("★ Laptop Dell Inspiron 15", "Dell"),
        ("🔥 Laptop ASUS Vivobook 15", "ASUS"),
    ],
)
def test_brand_is_found_after_common_product_descriptors(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


def test_canonical_name_starts_at_the_brand_not_at_a_descriptor() -> None:
    assert canonical_name("Tai nghe chụp tai Sony WH-CH520", HEADSET) == "Sony WH-CH520"
    assert (
        canonical_name("Laptop văn phòng Dell Inspiron 15 3520 N3520-71100521", LAPTOP)
        == "Dell Inspiron 15 3520 N3520-71100521"
    )


# ---- mã model ----
@pytest.mark.parametrize(
    "title",
    [
        "Laptop",
        "Laptop 15",
        "Laptop Dell Inspiron 15 3520 i5-1235U 16GB 512GB",
        "Laptop Dell Inspiron 15 3520 FHD+ 120Hz OLED",
        "Laptop Dell Inspiron 15 3520 2.8K OLED",
        "Laptop Lenovo ThinkPad E14 Gen10",
        "Laptop Lenovo ThinkPad E14 (Gen 5) 16GB",
    ],
)
def test_titles_without_a_real_model_code_give_none(title: str) -> None:
    assert extract_model_code(LAPTOP, title) is None


@pytest.mark.parametrize(
    ("title", "code"),
    [
        ("Laptop Apple MacBook Air 13 M2 8GB 256GB MLY13SA/A", "MLY13SA"),
        ("Laptop HP Pavilion 15-eg3092TU 8C5L7PA i5-1335U 8GB 512GB", "8C5L7PA"),
        ("laptop acer aspire lite 15 al15-53p-56qh (core 5-120u/ 8gb)", "AL15-53P-56QH"),
        ("Laptop Dell Latitude 3540 L3540I516W1 | Core i5 | 16GB", "L3540I516W1"),
    ],
)
def test_model_code_survives_trailing_specs_and_lower_case(title: str, code: str) -> None:
    assert extract_model_code(LAPTOP, title) == code


@pytest.mark.parametrize(
    ("title", "code"),
    [
        (
            "Laptop Acer Aspire Lite 15 AL15-53P-56QH Core 5-120U/8GB/512GB",
            "AL15-53P-56QH",
        ),
        (
            "Laptop Asus Vivobook 15 X1504VA-NJ070W Ryzen 5-7535HS/16GB/512GB",
            "X1504VA-NJ070W",
        ),
        (
            "Laptop Asus Vivobook 15 X1504VA-NJ070W Ultra 5-226V/16GB/512GB",
            "X1504VA-NJ070W",
        ),
        (
            "Laptop Asus Vivobook S 15 S5507QA-MA089WS Snapdragon X Elite X1E-78-100/32GB/1TB",
            "S5507QA-MA089WS",
        ),
        (
            "Laptop Asus Vivobook 15 X1504VA-NJ070W Core i7 DDR5-5600/16GB/512GB",
            "X1504VA-NJ070W",
        ),
        ("Laptop Dell Inspiron 15 3520 N3520-71100521 RTX-4060", "N3520-71100521"),
    ],
)
def test_hyphenated_cpu_or_memory_tokens_outside_parentheses_are_not_model_codes(
    title: str, code: str
) -> None:
    assert extract_model_code(LAPTOP, title) == code


@pytest.mark.parametrize(
    "title",
    [
        "(Mới) Laptop Acer Aspire Lite 15 AL15-53P-56QH",
        "[Giảm 10%/ Tặng chuột] Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB)",
    ],
)
def test_leading_promo_tag_does_not_hide_the_laptop_model_code(title: str) -> None:
    assert extract_model_code(LAPTOP, title) == "AL15-53P-56QH"


def test_laptop_canonical_name_drops_the_leading_promo_tag_and_the_type_word() -> None:
    title = "[Mới 100%] Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB)"

    assert canonical_name(title, LAPTOP) == "Acer Aspire Lite 15 AL15-53P-56QH"


@pytest.mark.parametrize(
    "title",
    [
        "Laptop Acer\x00 Aspire Lite 15 AL15-53P-56QH",
        "Laptop Acer Aspire Lite 15 AL15-53P-56QH\x07",
        "Chuột Pulsar\x1b[31m X2",
    ],
)
def test_control_characters_are_removed_from_names_and_codes(title: str) -> None:
    for category in (LAPTOP, MOUSE):
        name = canonical_name(title, category)
        assert not any(unicodedata.category(c) == "Cc" for c in name)
    code = extract_model_code(LAPTOP, title)
    assert code is None or not any(unicodedata.category(c) == "Cc" for c in code)


# ---- tên chuẩn / màu ----
@pytest.mark.parametrize(
    "colour",
    ["Đỏ", "Xanh dương", "Xanh lá", "Màu đỏ"],
)
def test_vietnamese_colours_are_not_part_of_the_name_key(colour: str) -> None:
    assert name_key(f"Chuột Pulsar X2 {colour}", "Pulsar") == name_key(
        "Chuột Pulsar X2 Đen", "Pulsar"
    )


@pytest.mark.parametrize(
    "colour", ["Đen", "Trắng", "Hồng", "Xám", "Vàng", "Bạc", "Black", "White", "Pink", "Magenta"]
)
def test_known_colours_are_not_part_of_the_name_key(colour: str) -> None:
    assert name_key(f"Chuột Pulsar X2 {colour}", "Pulsar") == ("x2",)


# ---- phủ định, số đo ----
@pytest.mark.parametrize(
    ("category", "title", "field", "expected"),
    [
        (HEADSET, "Tai nghe Sony WH-CH520 không có mic", "has_mic", None),
        (HEADSET, "Tai nghe Sony WH-CH520 không ANC", "anc", None),
        (HEADSET, "Tai nghe Sony WH-CH520 không chống ồn chủ động", "anc", None),
        (MOUSE, "Chuột Razer Orochi không có dây", "connection", ["wireless_2_4"]),
        (MOUSE, "Chuột không dây Logitech M221 (không Bluetooth)", "connection", ["wireless_2_4"]),
    ],
)
def test_negated_features_are_not_reported_as_present(
    category: Category, title: str, field: str, expected: Any
) -> None:
    assert extract_specs(category, title, {}).specs.get(field) == expected


def test_weight_after_a_2_4g_marker_in_the_title_is_still_read() -> None:
    specs = extract_specs(MOUSE, "Chuột không dây 2.4G Logitech M185 99g", {}).specs

    assert specs.get("weight_g") == 99


def test_button_count_with_more_than_two_digits_is_not_truncated() -> None:
    assert "buttons" not in extract_specs(MOUSE, "Chuột X", {"Số nút": "99999"}).specs


# ---- hiệu năng: tiêu đề/bảng thô rất dài không treo (ReDoS) ----
PATHOLOGICAL = {
    "spaces": " " * 100_000 + "x",
    "open-parens": "(" * 100_000,
    "unclosed-paren-words": "(" + "a " * 50_000,
    "brackets": "[a]" * 30_000,
    "tags-then-x": "[a] " * 30_000 + "x",
    "rtx-ti-chain": "rtx 4060" + " ti" * 30_000 + " x",
    "rtx-repeated": "rtx 4060 ti " * 15_000,
    "digits": "1" * 100_000,
    "capacities": "16GB " * 20_000,
    "slashes": "/" * 50_000,
    "pipes": " | " * 30_000,
    "long-word-then-switch": "a" * 100_000 + " switch",
    "thousand-separators": "1,000" * 20_000 + " dpi",
    "ryzen-repeated": "ryzen 7 " * 15_000,
    "combining-marks": "e\u0301" * 50_000,
    "zero-width": "\u200b" * 100_000,
    "prefix-words": "gaming " * 50_000,
    "laptop-words": "laptop " * 50_000,
}


@pytest.mark.parametrize("name", PATHOLOGICAL)
def test_pathological_titles_and_tables_finish_quickly(name: str) -> None:
    text = PATHOLOGICAL[name]
    raw = {"RAM": text, "Kết nối": text, "Card": text, "Switch": text, text[:50]: text}

    started = time.perf_counter()
    for category in EXTRACTABLE:
        extract_specs(category, text, raw)
        canonical_name(text, category)
        name_key(text, "Logitech")
    detect_brand(text)
    extract_model_code(LAPTOP, text)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"{name}: {elapsed:.2f}s"


# ---- nhãn khuyến mãi / bảo hành cuối tên ----
@pytest.mark.parametrize(
    "suffix",
    ["(Chính hãng)", "- Chính hãng", "Chính hãng", "(New)", "NEW", "Mới", "(Mới)"],
)
def test_known_promo_words_after_the_name_do_not_change_the_name_key(suffix: str) -> None:
    assert name_key(canonical_name(f"Chuột Pulsar X2 Black {suffix}", MOUSE), "Pulsar") == ("x2",)


@pytest.mark.parametrize(
    "suffix",
    [
        "(Mới 100%)",
        "- Mới 100%",
        "[Hot]",
        "[Sale]",
        "(Giá tốt)",
        "(Bảo hành 24 tháng)",
        "(Fullbox)",
        "(Nhập khẩu)",
        "| GearVN",
    ],
)
def test_trailing_marketing_text_does_not_change_the_name_key(suffix: str) -> None:
    assert name_key(canonical_name(f"Chuột Pulsar X2 Black {suffix}", MOUSE), "Pulsar") == ("x2",)


@pytest.mark.parametrize(
    "title",
    [
        "Bàn phím cho MacBook",  # từ nối: hãng đứng sau là sản phẩm khác
        "Chuột cho laptop Dell",
        "Ốp lưng iPhone 15",  # không bắt đầu bằng từ loại sản phẩm
        "Túi chống sốc Laptop Dell 15",
        "Tai nghe " + "x " * 20 + "Sony",  # hãng quá xa đầu tên
        "Chuột Fantech tương thích Logitech",
    ],
)
def test_brand_is_not_taken_from_accessories_or_far_away_words(title: str) -> None:
    assert detect_brand(title) == "Unknown"


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Dell Inspiron 15 3520", "Dell"),  # hãng ngay đầu tên vẫn khớp như trước
        ("[Mới 100%] Chuột không dây Logitech M331", "Logitech"),
        ("Combo bàn phím và chuột không dây Logitech MK270", "Logitech"),
        ("Chuột Gaming Razer DeathAdder V3", "Razer"),
        ("TAI NGHE CHỤP TAI SONY WH-CH520", "Sony"),
    ],
)
def test_brand_after_descriptors_in_other_wordings(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


# ---- T5.6: các biên của luật vệ sinh khóa tên ----
def test_long_part_codes_in_parentheses_are_still_dropped_but_short_model_names_are_kept() -> None:
    assert name_key("Chuột Predator Cestus 330 (PMW920)", "Acer") == ("predator", "cestus", "330")
    assert "g304" in name_key("Chuột Logitech Lightspeed (G304)", "Logitech")


def test_full_size_keyboard_layout_is_not_mistaken_for_the_new_condition_label() -> None:
    layout = name_key("Bàn phím Keychron K2 100%", "Keychron")
    sold_new = name_key("Bàn phím Keychron K2 Mới 100%", "Keychron")

    assert "100%" in layout and "100%" not in sold_new
    assert sold_new == ("k2",)


def test_other_bracket_groups_and_blue_without_a_following_colour_word_are_kept() -> None:
    assert name_key("Chuột Pulsar X2 [Wireless Edition]", "Pulsar") == ("x2", "wireless", "edition")
    assert name_key("Chuột Pulsar X2 La Mã", "Pulsar") == ("x2", "la", "ma")  # "La" không sau xanh
    assert name_key("Chuột Pulsar X2 Xanh Lá", "Pulsar") == ("x2",)  # "lá" sau xanh là màu


def test_marketing_labels_do_not_change_the_display_name_either() -> None:
    assert canonical_name("Chuột Pulsar X2 (Mới 100%) | GearVN", MOUSE) == "Pulsar X2"


# ---- T5.7: phủ định và số đo, các biên ----
@pytest.mark.parametrize(
    ("category", "title", "field", "expected"),
    [
        (HEADSET, "Tai nghe Sony WH-CH520 có mic", "has_mic", True),
        (HEADSET, "Tai nghe Sony WH-CH520 kèm mic", "has_mic", True),
        (HEADSET, "Tai nghe Sony WH-CH520 chống ồn chủ động ANC", "anc", True),
        (HEADSET, "Tai nghe Sony WH-CH520 ANC, không mic", "anc", True),
        (HEADSET, "Tai nghe Sony WH-CH520 no ANC", "anc", None),
        (HEADSET, "Tai nghe Sony WH-CH520 without mic", "has_mic", None),
        (MOUSE, "Chuột Logitech M331 không dây", "connection", ["wireless_2_4"]),
        (MOUSE, "Chuột Logitech M331 có dây", "connection", ["wired"]),
        (
            MOUSE,
            "Chuột Logitech M331 Bluetooth + 2.4G",
            "connection",
            ["wireless_2_4", "bluetooth"],
        ),
        (MOUSE, "Chuột Logitech M331 2.4G (không Bluetooth)", "connection", ["wireless_2_4"]),
    ],
)
def test_negation_only_removes_the_feature_it_precedes(
    category: Category, title: str, field: str, expected: Any
) -> None:
    assert extract_specs(category, title, {}).specs.get(field) == expected


@pytest.mark.parametrize(
    ("title", "weight"),
    [
        ("Chuột Logitech M185 99g", 99),
        ("Chuột Logitech M185 2.4G 99g", 99),
        ("Chuột 2.4G Logitech M185 0.1kg", 100),
        ("Chuột Logitech M185 2.4G", None),  # chỉ có "2.4G" (2 g): ngoài 20–300 g
        ("Chuột Logitech M185 5000g", None),
    ],
)
def test_mouse_weight_reads_every_gram_value_and_keeps_only_a_plausible_one(
    title: str, weight: int | None
) -> None:
    assert extract_specs(MOUSE, title, {}).specs.get("weight_g") == weight


@pytest.mark.parametrize(("value", "buttons"), [("6", 6), ("99", 99), ("6 nút", 6), ("100", None)])
def test_button_count_is_kept_only_between_1_and_99(value: str, buttons: int | None) -> None:
    assert extract_specs(MOUSE, "Chuột X", {"Số nút": value}).specs.get("buttons") == buttons


def test_keyboard_layout_in_parentheses_is_not_a_marketing_label() -> None:
    k75 = name_key("Bàn phím Keychron K2 (75%)", "Keychron")
    k100 = name_key("Bàn phím Keychron K2 (100%)", "Keychron")

    assert "75%" in k75 and "100%" in k100 and k75 != k100


@pytest.mark.parametrize(
    "title",
    ["Bộ sạc laptop Dell 65W", "Bộ pin laptop Dell Latitude", "Bộ cáp chuyển Dell DA200"],
)
def test_accessories_after_a_type_word_do_not_take_the_laptop_brand(title: str) -> None:
    assert detect_brand(title) == "Unknown"


def test_a_name_that_is_only_the_brand_never_merges_without_a_model_code() -> None:
    from app.normalize.matcher import Candidate, decide_match

    assert name_key("Chuột Gaming Dell", "Dell") == ()
    candidates = [Candidate(1, "Dell", None, {})]

    decision = decide_match(MOUSE, "Dell", None, "Chuột Gaming Dell", {}, candidates)

    assert decision.product_id is None
