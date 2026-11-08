"""QA X1: điện thoại, biên của trích xuất thông số, hãng, tên chuẩn và ghép mẫu (docs/04 §5.5, §7).

Test `xfail(strict=True)` mã `BUG-X1-n` là lỗi đã tái hiện: khi sửa xong, XPASS làm test đỏ và phải
gỡ dấu xfail. Dữ liệu hư cấu, không gọi mạng.
"""

import random
import time
import unicodedata
from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.extract import extract_specs
from app.normalize.matcher import Candidate, decide_match, specs_compatible
from app.normalize.names import canonical_name, name_key
from app.normalize.specs.phone import PhoneSpecs, extract_phone

PHONE = Category.phone


def specs_of(title: str, raw: dict[str, Any] | None = None) -> dict[str, object]:
    return extract_phone(title, raw or {}).model_dump(exclude_none=True)


def merges(first: str, second: str) -> bool:
    """`second` có được ghép vào sản phẩm đã tạo từ `first` không (như pipeline làm)."""
    brand_first, brand_second = detect_brand(first), detect_brand(second)
    if brand_first != brand_second:
        return False
    candidate = Candidate(1, canonical_name(first, PHONE), None, extract_specs(PHONE, first).specs)
    decision = decide_match(
        PHONE,
        brand_second,
        None,
        canonical_name(second, PHONE),
        extract_specs(PHONE, second).specs,
        [candidate],
    )
    return decision.product_id == 1


# ---- tiêu đề thực tế khó: RAM / bộ nhớ trong ----
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Điện thoại iPhone 17 Pro Max 1TB", {"storage_gb": 1000}),
        ("Điện thoại Samsung Galaxy Z Fold8 12GB+512GB", {"ram_gb": 12, "storage_gb": 512}),
        (
            "Điện thoại Xiaomi Redmi Note 13 Pro+ 5G 8GB/256GB",
            {"ram_gb": 8, "storage_gb": 256},
        ),
        ("Máy tính bảng Honor Pad X8b 6GB/128GB", {"ram_gb": 6, "storage_gb": 128}),
        ("Điện thoại Mock RAM 8GB ROM 128GB", {"ram_gb": 8, "storage_gb": 128}),
        ("Điện thoại Mock 8GB/128 GB", {"ram_gb": 8, "storage_gb": 128}),
        ("Điện thoại Mock 8 GB / 256 GB", {"ram_gb": 8, "storage_gb": 256}),
        ("Điện thoại Mock 8Gb/256Gb", {"ram_gb": 8, "storage_gb": 256}),
        ("Điện thoại Mock 8gb/256gb", {"ram_gb": 8, "storage_gb": 256}),
        ("Điện thoại Mock 8GB + 256GB", {"ram_gb": 8, "storage_gb": 256}),
        ("Điện thoại Mock 8GB | 256GB", {"ram_gb": 8, "storage_gb": 256}),
        ("iPhone 16 Pro 256 GB", {"storage_gb": 256}),
        ("Điện thoại Mock 2TB", {"storage_gb": 2000}),
        ("Điện thoại Mock 1 TB", {"storage_gb": 1000}),
        ("ＳＡＭＳＵＮＧ Ｇａｌａｘｙ Ａ５７ ８ＧＢ／１２８ＧＢ", {"ram_gb": 8, "storage_gb": 128}),
    ],
)
def test_realistic_phone_titles_give_ram_and_storage(title: str, expected: dict[str, int]) -> None:
    assert specs_of(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Điện thoại Nokia 105",  # máy phổ thông không dung lượng
        "Điện thoại Mock 0GB/0GB",
        "Điện thoại Mock 99999GB",  # quá 4 chữ số: không phải dung lượng
        "Điện thoại Mock 128GB/256GB/512GB",  # danh sách tùy chọn của cả dòng máy
        "Điện thoại Mock 8GB 128GB 256GB",
        "Điện thoại Mock 12GB+256GB Xanh 12GB",  # ba dung lượng
        "",
        "   ",
        "GB TB GB",
    ],
)
def test_titles_without_a_trustworthy_pair_leave_memory_empty(title: str) -> None:
    assert specs_of(title) == {}


