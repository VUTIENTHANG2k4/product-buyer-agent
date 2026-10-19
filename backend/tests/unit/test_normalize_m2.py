"""QA M2: đầu vào lạ cho chuẩn hóa giá, URL, hãng (docs/04 §7).

Ca đỏ do lỗi ứng dụng được giữ bằng `xfail(strict=True)`; sửa xong thì XPASS báo đỏ, khi đó gỡ dấu.
"""

import logging
import time
import unicodedata

import pytest

from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.price import MAX_PRICE_VND, MIN_PRICE_VND, parse_price
from app.normalize.url import MAX_URL_LENGTH, clean_url

# --- parse_price ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "9.990.000₫ -5%",
        "9.990.000₫ (-5%)",
        "9.990.000₫ Giảm 5%",
        "12.990.000₫ Trả góp 0%",
        "12.990.000₫ 3 cái",
        "9 990 000 VND -5%",
    ],
)
def test_a_discount_badge_next_to_the_price_is_not_glued_into_the_price(raw: str) -> None:
    assert parse_price(raw) in (None, 9_990_000, 12_990_000)


@pytest.mark.parametrize("raw", ["-27.490.000₫", "-2.000.000₫", "−2.000.000₫"])
def test_a_negative_amount_is_never_read_as_a_positive_price(raw: str) -> None:
    assert parse_price(raw) is None


def test_a_huge_digit_string_returns_none_instead_of_raising() -> None:
    assert parse_price("9" * 5000) is None


@pytest.mark.parametrize(
    "raw",
    [
        "27.490.000 - 29.990.000",
        "27.490.000₫ - 29.990.000₫",
        "27.490.000₫ 24.990.000₫",
        "Từ 5tr",
        "5tr",
        "27,5 triệu",
        "1e7",
        "Liên hệ",
        "Hết hàng",
        "",
        "   ",
        "₫",
    ],
)
def test_ambiguous_or_unparseable_prices_are_none_never_a_guess(raw: str) -> None:
    assert parse_price(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("27.490.000₫", 27_490_000),
        ("27 490 000 ₫", 27_490_000),  # NBSP giữa các nhóm
        ("27 490 000₫", 27_490_000),  # NNBSP (định dạng vi/fr của ICU)
        ("２７．４９０．０００", 27_490_000),  # full-width
        ("27.490.000,5", 27_490_000),  # phần lẻ dưới 1 đồng
        ("27,490,000.00", 27_490_000),
        ("27490000", 27_490_000),
        ("  27.490.000đ  ", 27_490_000),
    ],
)
def test_common_vietnamese_formats_give_the_same_integer(raw: str, expected: int) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (MIN_PRICE_VND - 1, None),
        (MIN_PRICE_VND, MIN_PRICE_VND),
        (MAX_PRICE_VND, MAX_PRICE_VND),
        (MAX_PRICE_VND + 1, None),
        (0, None),
        (-1, None),
        (True, None),
        ("1.234.567.890", None),
        ("500.000.001", None),
        ("9.999", None),
    ],
)
def test_price_range_boundaries(raw: str | int, expected: int | None) -> None:
    assert parse_price(raw) == expected


def test_out_of_range_price_logs_a_truncated_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.normalize.price"):
        assert parse_price("1" + ".000" * 40) is None
    assert caplog.records and all(len(record.getMessage()) < 200 for record in caplog.records)


# --- clean_url --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("with_port", "without_port"),
    [
        ("https://shop.example:443/p/x", "https://shop.example/p/x"),
        ("http://shop.example:80/p/x", "http://shop.example/p/x"),
        ("HTTPS://Shop.Example:443/p/x", "https://shop.example/p/x"),
    ],
)
def test_default_ports_do_not_create_a_second_key_for_the_same_page(
    with_port: str, without_port: str
) -> None:
    assert clean_url(with_port) == clean_url(without_port)


@pytest.mark.parametrize(
    "dirty",
    [
        "https://shop.example/p\x00x",
        "https://shop.example/p\x07x",
        "https://shop.example/p x",
        "https://shop.example/p\x7fx",
        "https://sh op.example/p",
    ],
)
def test_control_characters_and_spaces_never_reach_the_stored_url(dirty: str) -> None:
    try:
        cleaned = clean_url(dirty)
    except ValueError:
        return
    assert all(0x20 < ord(char) < 0x7F or ord(char) > 0x9F for char in cleaned)


