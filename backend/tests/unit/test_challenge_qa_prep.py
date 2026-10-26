"""QA "Chuẩn bị bảo vệ" (T4.8): biên của bộ phát hiện captcha theo thẻ/thuộc tính/`<title>`."""

import time
import unicodedata
from collections.abc import Callable
from typing import Literal

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.challenge import detect_challenge, has_captcha_marker, is_blocking_error_response
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.anphat import AnPhatScraper

PRODUCTS = "<div class='product'><h3>Chuột Mock</h3><span>290.000đ</span></div>"
BASE = "https://www.anphatpc.com.vn"
REGISTER_FORM = (
    '<form><input type="text" name="register_captcha" onkeyup="check_user_captcha(this.value)"/>'
    '<img src="/includes/captcha/captcha.php?v=" id="captchaimg"/></form>'
)


def _resp(text: str, status: int = 200, headers: dict[str, str] | None = None) -> FetchResponse:
    return FetchResponse(
        url=f"{BASE}/x", final_url=f"{BASE}/x", status=status, text=text, headers=headers or {}
    )


# ---- cú pháp thuộc tính -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "markup",
    [
        "<div class=captcha>x</div>",  # không nháy
        "<div class='x captcha'>x</div>",  # nháy đơn
        '<div class = "captcha">x</div>',  # khoảng trắng quanh dấu =
        '<div class\n=\n"captcha">x</div>',  # xuống dòng quanh dấu =
        '<DIV CLASS="CAPTCHA">x</DIV>',  # viết hoa
        "<input name=captcha />",  # tự đóng, có khoảng trắng
        "<input name=captcha/>",  # tự đóng, không khoảng trắng
        '<div class="a"id="captcha">x</div>',  # hai thuộc tính dính nhau
        "<FORM ACTION='/CAPTCHA'>",
        "<script src='/captcha.js'></script>",
        "<noscript><div id=captcha></div></noscript>",
    ],
)
def test_attribute_syntax_variants_all_count_as_markup(markup: str) -> None:
    assert has_captcha_marker(PRODUCTS + markup)


@pytest.mark.parametrize(
    "markup",
    [
        '<div data-id="captcha">x</div>',  # thuộc tính không thuộc danh sách
        '<div aria-label="captcha">x</div>',
        '<div xclass="captcha">x</div>',  # tên thuộc tính chỉ chứa `class` ở đuôi
        '<a title="id=captcha">x</a>',  # `id=captcha` nằm trong giá trị của `title`
        "<a title=id=captcha>x</a>",
        '<a href="/x?class=captcha">x</a>',
        '<img srcset="/captcha.png 1x">',
        "<style>.captcha{display:none}</style>",
        "<!-- <div id=captcha> -->",
        "<!-- <title>captcha</title> -->",
        "&lt;div id=&quot;captcha&quot;&gt;",  # entity: là văn bản, không phải thẻ
        "<textarea>&lt;div id=captcha&gt;</textarea>",
        "<p>a <1 captcha</p>",
        '<title data-x="captcha">Cửa hàng</title>',  # thuộc tính của thẻ title, không phải nội dung
    ],
)
def test_the_word_outside_the_listed_places_is_not_a_challenge(markup: str) -> None:
    assert not has_captcha_marker(PRODUCTS + markup)


# ---- <title> ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "markup",
    [
        "<title>Cửa hàng</title><svg><title>captcha</title></svg>",  # <title> thứ hai
        "<title><title>captcha</title></title>",  # lồng nhau
        "<title>Xác thực CAPTCHA",  # không đóng
        "<TITLE>Captcha</TITLE>",
    ],
)
def test_title_variants_count(markup: str) -> None:
    assert has_captcha_marker(markup)


def test_a_clean_title_does_not_hide_a_marker_after_it() -> None:
    assert has_captcha_marker("<title>Cửa hàng</title><div id='captcha'></div>")


# ---- tiếng Việt, Unicode ----------------------------------------------------------------------
@pytest.mark.parametrize("form", ["NFC", "NFD"])
@pytest.mark.parametrize("casing", [str, str.upper, str.title])
def test_vietnamese_marker_ignores_case_and_unicode_form(
    form: Literal["NFC", "NFD"], casing: Callable[[str], str]
) -> None:
    text = "Xác minh bạn không phải robot"
    assert has_captcha_marker(unicodedata.normalize(form, casing(text)))


def test_bug_prep_4_marker_phrase_with_a_no_break_space_is_still_a_challenge() -> None:
    assert has_captcha_marker("<p>Verify you are human</p>")


