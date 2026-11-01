"""QA M2: Fetcher với phản hồi lạ (Retry-After, Location, mã hóa, userinfo). respx, đồng hồ giả."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.scrapers.http.errors import (
    FetchError,
    HttpStatusError,
    OfflineModeError,
    RedirectError,
)
from app.scrapers.http.fetcher import Fetcher

SHOP = "https://shop.example"
MOCK = "http://localhost:8100"


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


def fetcher_for(fake: FakeTime, **overrides: Any) -> Fetcher:
    values: dict[str, Any] = {
        "scraper_offline_only": False,
        "scraper_min_delay_seconds": 5,
        "scraper_max_retries": 3,
        "mock_shop_url": MOCK,
        "mock_shop_delay_seconds": 1,
    }
    return Fetcher(
        Settings(**{**values, **overrides}),
        clock=fake.clock,
        sleep=fake.sleep,
        jitter=lambda: 0.0,
    )


def robots(http: respx.MockRouter, origin: str = SHOP, text: str = "") -> None:
    http.get(f"{origin}/robots.txt").respond(200, text=text)


# --- Retry-After lạ ---------------------------------------------------------------------------


async def test_a_nan_retry_after_is_treated_like_a_missing_header(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/p").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "nan"}),
            httpx.Response(200, text="ok"),
        ]
    )

    response = await fetcher_for(fake_time).get(f"{SHOP}/p")

    assert response.status == 200
    assert 60.0 in fake_time.sleeps
    assert all(0 <= seconds <= 600 for seconds in fake_time.sleeps)


@pytest.mark.parametrize(
    ("header", "expected_wait"),
    [
        ("-30", 60.0),  # âm → tối thiểu 60
        ("0", 60.0),
        ("90.5", 90.5),  # số thực
        ("600", 600.0),  # đúng ngưỡng vẫn chờ
        ("Wed, 21 Oct 2015 07:28:00 GMT", 60.0),  # ngày đã qua
        ("tomorrow", 60.0),  # rác
        ("", 60.0),
    ],
)
async def test_retry_after_is_clamped_to_at_least_60_seconds(
    http: respx.MockRouter, fake_time: FakeTime, header: str, expected_wait: float
) -> None:
    robots(http)
    http.get(f"{SHOP}/p").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": header}),
            httpx.Response(200, text="ok"),
        ]
    )

    response = await fetcher_for(fake_time).get(f"{SHOP}/p")

    assert response.status == 200
    assert expected_wait in fake_time.sleeps


@pytest.mark.parametrize("header", ["601", "1e3", "inf", "86400"])
async def test_a_retry_after_over_ten_minutes_is_not_waited_for(
    http: respx.MockRouter, fake_time: FakeTime, header: str
) -> None:
    robots(http)
    page = http.get(f"{SHOP}/p").mock(
        return_value=httpx.Response(429, headers={"Retry-After": header})
    )

    response = await fetcher_for(fake_time).get(f"{SHOP}/p")

    assert response.status == 429
    assert page.call_count == 1
    assert max(fake_time.sleeps, default=0) < 60


async def test_429_then_5xx_then_429_waits_for_rate_limit_once_and_returns_the_last_429(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    page = http.get(f"{SHOP}/p").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(429),
            httpx.Response(200, text="never reached"),
        ]
    )

    response = await fetcher_for(fake_time).get(f"{SHOP}/p")

    assert response.status == 429
    assert page.call_count == 3
    assert fake_time.sleeps.count(60.0) == 1  # chỉ chờ rate limit một lần


# --- Location lạ ------------------------------------------------------------------------------


@pytest.mark.parametrize("location", ["javascript:alert(1)", "mailto:a@shop.example"])
async def test_a_non_http_location_is_a_redirect_error_without_resending_the_request(
    http: respx.MockRouter, fake_time: FakeTime, location: str
) -> None:
    robots(http)
    page = http.get(f"{SHOP}/a").respond(302, headers={"Location": location})

    with pytest.raises(RedirectError):
        await fetcher_for(fake_time).get(f"{SHOP}/a")

    assert page.call_count == 1


async def test_a_redirect_to_the_same_host_with_the_default_port_is_followed(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/a").respond(301, headers={"Location": "https://shop.example:443/b"})
    http.get("https://shop.example:443/b").respond(200, text="b")

    response = await fetcher_for(fake_time).get(f"{SHOP}/a")

    assert response.text == "b"


async def test_hostile_redirect_targets_never_send_a_request_to_another_host(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/a").respond(302, headers={"Location": "//evil.example/x"})
    http.get(f"{SHOP}/b").respond(302, headers={"Location": "https://shop.example.evil.example/x"})
    http.get(f"{SHOP}/c").respond(302, headers={"Location": "https://shop.example@evil.example/x"})
    http.get(f"{SHOP}/d").respond(302, headers={"Location": ""})
    fetcher = fetcher_for(fake_time)

    for path in ("/a", "/b", "/c"):
        with pytest.raises(RedirectError):
            await fetcher.get(f"{SHOP}{path}")
    with pytest.raises(HttpStatusError):
        await fetcher.get(f"{SHOP}/d")

    assert {call.request.url.host for call in http.calls} == {"shop.example"}


async def test_an_http_to_https_redirect_on_the_same_host_is_followed_with_robots_for_each_origin(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, "http://shop.example")
    robots(http, SHOP, "User-agent: *\nDisallow: /private\n")
    http.get("http://shop.example/a").respond(301, headers={"Location": "https://shop.example/b"})
    http.get(f"{SHOP}/b").respond(200, text="b")
    http.get("http://shop.example/c").respond(
        301, headers={"Location": "https://shop.example/private/x"}
    )
    page = http.get(f"{SHOP}/private/x").respond(200, text="secret")
    fetcher = fetcher_for(fake_time)

    assert (await fetcher.get("http://shop.example/a")).final_url == f"{SHOP}/b"
    with pytest.raises(FetchError):  # robots của origin https chặn đích chuyển hướng
        await fetcher.get("http://shop.example/c")
    assert page.call_count == 0


# --- nội dung và danh tính --------------------------------------------------------------------


async def test_a_body_that_is_not_utf8_is_decoded_without_raising(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/bad").respond(
        200, content=b"<p>\xff\xfe broken \xe1\xbb</p>", headers={"Content-Type": "text/html"}
    )
    http.get(f"{SHOP}/legacy").respond(
        200,
        content="<p>Café</p>".encode("windows-1252"),
        headers={"Content-Type": "text/html; charset=windows-1252"},
    )
    http.get(f"{SHOP}/unknown-charset").respond(
        200, content="<p>Chuột</p>".encode(), headers={"Content-Type": "text/html; charset=bogus"}
    )
    fetcher = fetcher_for(fake_time)

    broken = await fetcher.get(f"{SHOP}/bad")
    legacy = await fetcher.get(f"{SHOP}/legacy")
    unknown = await fetcher.get(f"{SHOP}/unknown-charset")

    assert broken.text.startswith("<p>") and "broken" in broken.text
    assert legacy.text == "<p>Café</p>"
    assert unknown.text == "<p>Chuột</p>"


async def test_a_url_with_userinfo_sends_no_credentials_and_shares_the_domain_delay(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/a").respond(200, text="a")
    http.get(url__regex=r"https://.*shop\.example/b").respond(200, text="b")
    fetcher = fetcher_for(fake_time)

    await fetcher.get(f"{SHOP}/a")
    sleeps_before = len(fake_time.sleeps)
    try:
        await fetcher.get("https://user:secret@shop.example/b")
    except FetchError:
        return  # từ chối hẳn cũng chấp nhận được
    assert all("authorization" not in call.request.headers for call in http.calls)
    assert len(fake_time.sleeps) > sleeps_before  # vẫn chờ độ trễ của shop.example


async def test_domains_that_differ_only_by_port_are_separate_for_robots_and_offline_mode(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http, MOCK, "User-agent: *\nDisallow: /admin\n")
    http.get(f"{MOCK}/ok").respond(200, text="ok")
    admin = http.get(f"{MOCK}/admin").respond(200, text="admin")
    fetcher = fetcher_for(fake_time, scraper_offline_only=True)

    assert (await fetcher.get(f"{MOCK}/ok")).text == "ok"
    assert (await fetcher.get("http://LOCALHOST:8100/ok")).text == "ok"  # host không phân biệt hoa
    with pytest.raises(OfflineModeError):
        await fetcher.get("http://localhost:8101/ok")  # cổng khác không phải mock-shop
    with pytest.raises(FetchError):  # URL hỏng (cổng không phải số) bị từ chối, không gửi gì
        await fetcher.get("http://localhost:8100.evil.example/ok")
    with pytest.raises(FetchError):
        await fetcher.get(f"{MOCK}/admin/users")
    assert admin.call_count == 0