def test_nfd_title_gives_the_same_specs_as_nfc() -> None:
    title = "Điện thoại Samsung Galaxy A57 5G 8GB/128GB Đen"
    nfd = unicodedata.normalize("NFD", title)
    assert nfd != title
    assert specs_of(nfd) == specs_of(title) == {"ram_gb": 8, "storage_gb": 128}
    assert detect_brand(nfd) == "Samsung"
    assert canonical_name(nfd, PHONE) == canonical_name(title, PHONE)


def test_vietnamese_without_diacritics_matches_the_accented_title() -> None:
    plain = "Dien thoai Samsung Galaxy A57 5G 8GB/128GB"
    accented = "Điện thoại Samsung Galaxy A57 5G 8GB/128GB"
    assert canonical_name(plain, PHONE) == canonical_name(accented, PHONE)
    assert detect_brand(plain) == detect_brand(accented) == "Samsung"
    assert merges(plain, accented)


def test_uppercase_title_keeps_the_brand_and_the_model_key() -> None:
    upper = "ĐIỆN THOẠI SAMSUNG GALAXY A57 5G 8GB/128GB"
    assert detect_brand(upper) == "Samsung"
    assert name_key(canonical_name(upper, PHONE), "Samsung") == (
        "galaxy",
        "a57",
        "5g",
        "8gb",
        "128gb",
    )


# ---- bảng thông số: kiểu lạ, nhãn lạ, giá trị lạ ----
def test_label_values_of_the_wrong_type_are_ignored_without_error() -> None:
    raw: dict[Any, Any] = {
        "RAM": 8,
        "Bộ nhớ trong": None,
        5: "x",
        "Pin": ["5000 mAh"],
        "Màn hình": {},
    }
    assert specs_of("Điện thoại Mock X", raw) == {}


def test_label_values_are_read_with_vietnamese_without_diacritics() -> None:
    raw = {"Bo nho trong": "256 GB", "Dung luong RAM": "12 GB", "Kich thuoc man hinh": "6,7 inch"}
    assert specs_of("Điện thoại Mock X", raw) == {
        "ram_gb": 12,
        "storage_gb": 256,
        "screen_in": 6.7,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0 mAh", None),
        ("5 000 mAh", None),
        ("5.000.000 mAh", None),
        ("99999 mAh", None),
        ("500 mAh", 500),
        ("30.000 mAh", 30000),
        ("4.500 mAh / 4.400 mAh (min)", 4500),
        ("5000mAh", 5000),
    ],
)
def test_battery_boundaries(value: str, expected: int | None) -> None:
    got = specs_of("Điện thoại Mock X", {"Dung lượng pin": value}).get("battery_mah")
    assert got == expected


def test_conflicting_battery_labels_prefer_the_capacity_label() -> None:
    raw = {"Pin": "5000mAh", "Dung lượng pin": "4000 mAh"}
    assert specs_of("Điện thoại Mock X", raw)["battery_mah"] == 4000


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0 inch", None),
        ("1.9 inch", None),
        ("2 inch", 2.0),
        ("12 inch", 12.0),
        ('6.57" - Tần số quét 120 Hz', 6.57),
        ("6,7", 6.7),
    ],
)
def test_screen_boundaries(value: str, expected: float | None) -> None:
    got = specs_of("Điện thoại Mock X", {"Màn hình rộng": value}).get("screen_in")
    assert got == expected