# ---- `>` trong giá trị thuộc tính -------------------------------------------------------------
def test_bug_prep_3_greater_than_inside_an_attribute_value_does_not_hide_later_attributes() -> None:
    assert has_captcha_marker('<div data-tip="a > b" class="captcha">x</div>')


def test_greater_than_inside_a_value_still_finds_a_marker_before_it() -> None:
    assert has_captcha_marker('<div class="captcha" data-tip="a > b">x</div>')


# ---- tuyến tính -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "unit",
    ["<p>captcha</p>", "<title>x</title>", "<script>", "<!--", "<a ", "<", "<a b=c "],
)
def test_five_megabytes_of_repeated_units_stay_fast(unit: str) -> None:
    page = unit * (5_000_000 // len(unit))
    started = time.perf_counter()
    has_captcha_marker(page)
    assert time.perf_counter() - started < 15.0


@pytest.mark.parametrize(
    "tag",
    [
        "<a " + "a" * 20_000 + ">",  # một từ dài không có dấu =
        '<a x="' + "a" * 20_000 + ">",  # nháy không đóng
    ],
    ids=["long-word-in-tag", "unterminated-quote"],
)
def test_bug_prep_1_one_long_tag_is_scanned_in_linear_time(tag: str) -> None:
    started = time.perf_counter()
    has_captcha_marker(tag)
    assert time.perf_counter() - started < 0.5


# ---- detect_challenge / is_blocking_error_response -------------------------------------------
@pytest.mark.parametrize(
    ("status", "kind"),
    [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)],
)
def test_status_wins_over_markup(status: int, kind: ChallengeKind) -> None:
    challenge = detect_challenge(_resp("<div id='captcha'></div>", status), SiteKey.fptshop)
    assert challenge is not None and challenge.kind is kind


@pytest.mark.parametrize("status", [404, 410, 499])
def test_a_4xx_with_captcha_markup_is_still_a_captcha_but_never_a_cdn_5xx(status: int) -> None:
    assert is_blocking_error_response(status, {"cf-mitigated": "challenge"}, "x") is False
    challenge = detect_challenge(_resp("<div id='captcha'></div>", status), SiteKey.fptshop)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


@pytest.mark.parametrize("status", [500, 502, 599])
def test_every_5xx_with_markup_is_a_blocking_error(status: int) -> None:
    assert is_blocking_error_response(status, {}, "<div class='g-recaptcha'></div>") is True


def test_cf_mitigated_header_is_case_insensitive_in_name_and_value() -> None:
    assert is_blocking_error_response(503, {"CF-Mitigated": "Challenge"}, "") is True
    assert is_blocking_error_response(503, {"cf-mitigated": "other"}, "") is False


def test_a_plain_5xx_error_page_is_not_a_challenge() -> None:
    assert detect_challenge(_resp("<h1>Internal Server Error</h1>", 500), SiteKey.gearvn) is None


def test_detect_challenge_returns_none_for_an_empty_body() -> None:
    assert detect_challenge(_resp(""), SiteKey.gearvn) is None


# ---- An Phát: form đăng ký --------------------------------------------------------------------
@pytest.fixture
def anphat() -> AnPhatScraper:
    class Dummy:
        async def get(self, url: str) -> FetchResponse:  # pragma: no cover
            raise AssertionError(url)

    return AnPhatScraper(Dummy())


def test_anphat_register_form_alone_is_not_a_challenge(anphat: AnPhatScraper) -> None:
    assert anphat.detect_challenge(_resp(f"<body>{PRODUCTS}{REGISTER_FORM}</body>")) is None


@pytest.mark.parametrize(
    "extra",
    [
        "<title>Captcha</title>",
        '<div class="g-recaptcha"></div>',
        '<div id="captcha">AB3XZ</div>',
        "<p>Xác minh bạn không phải robot</p>",
        '<iframe src="https://hcaptcha.com/x"></iframe>',
    ],
)
def test_anphat_register_form_does_not_hide_a_real_challenge(
    anphat: AnPhatScraper, extra: str
) -> None:
    challenge = anphat.detect_challenge(_resp(f"<body>{REGISTER_FORM}{extra}</body>"))
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


def test_anphat_register_form_in_a_real_403_is_still_http_403(anphat: AnPhatScraper) -> None:
    challenge = anphat.detect_challenge(_resp(REGISTER_FORM, 403))
    assert challenge is not None and challenge.kind is ChallengeKind.http_403


def test_anphat_a_5xx_with_the_register_form_is_a_blocking_error(anphat: AnPhatScraper) -> None:
    challenge = anphat.detect_challenge(_resp(REGISTER_FORM, 503))
    assert challenge is not None and challenge.kind is ChallengeKind.captcha
