"""ChallengeDetector (app/scrapers/challenge.py): docs/06 §4, không gọi mạng."""

import unicodedata

import pytest

from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.challenge import ChallengeDetected, detect_challenge, soft_block_challenge
from app.scrapers.http.types import FetchResponse

URL = "https://shop.example/c/laptop"


def _resp(status: int = 200, text: str = "<html><body>Laptop</body></html>") -> FetchResponse:
    return FetchResponse(url=URL, final_url=URL, status=status, text=text)


@pytest.mark.parametrize(
    ("status", "kind"),
    [(403, ChallengeKind.http_403), (429, ChallengeKind.http_429)],
)
def test_blocking_status_codes_are_challenges(status: int, kind: ChallengeKind) -> None:
    challenge = detect_challenge(_resp(status), SiteKey.gearvn)
    assert challenge is not None
    assert challenge.kind is kind
    assert challenge.site is SiteKey.gearvn
    assert str(challenge.url) == URL


@pytest.mark.parametrize("status", [200, 201, 301, 404, 410, 500, 502, 503])
def test_other_statuses_with_plain_body_are_not_challenges(status: int) -> None:
    assert detect_challenge(_resp(status), SiteKey.gearvn) is None


@pytest.mark.parametrize(
    "marker",
    [
        "captcha",
        "cf-challenge",
        "g-recaptcha",
        "hcaptcha",
        "Verify you are human",
        "xác minh bạn không phải robot",
    ],
)
@pytest.mark.parametrize("transform", [str, str.upper, str.title])
def test_captcha_markers_match_case_insensitively(marker: str, transform: type[str]) -> None:
    html = f"<html><body><div class='x'>{transform(marker)}</div></body></html>"
    challenge = detect_challenge(_resp(200, html), SiteKey.mockshop)
    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKD"])
def test_vietnamese_marker_matches_in_any_unicode_form(form: str) -> None:
    text = unicodedata.normalize(form, "Xác minh bạn không phải ROBOT để tiếp tục")
    challenge = detect_challenge(_resp(200, text), SiteKey.viettelstore)
    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha


def test_marker_inside_script_or_attribute_is_detected() -> None:
    html = '<script src="https://www.google.com/recaptcha/api.js" class="g-recaptcha"></script>'
    assert detect_challenge(_resp(200, html), SiteKey.gearvn) is not None


def test_status_takes_precedence_over_body_markers() -> None:
    challenge = detect_challenge(_resp(403, "<div id='captcha'>AB3XZ</div>"), SiteKey.mockshop)
    assert challenge is not None
    assert challenge.kind is ChallengeKind.http_403


def test_empty_body_is_not_a_challenge() -> None:
    assert detect_challenge(_resp(200, ""), SiteKey.gearvn) is None


def test_challenge_uses_final_url_after_redirect() -> None:
    resp = FetchResponse(
        url=URL, final_url="https://shop.example/verify", status=200, text="hCaptcha"
    )
    challenge = detect_challenge(resp, SiteKey.gearvn)
    assert challenge is not None
    assert str(challenge.url) == "https://shop.example/verify"


def test_soft_block_challenge_has_kind_site_and_url() -> None:
    challenge = soft_block_challenge(SiteKey.nguyenkim, URL)
    assert challenge.kind is ChallengeKind.soft_block
    assert challenge.site is SiteKey.nguyenkim
    assert str(challenge.url) == URL


def test_challenge_detected_carries_the_challenge() -> None:
    challenge = soft_block_challenge(SiteKey.gearvn, URL)
    error = ChallengeDetected(challenge)
    assert error.challenge is challenge
    assert "soft_block" in str(error)
