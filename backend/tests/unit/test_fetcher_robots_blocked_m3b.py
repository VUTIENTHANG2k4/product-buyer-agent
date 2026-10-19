"""M3b/T3.4: robots.txt bị CDN chặn (403, 429, trang challenge 5xx) ném `RobotsBlocked`.

Khác `RobotsUnavailable` thường (lỗi mạng, 5xx): pipeline đổi thành `BLOCKED` và nghỉ 24 giờ.
"""

from collections.abc import Iterator

import httpx
import pytest
import respx

from app.scrapers.http.errors import RobotsBlocked, RobotsDisallowed, RobotsUnavailable
from tests.unit.test_fetcher import SHOP, FakeTime, make_fetcher

PAGE = f"{SHOP}/p"
ROBOTS = f"{SHOP}/robots.txt"


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


BLOCKING_RESPONSES = [
    pytest.param(httpx.Response(403, text="Forbidden"), 403, id="403"),
    pytest.param(httpx.Response(429, text="Too many"), 429, id="429"),
    pytest.param(
        httpx.Response(503, headers={"cf-mitigated": "challenge"}, text="x"), 503, id="503-cf"
    ),
    pytest.param(
        httpx.Response(
            503, headers={"server": "cloudflare"}, text="<title>Just a moment...</title>"
        ),
        503,
        id="503-just-a-moment",
    ),
    pytest.param(httpx.Response(500, text="please solve the captcha"), 500, id="500-captcha-text"),
]


@pytest.mark.parametrize(("response", "status"), BLOCKING_RESPONSES)
async def test_blocked_robots_txt_raises_robots_blocked_and_sends_no_page_request(
    http: respx.MockRouter, fake_time: FakeTime, response: httpx.Response, status: int
) -> None:
    http.get(ROBOTS).mock(return_value=response)
    page = http.get(PAGE).respond(200, text="ok")

    with pytest.raises(RobotsBlocked) as error:
        await make_fetcher(fake_time).get(PAGE)

    assert error.value.status == status
    assert error.value.url == ROBOTS
    assert page.call_count == 0


def test_robots_blocked_is_a_robots_unavailable_and_a_robots_disallowed() -> None:
    assert issubclass(RobotsBlocked, RobotsUnavailable)
    assert issubclass(RobotsBlocked, RobotsDisallowed)


async def test_a_blocked_robots_txt_is_not_cached_so_the_next_call_tries_again(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robot = http.get(ROBOTS).mock(side_effect=[httpx.Response(403), httpx.Response(200, text="")])
    http.get(PAGE).respond(200, text="ok")
    fetcher = make_fetcher(fake_time)

    with pytest.raises(RobotsBlocked):
        await fetcher.get(PAGE)

    assert (await fetcher.get(PAGE)).text == "ok"
    assert robot.call_count == 2


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_an_ordinary_5xx_robots_txt_stays_unavailable_not_blocked(
    http: respx.MockRouter, fake_time: FakeTime, status: int
) -> None:
    http.get(ROBOTS).respond(status, text="Internal error")

    with pytest.raises(RobotsUnavailable) as error:
        await make_fetcher(fake_time).get(PAGE)

    assert not isinstance(error.value, RobotsBlocked)


async def test_a_401_robots_txt_still_disallows_the_site_without_being_a_challenge(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(ROBOTS).respond(401)
    page = http.get(PAGE).respond(200)

    with pytest.raises(RobotsDisallowed) as error:
        await make_fetcher(fake_time).get(PAGE)

    assert not isinstance(error.value, RobotsBlocked)
    assert page.call_count == 0
