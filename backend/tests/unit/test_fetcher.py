"""Fetcher (app/scrapers/http/fetcher.py): HTTP giả bằng respx, đồng hồ giả, không gọi mạng."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.scrapers.http.errors import (
    FetchFailed,
    FormNotAllowed,
    HttpStatusError,
    OfflineModeError,
    RedirectError,
    RobotsDisallowed,
    RobotsUnavailable,
)
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.types import PageFetcher

SHOP = "https://shop.example"
OTHER = "https://other.example"
MOCK = "http://localhost:8100"
UA = "ProductBuyerAgent-test/0.1"


class FakeTime:
    """Đồng hồ giả: `sleep` chỉ cộng thời gian, không ngủ thật."""

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


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "scraper_offline_only": False,
        "scraper_min_delay_seconds": 5,
        "scraper_max_retries": 3,
        "mock_shop_url": MOCK,
        "mock_shop_delay_seconds": 1,
    }
    return Settings(**{**values, **overrides})


def make_fetcher(fake: FakeTime, **kwargs: Any) -> Fetcher:
    settings = kwargs.pop("settings", None) or make_settings()
    return Fetcher(settings, clock=fake.clock, sleep=fake.sleep, jitter=lambda: 0.0, **kwargs)


def robots(http: respx.MockRouter, origin: str = SHOP, text: str = "", status: int = 200) -> Any:
    return http.get(f"{origin}/robots.txt").respond(status, text=text)


def recorder(fake: FakeTime, log: list[tuple[str, float]], status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append((request.url.path, fake.now))
        return httpx.Response(status, text=f"<html>{request.url.path}</html>")

    return handler


# --- Hợp đồng PageFetcher ---------------------------------------------------------------------


async def test_get_returns_a_fetch_response_with_all_fields(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/c/laptop").respond(200, text="<p>Xin chào</p>", headers={"X-Test": "1"})
    fetcher: PageFetcher = make_fetcher(fake_time)

    response = await fetcher.get(f"{SHOP}/c/laptop")

    assert (response.url, response.final_url, response.status) == (f"{SHOP}/c/laptop",) * 2 + (200,)
    assert response.text == "<p>Xin chào</p>"
    assert response.headers["x-test"] == "1"
    assert response.from_cache is False


async def test_sends_honest_user_agent_and_language_and_no_browser_headers(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    page = http.get(f"{SHOP}/p").respond(200, text="ok")
    await make_fetcher(fake_time).get(f"{SHOP}/p")

    sent = page.calls.last.request.headers
    assert sent["user-agent"] == make_settings().scraper_user_agent
    assert sent["accept-language"] == "vi-VN,vi;q=0.9"
    assert "referer" not in sent and "cookie" not in sent
    # robots.txt cũng được tải với cùng User-Agent
    assert http.calls[0].request.headers["user-agent"] == sent["user-agent"]


async def test_non_http_urls_are_rejected_without_a_request(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    for bad in ("ftp://shop.example/x", "/relative", "shop.example/x"):
        with pytest.raises(RedirectError):
            await make_fetcher(fake_time).get(bad)
    assert http.calls.call_count == 0


# --- robots.txt -------------------------------------------------------------------------------


async def test_url_blocked_by_robots_is_never_requested(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, text="User-agent: *\nDisallow: /private")
    page = http.get(f"{SHOP}/private/x").respond(200, text="secret")

    with pytest.raises(RobotsDisallowed) as error:
        await make_fetcher(fake_time).get(f"{SHOP}/private/x")

    assert error.value.url == f"{SHOP}/private/x"
    assert page.call_count == 0


async def test_urls_with_a_query_blocked_by_a_wildcard_rule_are_not_requested(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, text="User-agent: *\nDisallow: /*?filter=")
    page = http.get(f"{SHOP}/laptop", params={"filter": "gaming"}).respond(200)

    with pytest.raises(RobotsDisallowed):
        await make_fetcher(fake_time).get(f"{SHOP}/laptop?filter=gaming")

    assert page.call_count == 0


async def test_robots_is_fetched_once_per_day_per_domain(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robot = robots(http)
    http.get(url__regex=rf"{SHOP}/p/\d").respond(200, text="ok")
    fetcher = make_fetcher(fake_time)

    await fetcher.get(f"{SHOP}/p/1")
    await fetcher.get(f"{SHOP}/p/2")
    assert robot.call_count == 1

    fake_time.now += 24 * 3600
    await fetcher.get(f"{SHOP}/p/3")
    assert robot.call_count == 2


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_robots_server_error_means_not_allowed_and_is_retried_on_the_next_call(
    http: respx.MockRouter, fake_time: FakeTime, status: int
) -> None:
    robot = http.get(f"{SHOP}/robots.txt").mock(
        side_effect=[httpx.Response(status), httpx.Response(200, text="")]
    )
    page = http.get(f"{SHOP}/p").respond(200, text="ok")
    fetcher = make_fetcher(fake_time)

    with pytest.raises(RobotsUnavailable):
        await fetcher.get(f"{SHOP}/p")
    assert page.call_count == 0

    assert (await fetcher.get(f"{SHOP}/p")).text == "ok"
    assert robot.call_count == 2


async def test_robots_network_error_means_not_allowed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").mock(side_effect=httpx.ConnectError("down"))
    page = http.get(f"{SHOP}/p").respond(200)

    with pytest.raises(RobotsUnavailable):
        await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert page.call_count == 0


async def test_missing_robots_404_allows_everything(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(200, text="ok")
    assert (await make_fetcher(fake_time).get(f"{SHOP}/p")).status == 200


async def test_robots_403_blocks_the_whole_site(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=403)
    page = http.get(f"{SHOP}/p").respond(200)
    with pytest.raises(RobotsDisallowed):
        await make_fetcher(fake_time).get(f"{SHOP}/p")
    assert page.call_count == 0


async def test_robots_redirect_within_the_domain_is_followed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(301, headers={"Location": f"{SHOP}/real-robots.txt"})
    http.get(f"{SHOP}/real-robots.txt").respond(200, text="User-agent: *\nDisallow: /nope")
    http.get(f"{SHOP}/nope").respond(200)

    with pytest.raises(RobotsDisallowed):
        await make_fetcher(fake_time).get(f"{SHOP}/nope")


async def test_robots_redirect_off_domain_means_unavailable(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(f"{SHOP}/robots.txt").respond(302, headers={"Location": f"{OTHER}/robots.txt"})
    with pytest.raises(RobotsUnavailable):
        await make_fetcher(fake_time).get(f"{SHOP}/p")


# --- Độ trễ -----------------------------------------------------------------------------------


async def test_requests_to_one_domain_are_at_least_the_configured_delay_apart(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    http.get(f"{SHOP}/robots.txt").respond(404)
    http.get(url__regex=rf"{SHOP}/p/\d").mock(side_effect=recorder(fake_time, log))
    fetcher = make_fetcher(fake_time)

    for n in (1, 2, 3):
        await fetcher.get(f"{SHOP}/p/{n}")

    times = [at for _, at in log]
    assert [b - a for a, b in zip(times, times[1:], strict=False)] == [5.0, 5.0]


async def test_robots_download_also_counts_towards_the_delay(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    http.get(f"{SHOP}/robots.txt").mock(side_effect=recorder(fake_time, log, status=404))
    http.get(f"{SHOP}/p").mock(side_effect=recorder(fake_time, log))

    await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert log == [("/robots.txt", 0.0), ("/p", 5.0)]


@pytest.mark.parametrize(
    ("crawl_delay", "site_delay", "env_delay", "expected"),
    [
        (12, 0, 5, 12.0),  # Crawl-delay của robots.txt lớn nhất
        (None, 10, 5, 10.0),  # SiteConfig.min_delay_s (Laptop88)
        (None, 0, 7, 7.0),  # SCRAPER_MIN_DELAY_SECONDS
        (3, 4, 2, 4.0),
    ],
)
async def test_delay_is_the_maximum_of_env_robots_crawl_delay_and_site_config(
    http: respx.MockRouter,
    fake_time: FakeTime,
    crawl_delay: int | None,
    site_delay: float,
    env_delay: int,
    expected: float,
) -> None:
    log: list[tuple[str, float]] = []
    text = "User-agent: *\n" + (f"Crawl-delay: {crawl_delay}\n" if crawl_delay is not None else "")
    robots(http, text=text)
    http.get(url__regex=rf"{SHOP}/p/\d").mock(side_effect=recorder(fake_time, log))
    settings = make_settings(scraper_min_delay_seconds=env_delay)
    fetcher = make_fetcher(fake_time, settings=settings, site_delays={"shop.example": site_delay})

    await fetcher.get(f"{SHOP}/p/1")
    await fetcher.get(f"{SHOP}/p/2")

    assert log[1][1] - log[0][1] == expected


async def test_jitter_between_zero_and_one_second_is_added_for_real_sites(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    robots(http, status=404)
    http.get(url__regex=rf"{SHOP}/p/\d").mock(side_effect=recorder(fake_time, log))
    fetcher = Fetcher(
        make_settings(), clock=fake_time.clock, sleep=fake_time.sleep, jitter=lambda: 0.6
    )

    await fetcher.get(f"{SHOP}/p/1")
    await fetcher.get(f"{SHOP}/p/2")

    assert log[1][1] - log[0][1] == pytest.approx(5.6)


async def test_two_domains_do_not_wait_for_each_other(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    robots(http, OTHER, status=404)
    http.get(f"{SHOP}/p").respond(200)
    http.get(f"{OTHER}/p").respond(200)
    fetcher = make_fetcher(fake_time)

    await fetcher.get(f"{SHOP}/p")
    await fetcher.get(f"{OTHER}/p")

    # Chỉ trang của SHOP chờ sau lượt robots.txt của chính nó; OTHER không phải chờ SHOP.
    assert fake_time.sleeps == [5.0, 5.0]
    assert fake_time.now == 10.0
    assert http.calls[2].request.url.host == "other.example"


async def test_two_domains_fetched_concurrently_both_complete(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    robots(http, OTHER, status=404)
    http.get(f"{SHOP}/p").respond(200, text="a")
    http.get(f"{OTHER}/p").respond(200, text="b")
    fetcher = make_fetcher(fake_time)

    a, b = await asyncio.gather(fetcher.get(f"{SHOP}/p"), fetcher.get(f"{OTHER}/p"))

    assert (a.text, b.text) == ("a", "b")


# --- Retry ------------------------------------------------------------------------------------


async def test_5xx_is_retried_with_exponential_backoff(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").mock(
        side_effect=[httpx.Response(500), httpx.Response(503), httpx.Response(200, text="ok")]
    )
    settings = make_settings(scraper_min_delay_seconds=0)

    response = await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert response.text == "ok"
    assert page.call_count == 3
    assert fake_time.sleeps == [5.0, 10.0]  # 5 · 2^n


async def test_gives_up_after_max_retries_with_fetch_failed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(500)
    settings = make_settings(scraper_min_delay_seconds=0, scraper_max_retries=2)

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert page.call_count == 3  # 1 lần đầu + 2 lần thử lại
    assert fake_time.sleeps == [5.0, 10.0]


async def test_zero_retries_means_one_attempt(http: respx.MockRouter, fake_time: FakeTime) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(502)
    settings = make_settings(scraper_min_delay_seconds=0, scraper_max_retries=0)

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert page.call_count == 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("x"), httpx.ReadTimeout("x"), httpx.RemoteProtocolError("x")]
)
async def test_network_errors_and_timeouts_are_retried(
    http: respx.MockRouter, fake_time: FakeTime, error: Exception
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").mock(side_effect=[error, httpx.Response(200, text="ok")])
    settings = make_settings(scraper_min_delay_seconds=0)

    assert (await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")).text == "ok"
    assert page.call_count == 2


async def test_retries_also_respect_the_domain_delay(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    robots(http, status=404)
    http.get(f"{SHOP}/p").mock(
        side_effect=[
            lambda request: (log.append(("p", fake_time.now)), httpx.Response(500))[1],
            lambda request: (log.append(("p", fake_time.now)), httpx.Response(200))[1],
        ]
    )

    await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert log[1][1] - log[0][1] >= 5.0


@pytest.mark.parametrize("status", [403])
async def test_403_is_returned_without_retry(
    http: respx.MockRouter, fake_time: FakeTime, status: int
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(status, text="Access denied")

    response = await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert (response.status, response.text) == (403, "Access denied")
    assert page.call_count == 1
    assert fake_time.sleeps == [5.0]  # chỉ độ trễ sau robots.txt, không backoff


@pytest.mark.parametrize("status", [404, 410, 400, 401, 451])
async def test_other_4xx_raise_http_status_error(
    http: respx.MockRouter, fake_time: FakeTime, status: int
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(status)

    with pytest.raises(HttpStatusError) as error:
        await make_fetcher(fake_time).get(f"{SHOP}/p")

    assert error.value.status == status
    assert page.call_count == 1


@pytest.mark.parametrize(
    ("retry_after", "expected_wait"),
    [("120", 120.0), ("5", 60.0), (None, 60.0), ("abc", 60.0)],
)
async def test_429_waits_for_retry_after_at_least_60_seconds_then_retries_once(
    http: respx.MockRouter, fake_time: FakeTime, retry_after: str | None, expected_wait: float
) -> None:
    robots(http, status=404)
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    page = http.get(f"{SHOP}/p").mock(
        side_effect=[httpx.Response(429, headers=headers), httpx.Response(200, text="ok")]
    )
    settings = make_settings(scraper_min_delay_seconds=0)

    response = await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert response.text == "ok"
    assert page.call_count == 2
    assert fake_time.sleeps == [expected_wait]


async def test_429_twice_is_returned_as_the_final_result(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(429, headers={"Retry-After": "60"})
    settings = make_settings(scraper_min_delay_seconds=0)

    response = await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert response.status == 429
    assert page.call_count == 2


async def test_429_with_an_excessive_retry_after_is_not_waited_for(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    page = http.get(f"{SHOP}/p").respond(429, headers={"Retry-After": "86400"})
    settings = make_settings(scraper_min_delay_seconds=0)

    response = await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert response.status == 429
    assert page.call_count == 1
    assert fake_time.sleeps == []


async def test_429_retry_after_as_http_date(http: respx.MockRouter, fake_time: FakeTime) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Mon, 19 Oct 2026 08:03:00 GMT"}),
            httpx.Response(200),
        ]
    )
    settings = make_settings(scraper_min_delay_seconds=0)
    fetcher = make_fetcher(
        fake_time,
        settings=settings,
        wall_now=lambda: datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
    )

    await fetcher.get(f"{SHOP}/p")

    assert fake_time.sleeps == [180.0]


# --- Chế độ ngoại tuyến -----------------------------------------------------------------------


async def test_offline_mode_blocks_real_domains_without_any_request(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    settings = make_settings(scraper_offline_only=True)

    with pytest.raises(OfflineModeError) as error:
        await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/p")

    assert "shop.example" in str(error.value)
    assert http.calls.call_count == 0


async def test_offline_mode_still_allows_the_mock_shop(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    http.get(f"{MOCK}/c/laptop").respond(200, text="mock")
    settings = make_settings(scraper_offline_only=True)

    assert (await make_fetcher(fake_time, settings=settings).get(f"{MOCK}/c/laptop")).text == "mock"


async def test_offline_mode_blocks_a_lookalike_of_the_mock_shop_host(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    settings = make_settings(scraper_offline_only=True)
    for url in ("http://localhost:8101/c", "http://localhost/c", "http://127.0.0.1:8100/c"):
        with pytest.raises(OfflineModeError):
            await make_fetcher(fake_time, settings=settings).get(url)


# --- Mock-shop --------------------------------------------------------------------------------


async def test_mock_shop_uses_its_own_delay_without_jitter(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    robots(http, MOCK, status=404)
    http.get(url__regex=rf"{MOCK}/p/\d").mock(side_effect=recorder(fake_time, log))
    settings = make_settings(mock_shop_delay_seconds=1.5, scraper_min_delay_seconds=5)
    fetcher = Fetcher(settings, clock=fake_time.clock, sleep=fake_time.sleep, jitter=lambda: 0.9)

    await fetcher.get(f"{MOCK}/p/1")
    await fetcher.get(f"{MOCK}/p/2")

    assert [at for _, at in log] == [1.5, 3.0]  # robots.txt ở 0, rồi cách nhau đúng 1,5 giây


async def test_mock_shop_zero_delay_never_sleeps(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    http.get(url__regex=rf"{MOCK}/p/\d").respond(200)
    settings = make_settings(mock_shop_delay_seconds=0)
    fetcher = make_fetcher(fake_time, settings=settings)

    for n in (1, 2, 3):
        await fetcher.get(f"{MOCK}/p/{n}")

    assert fake_time.sleeps == []


async def test_mock_shop_keeps_session_cookies_but_real_sites_never_do(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    robots(http, SHOP, status=404)
    mock_page = http.get(f"{MOCK}/p").mock(
        side_effect=[
            httpx.Response(200, headers={"Set-Cookie": "mock_pass=1; Path=/"}),
            httpx.Response(200),
        ]
    )
    shop_page = http.get(f"{SHOP}/p").mock(
        side_effect=[
            httpx.Response(200, headers={"Set-Cookie": "session=abc; Path=/"}),
            httpx.Response(200),
        ]
    )
    settings = make_settings(mock_shop_delay_seconds=0, scraper_min_delay_seconds=0)
    fetcher = make_fetcher(fake_time, settings=settings)

    await fetcher.get(f"{MOCK}/p")
    await fetcher.get(f"{MOCK}/p")
    await fetcher.get(f"{SHOP}/p")
    await fetcher.get(f"{SHOP}/p")

    assert mock_page.calls[1].request.headers.get("cookie") == "mock_pass=1"
    assert "cookie" not in shop_page.calls[1].request.headers


async def test_mock_transport_is_used_for_the_mock_shop_only(fake_time: FakeTime) -> None:
    seen: list[str] = []

    def app(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200, text="from-mock")

    settings = make_settings(scraper_offline_only=True, mock_shop_delay_seconds=0)
    fetcher = make_fetcher(fake_time, settings=settings, mock_transport=httpx.MockTransport(app))

    response = await fetcher.get(f"{MOCK}/c/laptop")

    assert response.text == "from-mock"
    assert seen == [f"{MOCK}/robots.txt", f"{MOCK}/c/laptop"]


# --- Chuyển hướng -----------------------------------------------------------------------------


async def test_same_domain_redirect_is_followed_and_reported_in_final_url(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/old").respond(301, headers={"Location": "/new?x=1#frag"})
    http.get(f"{SHOP}/new", params={"x": "1"}).respond(200, text="moved")

    response = await make_fetcher(fake_time).get(f"{SHOP}/old")

    assert (response.url, response.final_url) == (f"{SHOP}/old", f"{SHOP}/new?x=1")
    assert response.text == "moved"


async def test_http_to_https_redirect_on_the_same_host_is_followed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, "http://shop.example", status=404)
    robots(http, status=404)
    http.get("http://shop.example/p").respond(301, headers={"Location": f"{SHOP}/p"})
    http.get(f"{SHOP}/p").respond(200, text="secure")

    response = await make_fetcher(fake_time).get("http://shop.example/p")

    assert (response.final_url, response.text) == (f"{SHOP}/p", "secure")


async def test_redirect_to_another_domain_raises_without_requesting_it(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/go").respond(302, headers={"Location": f"{OTHER}/landing"})
    landing = http.get(f"{OTHER}/landing").respond(200)

    with pytest.raises(RedirectError):
        await make_fetcher(fake_time).get(f"{SHOP}/go")

    assert landing.call_count == 0
    assert not any(call.request.url.host == "other.example" for call in http.calls)


async def test_redirect_to_a_robots_blocked_url_raises_without_requesting_it(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, text="User-agent: *\nDisallow: /admin")
    http.get(f"{SHOP}/go").respond(302, headers={"Location": "/admin/panel"})
    target = http.get(f"{SHOP}/admin/panel").respond(200)

    with pytest.raises(RobotsDisallowed):
        await make_fetcher(fake_time).get(f"{SHOP}/go")

    assert target.call_count == 0


async def test_redirect_loop_stops_after_five_redirects(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    loop = http.get(f"{SHOP}/loop").respond(302, headers={"Location": "/loop"})
    settings = make_settings(scraper_min_delay_seconds=0)

    with pytest.raises(RedirectError, match="redirects"):
        await make_fetcher(fake_time, settings=settings).get(f"{SHOP}/loop")

    assert loop.call_count == 6


async def test_redirect_without_location_raises_http_status_error(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(302)
    with pytest.raises(HttpStatusError):
        await make_fetcher(fake_time).get(f"{SHOP}/p")


async def test_redirect_to_a_non_http_scheme_raises(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(302, headers={"Location": "ftp://shop.example/file"})
    with pytest.raises(RedirectError):
        await make_fetcher(fake_time).get(f"{SHOP}/p")


async def test_redirect_hops_pay_the_domain_delay(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    log: list[tuple[str, float]] = []
    robots(http, status=404)
    http.get(f"{SHOP}/a").mock(
        side_effect=lambda r: (
            log.append(("a", fake_time.now)),
            httpx.Response(302, headers={"Location": "/b"}),
        )[1]
    )
    http.get(f"{SHOP}/b").mock(side_effect=recorder(fake_time, log))

    await make_fetcher(fake_time).get(f"{SHOP}/a")

    assert log[1][1] - log[0][1] == 5.0


# --- Raw cache --------------------------------------------------------------------------------


async def test_pages_are_saved_to_the_raw_cache_for_debugging(
    http: respx.MockRouter, fake_time: FakeTime, tmp_path: Path
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(200, text="<p>Mô tả</p>")
    fetcher = make_fetcher(
        fake_time,
        raw_cache_dir=tmp_path,
        wall_now=lambda: datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
    )

    response = await fetcher.get(f"{SHOP}/p")

    saved = list((tmp_path / "shop.example" / "20261019").glob("*.html"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == "<p>Mô tả</p>"
    assert response.from_cache is False  # cache chỉ để debug, không bao giờ được đọc lại


async def test_raw_cache_write_failure_does_not_fail_the_request(
    http: respx.MockRouter, fake_time: FakeTime, tmp_path: Path
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(200, text="ok")
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    fetcher = make_fetcher(fake_time, raw_cache_dir=blocker)

    assert (await fetcher.get(f"{SHOP}/p")).text == "ok"


# --- Vòng đời ---------------------------------------------------------------------------------


async def test_async_context_manager_closes_the_clients(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, status=404)
    http.get(f"{SHOP}/p").respond(200)
    async with make_fetcher(fake_time) as fetcher:
        await fetcher.get(f"{SHOP}/p")
    with pytest.raises(RuntimeError):
        await fetcher.get(f"{SHOP}/p")


# --- post_form (đáp án captcha, chỉ mock-shop) ------------------------------------------------


async def test_post_form_sends_urlencoded_data_to_the_mock_shop_and_returns_any_status(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    route = http.post(f"{MOCK}/captcha").mock(
        side_effect=[httpx.Response(400, text="sai"), httpx.Response(200, text="ok")]
    )
    settings = make_settings(mock_shop_delay_seconds=0)
    fetcher = make_fetcher(fake_time, settings=settings)

    wrong = await fetcher.post_form(f"{MOCK}/captcha", {"token": "t", "answer": "ZZZZZ"})
    right = await fetcher.post_form(f"{MOCK}/captcha", {"token": "t", "answer": "ABCDE"})

    assert (wrong.status, wrong.text) == (400, "sai")  # không ném lỗi, không retry
    assert (right.status, right.text) == (200, "ok")
    assert route.call_count == 2
    request = route.calls[1].request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.content == b"token=t&answer=ABCDE"
    assert request.headers["user-agent"] == make_settings().scraper_user_agent


async def test_post_form_is_refused_for_real_sites_without_any_request(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    for settings in (make_settings(), make_settings(scraper_offline_only=True)):
        with pytest.raises(FormNotAllowed) as error:
            await make_fetcher(fake_time, settings=settings).post_form(
                f"{SHOP}/captcha", {"a": "b"}
            )
        assert error.value.url == f"{SHOP}/captcha"
    assert http.calls.call_count == 0


async def test_post_form_rejects_non_http_urls(http: respx.MockRouter, fake_time: FakeTime) -> None:
    with pytest.raises(RedirectError):
        await make_fetcher(fake_time).post_form("ftp://localhost:8100/captcha", {})


async def test_post_form_network_error_is_fetch_failed_and_not_retried(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    route = http.post(f"{MOCK}/captcha").mock(side_effect=httpx.ConnectError("down"))
    settings = make_settings(mock_shop_delay_seconds=0)

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time, settings=settings).post_form(f"{MOCK}/captcha", {"a": "b"})

    assert route.call_count == 1


async def test_post_form_respects_robots_and_the_mock_delay(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, text="User-agent: *\nDisallow: /captcha")
    route = http.post(f"{MOCK}/captcha").respond(200)
    with pytest.raises(RobotsDisallowed):
        await make_fetcher(fake_time).post_form(f"{MOCK}/captcha", {"a": "b"})
    assert route.call_count == 0


async def test_cookie_set_by_post_form_is_sent_on_later_gets(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, status=404)
    http.post(f"{MOCK}/captcha").respond(200, headers={"Set-Cookie": "mock_pass=abc; Path=/"})
    page = http.get(f"{MOCK}/c/laptop").respond(200, text="ok")
    settings = make_settings(mock_shop_delay_seconds=0)
    fetcher = make_fetcher(fake_time, settings=settings)

    await fetcher.post_form(f"{MOCK}/captcha", {"token": "t", "answer": "A"})
    await fetcher.get(f"{MOCK}/c/laptop")

    assert page.calls.last.request.headers["cookie"] == "mock_pass=abc"
