"""QA M3: biên của nhận diện 5xx challenge (challenge.py) và nhánh retry của Fetcher.

Bổ sung cho test_fetcher_challenge_5xx.py: tên header lẫn hoa/thường, thân không phải UTF-8, thân
rất lớn, thứ tự retry, 4xx/403/429 không bị ảnh hưởng, `detect_challenge` không lộ đáp án captcha.
"""

import asyncio
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.enums import Category, ChallengeKind, SiteKey
from app.scrapers.challenge import detect_challenge, is_blocking_error_response
from app.scrapers.http.errors import (
    FetchFailed,
    HttpStatusError,
    RobotsDisallowed,
    RobotsUnavailable,
)
from app.scrapers.http.factory import site_delays
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.gearvn import GearVNScraper

SHOP = "https://shop.example"
PAGE = f"{SHOP}/p"
CLOUDFLARE_BODY = "<title>Just a moment...</title><script src='/chl_page/v1'></script>"


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
        router.get(f"{SHOP}/robots.txt").respond(404)
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


def fetched(status: int, text: str = "", headers: dict[str, str] | None = None) -> FetchResponse:
    return FetchResponse(url=PAGE, final_url=PAGE, status=status, text=text, headers=headers or {})


# --- Fetcher: nhận diện không phụ thuộc cách viết ----------------------------------------------


@pytest.mark.parametrize(
    ("headers", "text"),
    [
        pytest.param({"CF-MITIGATED": "CHALLENGE"}, "", id="upper-case-header-and-value"),
        pytest.param({"Cf-Mitigated": "Challenge"}, "x", id="title-case-header"),
        pytest.param({"SERVER": "CloudFlare"}, "JUST A MOMENT...", id="mixed-case-server"),
        pytest.param({"server": "cloudflare"}, "Attention Required! | Cloudflare", id="attention"),
        pytest.param({}, "<DIV ID='CAPTCHA'></DIV>", id="upper-case-marker"),
        pytest.param(
            {}, unicodedata.normalize("NFD", "Xác minh bạn không phải robot"), id="nfd-vietnamese"
        ),
    ],
)
async def test_challenge_5xx_is_returned_without_retry_whatever_the_letter_case_or_unicode_form(
    http: respx.MockRouter, fake_time: FakeTime, headers: dict[str, str], text: str
) -> None:
    page = http.get(PAGE).respond(503, headers=headers, text=text)

    response = await make_fetcher(fake_time).get(PAGE)

    assert (response.status, page.call_count, fake_time.sleeps) == (503, 1, [])


