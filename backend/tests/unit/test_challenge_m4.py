"""QA M4: ca biên của `detect_challenge` và `_strip_script_bodies` (T4.0b), không gọi mạng.

Bổ sung cho `test_challenge_inline_script.py`. Test `xfail(strict=True)` là lỗi đã tái hiện;
khi sửa xong, XPASS làm test đỏ và phải gỡ dấu xfail.
"""

import time
import unicodedata

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.challenge import detect_challenge, is_blocking_error_response
from app.scrapers.http.types import FetchResponse

URL = "https://shop.example/p/1"
PRODUCTS = "<main><h1>Chuột Logitech</h1><p>299.000đ</p></main>"


def _resp(text: str, status: int = 200, headers: dict[str, str] | None = None) -> FetchResponse:
    return FetchResponse(url=URL, final_url=URL, status=status, text=text, headers=headers or {})


def _kind(
    text: str, status: int = 200, headers: dict[str, str] | None = None
) -> ChallengeKind | None:
    found = detect_challenge(_resp(text, status, headers), SiteKey.fptshop)
    return found.kind if found else None


# --- Thẻ script ---------------------------------------------------------------------------------


def test_uppercase_script_with_a_very_long_attribute_list_is_still_stripped() -> None:
    attrs = "x" * 5_000
    page = f'<SCRIPT TYPE="text/javascript" data-x="{attrs}">var c = "captcha"</SCRIPT>{PRODUCTS}'
    assert _kind(page) is None


def test_greater_than_sign_inside_a_script_attribute_does_not_expose_the_body() -> None:
    assert _kind(f'<script data-x="a>b">var c = "captcha"</script>{PRODUCTS}') is None


def test_nested_script_markup_inside_a_js_string_does_not_expose_the_body() -> None:
    page = (
        f"<script>document.write('<script src=x><\\/script>'); var c='captcha'</script>{PRODUCTS}"
    )
    assert _kind(page) is None


def test_marker_after_the_script_that_ends_inside_a_js_string_is_visible_text() -> None:
    """Trình duyệt kết thúc script ở `</script` đầu tiên, nên phần sau là văn bản thường."""
    page = "<script>var s = '</script>'; var c = 'g-recaptcha';</script>"
    assert _kind(page) is ChallengeKind.captcha


@pytest.mark.parametrize("tag", ["<script", "<script ", "<script>", "<script data-a='1'"])
def test_text_ending_in_a_dangling_script_open_tag_keeps_earlier_markers_visible(tag: str) -> None:
    assert _kind(f"<p>Xác minh bạn không phải robot</p>{tag}") is ChallengeKind.captcha


def test_many_closed_inline_scripts_and_lookalike_tags_are_scanned_quickly() -> None:
    started = time.perf_counter()
    assert _kind("<script>var a = 1;</script>" * 50_000 + PRODUCTS) is None
    assert _kind("<scripts>" * 100_000 + PRODUCTS) is None
    assert time.perf_counter() - started < 5.0


def test_a_five_megabyte_page_without_markers_is_scanned_quickly() -> None:
    started = time.perf_counter()
    assert _kind("<p>" + "a" * 5_000_000 + "</p>") is None
    assert time.perf_counter() - started < 2.0


# --- Từ khóa và Unicode -------------------------------------------------------------------------


def test_vietnamese_marker_is_found_whatever_the_unicode_form() -> None:
    text = "<p>Xác minh bạn không phải robot</p>"
    assert _kind(text) is ChallengeKind.captcha
    assert _kind(unicodedata.normalize("NFD", text)) is ChallengeKind.captcha
    assert _kind(text.upper()) is ChallengeKind.captcha


@pytest.mark.parametrize(
    "markup",
    [
        '<input type="hidden" name="captcha_token">',
        '<img alt="Captcha" src="/c.png">',
        '<div data-hcaptcha="1"></div>',
        '<div class="CF-Challenge"></div>',
        "<p>VERIFY YOU ARE HUMAN</p>",
    ],
)
def test_marker_in_an_attribute_or_in_any_letter_case_is_a_challenge(markup: str) -> None:
    assert _kind(f"<body>{markup}{PRODUCTS}</body>") is ChallengeKind.captcha


@pytest.mark.parametrize("text", ["", "   ", "<html></html>", PRODUCTS])
def test_empty_or_plain_pages_are_not_challenges(text: str) -> None:
    assert _kind(text) is None


# --- Mã trạng thái và header --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"), [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)]
)
def test_blocking_status_wins_over_the_body(status: int, kind: ChallengeKind) -> None:
    assert _kind("<div id='captcha'></div>", status) is kind
    assert _kind(PRODUCTS, status) is kind


def test_cloudflare_challenge_header_on_a_5xx_is_blocking_even_with_a_plain_body() -> None:
    assert is_blocking_error_response(503, {"CF-Mitigated": "Challenge"}, "<html>x</html>") is True
    assert _kind("<html>x</html>", 503, {"cf-mitigated": "challenge"}) is ChallengeKind.captcha


def test_cloudflare_interstitial_needs_a_cloudflare_server_and_a_5xx() -> None:
    page = "<title>Just a moment...</title>"
    assert _kind(page, 503, {"Server": "cloudflare"}) is ChallengeKind.captcha
    assert _kind(page, 503, {"Server": "nginx"}) is None
    assert _kind(page, 200, {"Server": "cloudflare"}) is None


def test_plain_5xx_error_page_is_not_a_challenge() -> None:
    assert _kind("<h1>Internal Server Error</h1>", 500) is None
    assert is_blocking_error_response(502, {}, "") is False


def test_4xx_other_than_403_429_is_not_blocking_even_with_a_cloudflare_header() -> None:
    assert is_blocking_error_response(404, {"cf-mitigated": "challenge"}, "captcha") is False


# --- Hạn chế đã tái hiện ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markup",
    [
        '<div class="cf-turnstile" data-sitekey="0x4AAA"></div>',
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async></script>',
    ],
)
def test_turnstile_widget_is_a_challenge(markup: str) -> None:
    assert _kind(f"<body>{markup}</body>") is ChallengeKind.captcha


@pytest.mark.parametrize(
    "markup",
    ["<!-- captcha widget removed -->", "<style>.grecaptcha-badge{visibility:hidden}</style>"],
    ids=["html-comment", "style-body"],
)
def test_marker_only_in_a_comment_or_stylesheet_is_not_a_challenge(markup: str) -> None:
    assert _kind(f"<html><head>{markup}</head><body>{PRODUCTS}</body></html>") is None


def test_the_word_captcha_in_a_product_review_paragraph_is_not_a_challenge() -> None:
    page = f"<main>{PRODUCTS}<p>Đăng nhập app không cần nhập captcha, rất tiện.</p></main>"
    assert _kind(page) is None