def test_negative_battery_and_screen_values_are_not_read_as_positive() -> None:
    assert "battery_mah" not in specs_of("Điện thoại Mock X", {"Dung lượng pin": "-5000 mAh"})
    assert "screen_in" not in specs_of("Điện thoại Mock X", {"Màn hình rộng": "-6.7 inch"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Pin: -5.000mAh", None),
        ("−5000 mAh", None),  # dấu trừ Unicode
        ("(-5000 mAh)", None),
        ("-5000 mAh, 4500 mAh", 4500),  # khớp âm bị bỏ, khớp dương sau đó được dùng
        ("4000-5000 mAh", 5000),  # khoảng: gạch nối không phải dấu trừ
        ("Pin 5000mAh", 5000),
    ],
)
def test_battery_sign_is_only_a_minus_when_it_stands_before_the_number(
    value: str, expected: int | None
) -> None:
    assert specs_of("Điện thoại Mock X", {"Pin": value}).get("battery_mah") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("−6.7 inch", None),
        ("-6.7 inch, 120 Hz", None),
        ("6.7 inch - 120Hz", 6.7),
        ("Acer-6.7 inch", 6.7),  # gạch nối trong tên, không phải dấu trừ
        ('-6.7" hoặc 6.1"', 6.1),
    ],
)
def test_screen_sign_is_only_a_minus_when_it_stands_before_the_number(
    value: str, expected: float | None
) -> None:
    assert specs_of("Điện thoại Mock X", {"Màn hình rộng": value}).get("screen_in") == expected


def test_a_chipset_text_longer_than_80_characters_is_dropped_not_truncated() -> None:
    assert specs_of("Điện thoại Mock X", {"Chip xử lý": "A" * 80})["chipset"] == "A" * 80
    assert "chipset" not in specs_of("Điện thoại Mock X", {"Chip xử lý": "A" * 81})


def test_a_long_chipset_label_does_not_hide_a_later_valid_one() -> None:
    raw = {"Chip xử lý (CPU)": "A" * 200, "Chipset": "Apple A18"}
    assert specs_of("Điện thoại Mock X", raw)["chipset"] == "Apple A18"


def test_table_ram_above_the_phone_range_is_ignored() -> None:
    assert specs_of("iPhone 16", {"RAM": "128 GB"}) == {}
    assert specs_of("iPhone 16", {"RAM": "24 GB"}) == {"ram_gb": 24}


def test_table_storage_above_4tb_is_ignored() -> None:
    assert specs_of("iPhone 16", {"Bộ nhớ trong": "8 TB"}) == {}
    assert specs_of("iPhone 16", {"Bộ nhớ trong": "4 TB"}) == {"storage_gb": 4000}


def test_extract_specs_confidence_for_phone_boundaries() -> None:
    assert extract_specs(PHONE, "Điện thoại Nokia 105").missing == ("ram_gb", "storage_gb")
    full = extract_specs(PHONE, "Điện thoại Mock 8GB/128GB")
    assert (full.missing, full.confidence) == ((), 1.0)
    # Mọi giá trị hỏng cùng lúc: không ném lỗi, specs rỗng.
    junk = extract_specs(PHONE, "x" * 50_000, {"RAM": "9" * 10_000, "Pin": "0" * 10_000})
    assert junk.specs == {}


def test_extract_phone_never_raises_on_random_text() -> None:
    rng = random.Random(7)
    alphabet = "0123456789 GBTBgbmAhinch.,/+()-xXđệ́１\x00\n"
    for _ in range(300):
        title = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        raw = {"RAM": title[::-1], "Pin": title, "Màn hình": title[5:], "Bộ nhớ trong": title[3:]}
        assert isinstance(extract_phone(title, raw), PhoneSpecs)


def test_phone_specs_ignores_unknown_keys_like_the_other_groups() -> None:
    assert PhoneSpecs.model_validate({"ram_gb": 8, "sim": "2 SIM"}).model_dump(
        exclude_none=True
    ) == {"ram_gb": 8}


