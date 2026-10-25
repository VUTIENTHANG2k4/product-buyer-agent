"""T4.8: chữ "captcha" chỉ là dấu hiệu khi nằm trong thẻ/thuộc tính hoặc `<title>`."""

import time

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.challenge import detect_challenge, has_captcha_marker, is_blocking_error_response
from app.scrapers.http.types import FetchResponse

PRODUCTS = "<div class='product'><h3>Chuột Mock</h3><span>290.000đ</span></div>"


def _resp(text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(
        url="https://shop.example/p", final_url="https://shop.example/p", status=status, text=text
    )


@pytest.mark.parametrize(
    "page",
    [
        f"<main>{PRODUCTS}<p>Đăng nhập app không cần nhập captcha, rất tiện.</p></main>",
        f"<main>{PRODUCTS}<h2>Captcha là gì?</h2><p>CAPTCHA giúp chống spam.</p></main>",
        f"<main>{PRODUCTS}<li>Không bị hỏi captcha khi đặt hàng</li></main>",
    ],
)
def test_the_word_in_visible_text_only_is_not_a_challenge(page: str) -> None:
    assert detect_challenge(_resp(page), SiteKey.fptshop) is None


@pytest.mark.parametrize(
    "markup",
    [
        "<div id='captcha'><p>Nhập mã: ABCDE</p></div>",  # trang chặn của mock-shop
        "<title>Captcha - Xác minh</title><body>Vui lòng đợi</body>",
        "<form action='/captcha/verify' method='post'><input name='answer'></form>",
        "<img src='/captcha.png' alt='mã'>",
        "<CAPTCHA-BOX></CAPTCHA-BOX>",
    ],
)
def test_the_word_inside_a_tag_or_the_title_is_a_challenge(markup: str) -> None:
    challenge = detect_challenge(_resp(PRODUCTS + markup), SiteKey.fptshop)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


@pytest.mark.parametrize(
    "marker",
    ["<p>Verify you are human</p>", "<p>Xác minh bạn không phải robot</p>", "<p>hcaptcha</p>"],
)
def test_specific_markers_still_count_in_visible_text(marker: str) -> None:
    assert has_captcha_marker(PRODUCTS + marker)


def test_title_without_a_closing_tag_is_still_scanned() -> None:
    assert has_captcha_marker("<html><title>CAPTCHA")


def test_an_unclosed_angle_bracket_does_not_hide_or_invent_markers() -> None:
    assert not has_captcha_marker("<p>nhập captcha 3 < 5")
    assert has_captcha_marker("<p class='captcha'>x</p><p>3 < 5")


def test_a_5xx_page_needs_the_word_in_markup_too() -> None:
    assert is_blocking_error_response(503, {}, "<p>please solve the captcha</p>") is False
    assert is_blocking_error_response(503, {}, "<div class='captcha'>please solve</div>") is True


def test_many_tags_are_scanned_in_linear_time() -> None:
    started = time.perf_counter()
    assert not has_captcha_marker("<p>captcha</p>" * 100_000)
    assert not has_captcha_marker("<" * 200_000)
    assert time.perf_counter() - started < 5.0