async def test_non_utf8_body_with_an_ascii_marker_is_still_a_challenge(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(503, content=b"\xff\xfe\x80 g-recaptcha \xfa\xfb")

    response = await make_fetcher(fake_time).get(PAGE)

    assert (response.status, page.call_count) == (503, 1)
    assert detect_challenge(response, SiteKey.gearvn) is not None


async def test_non_utf8_body_without_a_marker_is_retried_and_fails_normally(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(502, content=b"\xff\xfe\x80\xfa\xfb")

    with pytest.raises(FetchFailed, match="HTTP 502 after 1 retries"):
        await make_fetcher(fake_time, scraper_max_retries=1).get(PAGE)

    assert (page.call_count, fake_time.sleeps) == (2, [5.0])


async def test_multi_megabyte_503_body_is_scanned_for_the_marker(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    big = "a" * 3_000_000
    page = http.get(PAGE).respond(503, text=big + " hcaptcha")

    response = await make_fetcher(fake_time).get(PAGE)

    assert (response.status, page.call_count, fake_time.sleeps) == (503, 1, [])


async def test_multi_megabyte_503_body_without_a_marker_is_retried(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(503, text="a" * 3_000_000)

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time, scraper_max_retries=1).get(PAGE)

    assert page.call_count == 2


async def test_plain_503_followed_by_a_challenge_503_returns_the_challenge_after_one_backoff(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(503, headers={"cf-mitigated": "challenge"}, text=CLOUDFLARE_BODY),
            httpx.Response(200, text="never reached"),
        ]
    )

    response = await make_fetcher(fake_time).get(PAGE)

    assert (response.status, page.call_count, fake_time.sleeps) == (503, 2, [5.0])
    challenge = detect_challenge(response, SiteKey.gearvn)
    assert challenge is not None and challenge.kind is ChallengeKind.captcha


async def test_challenge_503_then_ok_is_never_retried_into_success(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    """Gửi lại trang challenge để 'may mắn' qua được là né chặn: chỉ một request."""
    page = http.get(PAGE).mock(
        side_effect=[
            httpx.Response(503, headers={"cf-mitigated": "challenge"}),
            httpx.Response(200, text="ok"),
        ]
    )

    response = await make_fetcher(fake_time).get(PAGE)

    assert (response.status, page.call_count) == (503, 1)


# --- Fetcher: các mã khác không đổi ------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 410, 451, 499])
async def test_4xx_with_challenge_signals_is_still_a_plain_status_error_without_retry(
    http: respx.MockRouter, fake_time: FakeTime, status: int
) -> None:
    page = http.get(PAGE).respond(status, headers={"cf-mitigated": "challenge"}, text="captcha")

    with pytest.raises(HttpStatusError) as caught:
        await make_fetcher(fake_time).get(PAGE)

    assert (caught.value.status, page.call_count, fake_time.sleeps) == (status, 1, [])


async def test_403_with_challenge_signals_is_returned_once_and_reported_as_http_403(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(403, headers={"cf-mitigated": "challenge"}, text="captcha")

    response = await make_fetcher(fake_time).get(PAGE)
    challenge = detect_challenge(response, SiteKey.gearvn)

    assert (response.status, page.call_count, fake_time.sleeps) == (403, 1, [])
    assert challenge is not None and challenge.kind is ChallengeKind.http_403


async def test_429_with_challenge_signals_waits_once_then_is_reported_as_http_429(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(429, headers={"cf-mitigated": "challenge"}, text="captcha")

    response = await make_fetcher(fake_time).get(PAGE)
    challenge = detect_challenge(response, SiteKey.gearvn)

    assert (response.status, page.call_count, fake_time.sleeps) == (429, 2, [60.0])
    assert challenge is not None and challenge.kind is ChallengeKind.http_429


async def test_ordinary_5xx_exhausts_its_retries_with_doubling_backoff_then_fails(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    page = http.get(PAGE).respond(502, text="Bad gateway")

    with pytest.raises(FetchFailed, match="HTTP 502 after 3 retries"):
        await make_fetcher(fake_time).get(PAGE)

    assert (page.call_count, fake_time.sleeps) == (4, [5.0, 10.0, 20.0])


async def test_robots_txt_served_as_a_challenge_503_blocks_the_page_request(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(503, headers={"cf-mitigated": "challenge"})
    page = http.get(PAGE).respond(200, text="ok")

    with pytest.raises(RobotsUnavailable):
        await make_fetcher(fake_time).get(PAGE)

    assert page.call_count == 0


# --- Hàm nhận diện -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, False), (302, False), (400, False), (499, False), (500, True), (503, True), (599, True)],
)
def test_status_boundary_for_blocking_error_responses(status: int, expected: bool) -> None:
    assert is_blocking_error_response(status, {"cf-mitigated": "challenge"}, "") is expected


def test_duplicated_cf_mitigated_header_values_are_not_mistaken_for_a_challenge() -> None:
    assert is_blocking_error_response(503, {"cf-mitigated": "challenge, challenge"}, "") is False


# --- detect_challenge không bao giờ lộ hay giải đáp án ------------------------------------------

CAPTCHA_PAGE = (
    '<div class="captcha"><img src="/captcha.png"><p>Tính 2 + 3 = ?</p>'
    '<input name="answer" value="5"><input type="hidden" name="token" value="abc123"></div>'
)


@pytest.mark.parametrize("status", [200, 503])
def test_real_site_captcha_challenge_carries_no_prompt_image_token_or_answer(status: int) -> None:
    challenge = detect_challenge(fetched(status, CAPTCHA_PAGE), SiteKey.gearvn)

    assert challenge is not None and challenge.kind is ChallengeKind.captcha
    dumped = challenge.model_dump(mode="json")
    assert (dumped["prompt"], dumped["image_url"], dumped["token"]) == (None, None, None)
    assert "5" not in {value for value in dumped.values() if isinstance(value, str)}
    assert "abc123" not in repr(dumped)


@pytest.mark.parametrize(
    ("status", "headers", "text", "kind"),
    [
        (429, {"cf-mitigated": "challenge"}, "captcha", ChallengeKind.http_429),
        (403, {"cf-mitigated": "challenge"}, "captcha", ChallengeKind.http_403),
        (503, {}, "<div id='captcha'></div>", ChallengeKind.captcha),
        (200, {}, "g-recaptcha", ChallengeKind.captcha),
    ],
)
def test_detect_challenge_prefers_the_status_code_over_the_body(
    status: int, headers: dict[str, str], text: str, kind: ChallengeKind
) -> None:
    challenge = detect_challenge(fetched(status, text, headers), SiteKey.gearvn)
    assert challenge is not None and challenge.kind is kind


@pytest.mark.parametrize("status", [200, 404, 500, 503])
def test_detect_challenge_ignores_pages_without_any_signal(status: int) -> None:
    assert (
        detect_challenge(fetched(status, "<html>Chuột gaming 1.990.000đ</html>"), SiteKey.gearvn)
        is None
    )


# --- GearVN qua Fetcher thật: quy tắc thu thập (robots.txt, độ trễ, User-Agent) -----------------

GEARVN = "https://gearvn.com"
GEARVN_LIST = f"{GEARVN}/collections/chuot-may-tinh"
GEARVN_ROBOTS = chr(10).join(
    [
        "User-Agent: *",
        "Allow: /",
        "Disallow: /gio-hang",
        "Disallow: /thanh-toan",
        "Disallow: /design-system",
        "Disallow: /tai-khoan",
        "Disallow: /api/",
    ]
)
PROJECT_UA = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: qa@example.com)"
GEARVN_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"


def gearvn_fetcher(fake: FakeTime) -> Fetcher:
    settings = Settings(
        scraper_offline_only=False, scraper_min_delay_seconds=0, scraper_user_agent=PROJECT_UA
    )
    return Fetcher(
        settings, site_delays=site_delays(), clock=fake.clock, sleep=fake.sleep, jitter=lambda: 0.0
    )


def test_gearvn_delay_comes_from_the_site_config_even_when_the_env_delay_is_zero() -> None:
    assert site_delays()["gearvn.com"] == 5.0


def test_crawling_two_gearvn_pages_waits_between_requests_and_sends_the_project_user_agent(
    fake_time: FakeTime,
) -> None:
    page_one = (GEARVN_FIXTURES / "listing_mouse_p1.html").read_text(encoding="utf-8")
    page_two = (GEARVN_FIXTURES / "listing_mouse_p8.html").read_text(encoding="utf-8")

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=GEARVN_ROBOTS)
        return httpx.Response(200, text=page_two if request.url.params.get("page") else page_one)

    async def run() -> tuple[list[int], list[httpx.Request]]:
        with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
            router.route(host="gearvn.com").mock(side_effect=serve)
            scraper = GearVNScraper(gearvn_fetcher(fake_time))
            pages = [p async for p in scraper.crawl_category(Category.mouse, max_pages=2)]
            return [len(p.items) for p in pages], [call.request for call in router.calls]

    sizes, requests = asyncio.run(run())

    assert sizes == [20, 19]
    assert [str(r.url) for r in requests] == [
        f"{GEARVN}/robots.txt",
        GEARVN_LIST,
        f"{GEARVN_LIST}?page=2",
    ]
    assert fake_time.sleeps == [5.0, 5.0]  # robots.txt -> trang 1 -> trang 2
    assert {r.headers["user-agent"] for r in requests} == {PROJECT_UA}
    assert all("cookie" not in r.headers and "referer" not in r.headers for r in requests)


@pytest.mark.parametrize("path", ["/api/products", "/api/", "/gio-hang", "/thanh-toan/x"])
async def test_fetcher_refuses_gearvn_paths_that_robots_txt_disallows_without_sending_them(
    fake_time: FakeTime, path: str
) -> None:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.get(f"{GEARVN}/robots.txt").respond(200, text=GEARVN_ROBOTS)
        blocked = router.get(f"{GEARVN}{path}").respond(200, text="secret")

        with pytest.raises(RobotsDisallowed):
            await gearvn_fetcher(fake_time).get(f"{GEARVN}{path}")

        assert blocked.call_count == 0