# ---- hãng ----
@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Điện thoại di động Samsung Galaxy A57", "Samsung"),
        ("Điện thoại thông minh Xiaomi 15T", "Xiaomi"),
        ("Điện thoại Realme 14 Pro+ 5G 12GB/256GB", "realme"),
        ("Điện thoại POCO X7 Pro 5G 8GB/256GB", "Xiaomi"),
        ("Dien thoai iPhone 16 128GB", "Apple"),
        ("[Trả góp 0%] Điện thoại Samsung Galaxy A57 5G 8GB/128GB", "Samsung"),
        ("🔥 Điện thoại iPhone 16 128GB", "Apple"),
        ("Máy tính bảng Apple iPad 11 128GB Wifi", "Apple"),
        ("Điện thoại Moto G84 5G", "Motorola"),
        ("ĐTDĐ Samsung S26 SM-S942B/DS, 12GB+256GB", "Samsung"),
    ],
)
def test_more_phone_brands(title: str, brand: str) -> None:
    assert detect_brand(title) == brand


@pytest.mark.parametrize(
    "title",
    [
        "Dây đeo điện thoại Samsung",
        "Giá đỡ điện thoại iPhone",
        "Ốp lưng cho điện thoại Samsung Galaxy A57",
        "Sạc điện thoại Samsung 25W",
        "Điện thoại Mock X",
    ],
)
def test_accessories_and_unknown_makers_stay_unknown(title: str) -> None:
    assert detect_brand(title) == UNKNOWN_BRAND


def test_smartphone_prefix_is_skipped_when_looking_for_the_brand() -> None:
    # names.py và docs/04 §7 coi "Smartphone" là tiền tố loại cùng "Điện thoại"/"ĐTDĐ".
    assert detect_brand("Smartphone Samsung Galaxy A57 5G 8GB/128GB") == "Samsung"


def test_hmd_phones_have_a_brand() -> None:
    assert detect_brand("Điện thoại HMD Fusion 5G 8GB/256GB") != UNKNOWN_BRAND


# ---- tên chuẩn ----
@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Điện thoại iPhone 17 Pro Max 1TB Cam Vũ Trụ", "iPhone 17 Pro Max 1TB"),
        (
            "Điện thoại Samsung Galaxy Z Fold8 12GB+512GB Xanh Navy SM-F966BZBGXXV",
            "Samsung Galaxy Z Fold8 12GB 512GB",
        ),
        (
            "Điện thoại Xiaomi Redmi Note 13 Pro+ 5G 8GB/256GB Tím",
            "Xiaomi Redmi Note 13 Pro+ 5G 8GB 256GB",
        ),
        ("Máy tính bảng Honor Pad X8b 6GB/128GB", "Honor Pad X8b 6GB 128GB"),
        (
            "Điện thoại Samsung Galaxy A57 5G 8GB/128GB Titan Sa Mạc",
            "Samsung Galaxy A57 5G 8GB 128GB",
        ),
        ("Điện thoại Nokia 105", "Nokia 105"),
        (
            "Điện thoại Samsung Galaxy A57 5G (8GB/128GB) (Chính hãng VN/A)",
            "Samsung Galaxy A57 5G 8GB 128GB",
        ),
        ("  Điện thoại   iPhone 16   128GB  ", "iPhone 16 128GB"),
    ],
)
def test_canonical_name_of_hard_phone_titles(title: str, name: str) -> None:
    assert canonical_name(title, PHONE) == name


def test_canonical_name_is_never_empty() -> None:
    for title in ["Điện thoại", "ĐTDĐ", "Điện thoại Samsung", "128GB", "5G"]:
        assert canonical_name(title, PHONE).strip() != ""


def test_canonical_name_of_the_plus_variant_differs_from_the_plain_one() -> None:
    plain = canonical_name("Điện thoại Samsung Galaxy S25 8GB/256GB", PHONE)
    plus = canonical_name("Điện thoại Samsung Galaxy S25+ 8GB/256GB", PHONE)
    assert plain != plus


