"""T2.7(c): 5xx của trang challenge (Cloudflare…) là chặn, không phải lỗi máy chủ để retry.

Fetcher trả ngay phản hồi (không gửi lại request) và `detect_challenge` báo `captcha`; pipeline đã
có sẵn quy tắc challenge của trang thật → `BLOCKED` + nghỉ 24 giờ (test ở test_pipeline.py). 5xx
thường vẫn retry rồi `FetchFailed`.
"""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.enums import Category, ChallengeKind, SiteKey
from app.scrapers.challenge import ChallengeDetected, detect_challenge, is_blocking_error_response
from app.scrapers.http.errors import FetchFailed
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.gearvn import GearVNScraper

SHOP = "https://shop.example"
CLOUDFLARE_PAGE = (
    "<html><head><title>Just a moment...</title></head>"
    '<body><script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body>'
    "</html>"
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


def make_fetcher(fake: FakeTime, **overrides: Any) -> Fetcher:
    values: dict[str, Any] = {
        "scraper_offline_only": False,
        "scraper_min_delay_seconds": 0,
        "scraper_max_retries": 3,
    }
    return Fetcher(
        Settings(**{**values, **overrides}), clock=fake.clock, sleep=fake.sleep, jitter=lambda: 0.0
    )


# --- Fetcher ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "headers", "text"),
    [
        pytest.param(503, {"cf-mitigated": "challenge"}, "", id="cf-mitigated-header"),
        pytest.param(503, {"CF-Mitigated": "Challenge"}, "<p>x</p>", id="header-case-insensitive"),
        pytest.param(
            503, {"server": "cloudflare"}, CLOUDFLARE_PAGE, id="cloudflare-interstitial-page"
        ),
        pytest.param(500, {}, "<div class='g-recaptcha'></div>", id="captcha-marker-in-500"),
        pytest.param(502, {}, "<h1>Verify you are human</h1>", id="verify-human-in-502"),
    ],
)
async def test_blocking_5xx_is_returned_once_without_retry_or_backoff(
    http: respx.MockRouter, fake_time: FakeTime, status: int, headers: dict[str, str], text: str
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(404)
    page = http.get(f"{SHOP}/p").respond(status, headers=headers, text=text)

    response = await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert response.status == status
    assert page.call_count == 1
    assert fake_time.sleeps == []  # không backoff: gửi lại trang challenge chỉ thêm tải


async def test_blocking_5xx_is_reported_as_challenge_by_the_detector(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(404)
    http.get(f"{SHOP}/p").respond(503, headers={"cf-mitigated": "challenge"})

    response = await make_fetcher(fake_time).get(f"{SHOP}/p")
    challenge = detect_challenge(response, SiteKey.gearvn)

    assert challenge is not None
    assert (challenge.kind, challenge.site, str(challenge.url)) == (
        ChallengeKind.captcha,
        SiteKey.gearvn,
        f"{SHOP}/p",
    )


@pytest.mark.parametrize(
    ("headers", "text"),
    [
        pytest.param({}, "", id="empty-503"),
        pytest.param({"server": "nginx"}, "<h1>Service Unavailable</h1>", id="nginx-503"),
        pytest.param(
            {"server": "cloudflare"}, "<h1>Bad gateway</h1>", id="cloudflare-origin-error"
        ),
        pytest.param({"cf-mitigated": "block"}, "", id="other-cf-mitigated-value"),
        pytest.param(
            {"server": "cloudflare"},
            '<h1>Bad gateway</h1><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
            "</script>",
            id="cloudflare-beacon-script-on-an-origin-error",
        ),
    ],
)
async def test_ordinary_5xx_is_still_retried_then_fails(
    http: respx.MockRouter, fake_time: FakeTime, headers: dict[str, str], text: str
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(404)
    page = http.get(f"{SHOP}/p").respond(503, headers=headers, text=text)

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time, scraper_max_retries=2).get(f"{SHOP}/p")

    assert page.call_count == 3
    assert fake_time.sleeps == [5.0, 10.0]


async def test_server_error_that_recovers_is_not_treated_as_a_block(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(404)
    page = http.get(f"{SHOP}/p").mock(
        side_effect=[httpx.Response(503, text="busy"), httpx.Response(200, text="ok")]
    )

    response = await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert (response.status, response.text, page.call_count) == (200, "ok", 2)


# --- Hàm nhận diện ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "headers", "text", "expected"),
    [
        (503, {"cf-mitigated": "challenge"}, "", True),
        (503, {"Server": "cloudflare"}, "Attention Required! | Cloudflare", True),
        (503, {"server": "Cloudflare"}, "<title>JUST A MOMENT...</title>", True),
        (500, {}, "xác minh bạn không phải robot", True),
        (503, {"server": "nginx"}, "Just a moment", False),  # không phải Cloudflare
        (502, {"server": "cloudflare"}, "/cdn-cgi/challenge-platform/scripts/jsd/main.js", False),
        (
            503,
            {"server": "cloudflare"},
            "/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1",
            True,
        ),
        (503, {}, "bảo trì hệ thống", False),
        (404, {"cf-mitigated": "challenge"}, "", False),  # 4xx do Fetcher/detector xử lý riêng
        (200, {"cf-mitigated": "challenge"}, "", False),
    ],
)
def test_is_blocking_error_response(
    status: int, headers: dict[str, str], text: str, expected: bool
) -> None:
    assert is_blocking_error_response(status, headers, text) is expected


def test_detector_flags_blocking_5xx_even_when_the_body_has_no_marker() -> None:
    response = FetchResponse(
        url=f"{SHOP}/p",
        final_url=f"{SHOP}/p",
        status=503,
        text="",
        headers={"cf-mitigated": "challenge"},
    )
    challenge = detect_challenge(response, SiteKey.gearvn)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


def test_detector_does_not_flag_a_plain_503() -> None:
    response = FetchResponse(url=f"{SHOP}/p", final_url=f"{SHOP}/p", status=503, text="busy")
    assert detect_challenge(response, SiteKey.gearvn) is None


# --- Qua scraper ------------------------------------------------------------------------------


async def test_crawl_category_on_a_cloudflare_503_raises_challenge_detected_not_fetch_failed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    category_url = "https://gearvn.com/collections/laptop"
    http.get("https://gearvn.com/robots.txt").respond(404)
    page = http.get(category_url).respond(
        503, headers={"server": "cloudflare", "cf-mitigated": "challenge"}, text=CLOUDFLARE_PAGE
    )
    scraper = GearVNScraper(make_fetcher(fake_time))

    with pytest.raises(ChallengeDetected) as caught:
        _ = [item async for item in scraper.crawl_category(Category.laptop, max_pages=2)]

    assert caught.value.challenge.kind is ChallengeKind.captcha
    assert caught.value.challenge.site is SiteKey.gearvn
    assert page.call_count == 1