def test_idn_host_and_its_punycode_form_are_the_same_key() -> None:
    assert clean_url("https://bücher.example/p") == clean_url("https://xn--bcher-kva.example/p")


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ("https://ShOp.Example/P/X", "https://shop.example/P/X"),  # host thường, path giữ nguyên
        ("https://user:pw@shop.example/p", "https://shop.example/p"),
        ("https://shop.example/p?UTM_Source=x&Fbclid=1&GCLID=2&a=1", "https://shop.example/p?a=1"),
        ("https://shop.example/p#", "https://shop.example/p"),
        ("https://shop.example/p?", "https://shop.example/p"),
        ("https://shop.example?", "https://shop.example"),
        ("https://shop.example/p?a=1&a=2", "https://shop.example/p?a=1&a=2"),  # tham số lặp giữ
        ("https://shop.example/a//b", "https://shop.example/a//b"),  # '//' trong path giữ nguyên
        ("https://shop.example:8443/p", "https://shop.example:8443/p"),
        ("  https://shop.example/p\n", "https://shop.example/p"),
        ("https://[::1]:8080/p", "https://[::1]:8080/p"),
        ("https://shop.example/p?a", "https://shop.example/p?a="),
    ],
)
def test_clean_url_normalizes_without_dropping_meaningful_parts(dirty: str, clean: str) -> None:
    assert clean_url(dirty) == clean


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "shop.example/p",
        "/p/x",
        "ftp://shop.example/p",
        "javascript:alert(1)",
        "mailto:a@b.example",
        "https:///p",
        "https://shop.example:abc/p",
        "https://shop.example:99999/p",
        "https://shop.example/" + "a" * MAX_URL_LENGTH,
    ],
)
def test_clean_url_rejects_what_is_not_an_absolute_http_url_with_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        clean_url(bad)


def test_url_length_limit_applies_to_the_cleaned_form_and_to_percent_expansion() -> None:
    at_limit = "https://shop.example/" + "a" * (MAX_URL_LENGTH - len("https://shop.example/"))
    assert clean_url(at_limit) == at_limit
    with pytest.raises(ValueError):
        clean_url(at_limit + "a")
    with pytest.raises(ValueError):  # 300 ký tự có dấu nở ra > 2000 sau khi mã hóa %XX
        clean_url("https://shop.example/p?q=" + "ạ" * 300)


@pytest.mark.parametrize(
    "url",
    [
        "https://shop.example/p?q=a%20b&c=%C3%A9",
        "https://SHOP.example:8443/p/?a=1&a=2&utm_x=1#f",
        "https://shop.example/p?x=1;y=2",
        "https://shop.example/p?q=%25",
        "https://shop.example/p?q=a+b%2Bc",
        "https://shop.example/p?q=%2F&r=/&s=?",
        "https://shop.example/Sản-phẩm?từ=khóa",
    ],
)
def test_clean_url_is_idempotent(url: str) -> None:
    once = clean_url(url)
    assert clean_url(once) == once


# --- detect_brand -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Acerbis Helmet X", UNKNOWN_BRAND),  # 'Acer' lồng trong từ khác
        ("HPE ProLiant Server", UNKNOWN_BRAND),
        ("MSIGaming Mouse", UNKNOWN_BRAND),
        ("Hpx Cable", UNKNOWN_BRAND),
        ("Bàn phím cho MacBook Pro", UNKNOWN_BRAND),  # chỉ so khớp ở đầu tên
        ("Ốp lưng iPhone 15", UNKNOWN_BRAND),
        ("", UNKNOWN_BRAND),
        ("   ", UNKNOWN_BRAND),
        ("Laptop Gaming Gaming Acer Nitro 5", "Acer"),  # nhiều tiền tố loại sản phẩm
        ("LAPTOP   ACER   ASPIRE", "Acer"),
        ("Laptop Acer Swift 3", "Acer"),
        ("Chuột Gaming Không dây Razer DeathAdder", "Razer"),
    ],
)
def test_brand_matches_only_at_the_start_and_only_whole_words(title: str, expected: str) -> None:
    assert detect_brand(title) == expected


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_brand_detection_does_not_depend_on_unicode_normalization_form(form: str) -> None:
    for title in ("Chuột Logitech G502", "Tai nghe Edifier W820NB", "Bàn phím cơ Keychron K2"):
        assert detect_brand(unicodedata.normalize(form, title)) == detect_brand(title)
        assert detect_brand(title) != UNKNOWN_BRAND


def test_a_hundred_thousand_character_title_is_fast_and_unknown() -> None:
    started = time.perf_counter()
    assert detect_brand("x" * 100_000 + " acer") == UNKNOWN_BRAND
    assert detect_brand("Laptop Acer " + "y" * 100_000) == "Acer"
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "title",
    [
        "A​cer Aspire 5",
        "Laptop ​Acer Aspire 5",
        "Ａｃｅｒ Aspire 5",
        "[Mới 100%] Laptop Acer Aspire 5",
    ],
)
def test_invisible_characters_and_leading_tags_do_not_hide_the_brand(title: str) -> None:
    assert detect_brand(title) == "Acer"