def test_canonical_name_keeps_storage_written_with_a_space() -> None:
    name = canonical_name("Điện thoại Samsung Galaxy A57 5G 8GB/128 GB Đen", PHONE)
    assert "128" in name


def test_pipe_separated_shop_suffix_is_cut_but_memory_before_it_is_kept() -> None:
    name = canonical_name("Điện thoại Samsung Galaxy A57 5G 8GB/128GB | Nguyễn Kim", PHONE)
    assert name == "Samsung Galaxy A57 5G 8GB 128GB"


def test_long_title_with_many_capacities_is_bounded() -> None:
    title = "Điện thoại Mock X " + " ".join(f"{n}GB" for n in range(1, 4000))
    start = time.perf_counter()
    canonical_name(title, PHONE)
    extract_phone(title, {})
    assert time.perf_counter() - start < 5  # chỉ chặn hành vi mũ; đo tương đối ở test cũ


# ---- ghép: cặp phải gộp ----
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Điện thoại iPhone 16 128GB Đen", "iPhone 16 128GB Trắng (MYE73ZP/A)"),
        ("Điện thoại Samsung Galaxy A57 5G 8GB/128GB Xanh", "Samsung Galaxy A57 5G 8GB+128GB Đen"),
        ("Điện thoại Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 5G (8GB/128GB) Black"),
        ("Điện thoại Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 5G 8Gb/128Gb"),
        ("Điện thoại Samsung Galaxy Z Fold8 12GB+512GB", "Samsung Galaxy Z Fold8 12GB/512GB"),
        (
            "Samsung Galaxy S25 Ultra Titanium Black 12GB/256GB",
            "Samsung Galaxy S25 Ultra Titanium Gray 12GB/256GB",
        ),
        (
            "Điện thoại Xiaomi Redmi 14C 4GB/128GB Xanh Rêu",
            "Điện thoại Xiaomi Redmi 14C 4GB/128GB Đen",
        ),
        ("Điện thoại iPhone 16 Pro 256GB Titan Sa Mạc", "Điện thoại iPhone 16 Pro 256GB Titan Đen"),
        ("Điện thoại Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 5G 128GB 8GB Xanh"),
    ],
)
def test_same_phone_in_another_colour_or_spelling_is_merged(first: str, second: str) -> None:
    assert merges(first, second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Điện thoại iPhone 16 Pro 256GB", "iPhone 16 Pro 256 GB"),
        ("Điện thoại iPhone 17 Pro Max 1TB", "iPhone 17 Pro Max 1 TB"),
    ],
)
def test_capacity_written_with_a_space_is_the_same_phone(first: str, second: str) -> None:
    assert merges(first, second)


