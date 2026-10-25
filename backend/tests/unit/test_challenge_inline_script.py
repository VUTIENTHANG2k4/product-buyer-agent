"""T4.0b: từ khóa captcha trong thân script nội tuyến không phải challenge (FPT Shop, Next.js)."""

import time

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.challenge import detect_challenge, is_blocking_error_response
from app.scrapers.http.types import FetchResponse

URL = "https://shop.example/c/laptop"
# Rút gọn từ trang danh mục FPT Shop: khóa reCAPTCHA nằm trong biến môi trường của Next.js.
NEXT_ENV = (
    '<script>window["__ENV"] = {"NEXT_PUBLIC_GA":"UA-1","NEXT_PUBLIC_CAPTCHA_KEY":"6Lf-key",'
    '"NEXT_PUBLIC_API":"https://papi.shop.example/"}</script>'
)
PRODUCTS = "<main><a href='/p/1'>Laptop Acer 19.490.000đ</a></main>"


def _resp(text: str, status: int = 200, headers: dict[str, str] | None = None) -> FetchResponse:
    return FetchResponse(url=URL, final_url=URL, status=status, text=text, headers=headers or {})


def test_marker_only_in_inline_script_body_is_not_a_challenge() -> None:
    page = f"<html><head>{NEXT_ENV}</head><body>{PRODUCTS}</body></html>"
    assert detect_challenge(_resp(page), SiteKey.fptshop) is None


def test_marker_in_every_inline_script_of_a_large_page_is_ignored() -> None:
    scripts = "".join(f"<script>var k{i} = 'captcha';</script>" for i in range(50))
    assert detect_challenge(_resp(f"<body>{scripts}{PRODUCTS}</body>"), SiteKey.fptshop) is None


@pytest.mark.parametrize(
    "html",
    [
        "<div class='g-recaptcha' data-sitekey='k'></div>",
        "<iframe src='https://newassets.hcaptcha.com/captcha/v1/x'></iframe>",
        "<script src='https://www.google.com/recaptcha/api.js' async></script>",
        "<script async src='https://x.example/captcha.js'>var a = 1;</script>",
        "<form action='/captcha' method='post'><input name='answer'></form>",
        "<p>Please verify you are human</p>",
        "<title>Captcha</title>",
    ],
)
def test_marker_in_markup_or_script_src_is_still_a_challenge(html: str) -> None:
    challenge = detect_challenge(_resp(f"<body>{NEXT_ENV}{html}</body>"), SiteKey.fptshop)
    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha


def test_visible_marker_next_to_inline_script_is_still_a_challenge() -> None:
    page = f"<body><script>var a = 1;</script><p>Verify you are human</p>{NEXT_ENV}</body>"
    assert detect_challenge(_resp(page), SiteKey.fptshop) is not None


def test_uppercase_script_tag_and_attributes_are_handled() -> None:
    page = f"<BODY><SCRIPT TYPE='text/javascript'>captcha</SCRIPT>{PRODUCTS}</BODY>"
    assert detect_challenge(_resp(page), SiteKey.fptshop) is None


def test_unclosed_script_keeps_the_marker_visible() -> None:
    """Không đóng được thẻ thì không đoán vùng cần bỏ: giữ hành vi cũ (báo challenge)."""
    assert detect_challenge(_resp("<body><script>var k = 'g-recaptcha';"), SiteKey.fptshop) is not None


def test_marker_in_json_ld_script_is_ignored_too() -> None:
    page = '<script type="application/ld+json">{"name":"Captcha mouse"}</script>' + PRODUCTS
    assert detect_challenge(_resp(page), SiteKey.fptshop) is None


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_with_marker_only_in_inline_script_is_a_plain_server_error(status: int) -> None:
    assert is_blocking_error_response(status, {}, f"<html>{NEXT_ENV}Lỗi máy chủ</html>") is False
    assert detect_challenge(_resp(f"<html>{NEXT_ENV}Lỗi</html>", status), SiteKey.fptshop) is None


def test_5xx_with_visible_marker_is_still_a_blocking_response() -> None:
    assert is_blocking_error_response(503, {}, f"<html>{NEXT_ENV}<div id='captcha'></div>") is True


def test_cloudflare_interstitial_inside_script_still_counts() -> None:
    body = "<html><script>var chl_page = 1;</script></html>"
    assert is_blocking_error_response(503, {"server": "cloudflare"}, body) is True


def test_many_unclosed_script_tags_are_scanned_in_linear_time() -> None:
    # Regex lười chạy bậc hai trên đầu vào này (4000 thẻ ~0,5 s, 5 MB ~ hàng giờ).
    page = "<script>" * 200_000 + "tail"
    started = time.perf_counter()
    assert detect_challenge(_resp(page), SiteKey.fptshop) is None
    assert time.perf_counter() - started < 2.0


def test_captcha_marker_after_an_unclosed_script_is_not_hidden() -> None:
    page = "<script>var a = 1;</script><div id='captcha'></div><script>unclosed captcha"
    challenge = detect_challenge(_resp(page), SiteKey.fptshop)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


def test_script_lookalike_tags_are_not_treated_as_scripts() -> None:
    page = "<scripts>hidden g-recaptcha</scripts><p>ok</p></script>"
    challenge = detect_challenge(_resp(page), SiteKey.fptshop)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha
