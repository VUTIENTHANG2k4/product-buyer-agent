"""AnPhatScraper (app/scrapers/sites/anphat.py) trên fixture đã lưu ở T4.3, không gọi mạng."""

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.anphat import AnPhatScraper
from tests.fakes import FakeFetcher

BASE = "https://www.anphatpc.com.vn"
# Form đăng ký nằm trong mọi trang của An Phát (kể cả trang sản phẩm bình thường).
REGISTER_FORM = (
    '<form><input type="text" name="register_captcha" onkeyup="check_user_captcha(this.value)"/>'
    '<img src="/includes/captcha/captcha.php?v=" id="captchaimg"/>'
    "<a onclick=\"document.getElementById('captchaimg').src='/includes/captcha/captcha.php?'\">"
    "Đổi ảnh</a></form>"
)


def response(text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(url=f"{BASE}/x", final_url=f"{BASE}/x", status=status, text=text)


@pytest.fixture
def scraper() -> AnPhatScraper:
    return AnPhatScraper(FakeFetcher({}))


# --- Bộ phát hiện challenge --------------------------------------------------------------------


def test_registration_form_captcha_on_every_page_is_not_a_challenge(
    scraper: AnPhatScraper,
) -> None:
    page = f"<html><body><h1>Chuột Logitech</h1>{REGISTER_FORM}</body></html>"
    assert scraper.detect_challenge(response(page)) is None


def test_empty_listing_page_with_the_registration_form_is_not_a_challenge(
    scraper: AnPhatScraper,
) -> None:
    assert scraper.detect_challenge(response(f"<body>{REGISTER_FORM}</body>")) is None


@pytest.mark.parametrize(
    "markup",
    [
        '<div id="captcha">AB3XZ</div>',
        '<div class="g-recaptcha" data-sitekey="k"></div>',
        '<iframe src="https://newassets.hcaptcha.com/captcha/v1/x"></iframe>',
        "<p>Please verify you are human</p>",
        '<form action="/captcha" method="post"></form>',
        '<img src="/includes/captcha/other.php">',
    ],
)
def test_a_real_captcha_next_to_the_registration_form_is_still_a_challenge(
    scraper: AnPhatScraper, markup: str
) -> None:
    challenge = scraper.detect_challenge(response(f"<body>{REGISTER_FORM}{markup}</body>"))
    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha
    assert challenge.site is SiteKey.anphat


@pytest.mark.parametrize(
    ("status", "kind"), [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)]
)
def test_blocking_status_is_a_challenge_even_with_the_registration_form(
    scraper: AnPhatScraper, status: int, kind: ChallengeKind
) -> None:
    challenge = scraper.detect_challenge(response(REGISTER_FORM, status))
    assert challenge is not None and challenge.kind is kind