# ---- ghép: cặp không được gộp nhầm ----
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 8GB/128GB"),  # 5G / không 5G
        ("Samsung Galaxy A07 LTE 4GB/128GB", "Samsung Galaxy A07 4G 4GB/128GB"),
        ("Samsung Galaxy S25 8GB/256GB", "Samsung Galaxy S25+ 8GB/256GB"),
        ("Samsung Galaxy S25 Ultra 12GB/256GB", "Samsung Galaxy S25 FE 12GB/256GB"),
        ("Samsung Galaxy S25 Ultra 12GB/256GB", "Samsung Galaxy S25 12GB/256GB"),
        ("Xiaomi Redmi Note 13 Pro 5G 8GB/256GB", "Xiaomi Redmi Note 13 Pro+ 5G 8GB/256GB"),
        ("Xiaomi Redmi Note 13 Pro 5G 8GB/256GB", "Xiaomi Redmi Note 13 5G 8GB/256GB"),
        ("Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 5G 12GB/128GB"),  # RAM khác
        ("Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A57 5G 8GB/256GB"),  # bộ nhớ khác
        ("iPhone 16 128GB", "iPhone 16 256GB"),
        ("iPhone 16 128GB", "iPhone 16 Plus 128GB"),
        ("iPhone 16 128GB", "iPhone 16e 128GB"),
        ("iPhone 16 128GB", "iPhone 16 Pro 128GB"),
        ("iPhone 16 Pro 128GB", "iPhone 16 Pro Max 128GB"),
        ("iPhone 17 Pro Max 1TB", "iPhone 17 Pro Max 512GB"),
        ("Honor 400 8GB/256GB", "Honor 400 Pro 8GB/256GB"),
        ("Honor Pad X8b 6GB/128GB", "Honor Pad X8a 6GB/128GB"),
        ("Samsung Galaxy Z Fold8 12GB+512GB", "Samsung Galaxy Z Flip8 12GB+512GB"),
        ("Samsung Galaxy A57 5G 8GB/128GB", "Samsung Galaxy A37 5G 8GB/128GB"),
        ("Nokia 105 4G", "Nokia 105"),
        ("Nokia 105", "Nokia 106"),
        ("Điện thoại Redmi 12 8GB(+8GB)/256GB", "Điện thoại Redmi 12 8GB/256GB"),
    ],
)
def test_different_phones_are_not_merged(first: str, second: str) -> None:
    assert not merges(first, second)
    assert not merges(second, first)


def test_the_same_title_on_two_brands_is_never_merged() -> None:
    assert not merges("Điện thoại Samsung Mock X 8GB/128GB", "Điện thoại Xiaomi Mock X 8GB/128GB")


def test_a_detached_plus_sign_still_separates_the_plus_model() -> None:
    assert not merges("Samsung Galaxy S25 8GB/256GB", "Samsung Galaxy S25 + 8GB/256GB")
    assert not merges("Samsung Galaxy S25 + 8GB/256GB", "Samsung Galaxy S25 8GB/256GB")


def test_a_detached_plus_sign_is_the_same_model_as_the_attached_one() -> None:
    assert merges("Samsung Galaxy S25+ 8GB/256GB", "Samsung Galaxy S25 + 8GB/256GB")
    assert (
        canonical_name("Samsung Galaxy S25 + 8GB/256GB", PHONE) == "Samsung Galaxy S25+ 8GB 256GB"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("+ Samsung Galaxy S25 8GB/256GB", "Samsung Galaxy S25 8GB 256GB"),
        ("Samsung Galaxy S25 8GB + 256GB", "Samsung Galaxy S25 8GB 256GB"),
        ("Samsung Galaxy S25 ++ 8GB/256GB", "Samsung Galaxy S25 8GB 256GB"),
    ],
)
def test_a_plus_sign_that_is_not_a_model_suffix_is_still_dropped(title: str, expected: str) -> None:
    assert canonical_name(title, PHONE) == expected


def test_unknown_brand_phones_are_never_merged_by_name() -> None:
    title = "Điện thoại Mock X 8GB/256GB Đen"
    candidate = Candidate(1, canonical_name(title, PHONE), None, extract_specs(PHONE, title).specs)
    decision = decide_match(
        PHONE, UNKNOWN_BRAND, None, canonical_name(title, PHONE), candidate.specs, [candidate]
    )
    assert decision.product_id is None


# ---- specs_compatible / decide_match với specs thiếu một phía ----
@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"ram_gb": 8, "storage_gb": 128}, {"storage_gb": 128}, True),  # iPhone thiếu RAM
        ({}, {}, True),
        ({"ram_gb": 8}, {"ram_gb": 12}, False),
        ({"storage_gb": 128}, {"storage_gb": 256}, False),
        ({"ram_gb": None, "storage_gb": 128}, {"ram_gb": 8, "storage_gb": 128}, True),
        ({"ram_gb": 8}, {"storage_gb": 256}, True),  # không có trường chung nào để mâu thuẫn
        ({"chipset": "A18"}, {"chipset": "A17"}, True),  # chipset không phải trường bắt buộc
        ({"ram_gb": 8.0}, {"ram_gb": 8}, True),
        ({"ram_gb": [8]}, {"ram_gb": [8]}, True),
        ({"ram_gb": [8, [1]]}, {"ram_gb": [8]}, False),  # dữ liệu hỏng không làm lỗi
    ],
)
def test_specs_compatible_for_phones(
    left: dict[str, Any], right: dict[str, Any], expected: bool
) -> None:
    assert specs_compatible(PHONE, left, right) is expected


def test_strict_mode_needs_both_required_fields_on_both_sides() -> None:
    full = {"ram_gb": 8, "storage_gb": 128}
    assert specs_compatible(PHONE, full, full, strict=True)
    assert not specs_compatible(PHONE, full, {"storage_gb": 128}, strict=True)
    assert not specs_compatible(PHONE, {}, {}, strict=True)


def test_phone_with_missing_specs_on_both_sides_is_still_split_by_name() -> None:
    # Candidate không có specs (sản phẩm cũ): chỉ còn khóa tên để phân biệt 128GB và 256GB.
    old = Candidate(1, "iPhone 16 128GB", None, {})
    decision = decide_match(PHONE, "Apple", None, "iPhone 16 256GB", {"storage_gb": 256}, [old])
    assert decision.product_id is None
    same = decide_match(PHONE, "Apple", None, "iPhone 16 128GB", {"storage_gb": 128}, [old])
    assert same.product_id == 1


def test_decide_match_with_several_candidates_is_deterministic() -> None:
    candidates = [
        Candidate(7, "Samsung Galaxy A57 5G 8GB 128GB", None, {"ram_gb": 8, "storage_gb": 128}),
        Candidate(3, "Samsung Galaxy A57 5G 8GB 128GB", None, {"ram_gb": 8, "storage_gb": 128}),
        Candidate(5, "Samsung Galaxy A57 5G 8GB 256GB", None, {"ram_gb": 8, "storage_gb": 256}),
    ]
    results = set()
    for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2]):
        decision = decide_match(
            PHONE,
            "Samsung",
            None,
            "Samsung Galaxy A57 5G 8GB 128GB",
            {"ram_gb": 8, "storage_gb": 128},
            [candidates[i] for i in order],
        )
        results.add(decision.product_id)
    assert results == {3}  # điểm bằng nhau thì lấy id nhỏ nhất, không phụ thuộc thứ tự đầu vào


def test_phone_model_code_never_forces_a_merge_across_storage_variants() -> None:
    # Dù một nguồn nào đó đưa mã hãng (mpn) vào, điện thoại không dùng mã để ghép.
    a = Candidate(1, "OPPO Reno16 F 5G 8GB 256GB", "CPH2859", {"ram_gb": 8, "storage_gb": 256})
    decision = decide_match(
        PHONE,
        "OPPO",
        "CPH2859",
        "OPPO Reno16 F 5G 8GB 512GB",
        {"ram_gb": 8, "storage_gb": 512},
        [a],
    )
    assert decision.product_id is None
    assert decision.code_taken is True


# ---- trích xuất: lỗi đã tái hiện ----
def test_cpu_clock_label_is_not_the_chipset() -> None:
    assert "chipset" not in specs_of("Điện thoại Mock X", {"Tốc độ CPU": "4 nhân 2.5 GHz"})


def test_absurd_storage_in_the_title_is_ignored_like_in_the_table() -> None:
    assert "storage_gb" not in specs_of("Điện thoại Mock X 9999GB")
    assert specs_of("Điện thoại Mock X 8GB/16TB").get("storage_gb") != 16000


def test_small_labelled_internal_storage_is_read() -> None:
    assert specs_of("Điện thoại Mock X", {"Bộ nhớ trong": "16 GB"}) == {"storage_gb": 16}
