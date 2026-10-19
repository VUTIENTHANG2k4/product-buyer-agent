"""M3b/T2.7: `Retry-After` của HTTP 503, robots.txt quá 500 KiB, hai domain song song."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.scrapers.http.errors import FetchFailed, RobotsUnavailable
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.robots import MAX_ROBOTS_CHARS, RobotsCache
from tests.unit.test_fetcher import OTHER, SHOP, FakeTime, make_fetcher, make_settings

PAGE = f"{SHOP}/p"
ROBOTS = f"{SHOP}/robots.txt"
UA = "ProductBuyerAgent/0.1 (+test)"


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.get(ROBOTS).respond(404)
        router.get(f"{OTHER}/robots.txt").respond(404)
        yield router


# --- Retry-After của 503 ------------------------------------------------------------------------


def waits_between_requests(fake_time: FakeTime) -> list[float]:
    """Các lần ngủ lớn hơn độ trễ domain (5 giây): chính là thời gian chờ retry."""
    return [seconds for seconds in fake_time.sleeps if seconds != 5.0]


@pytest.mark.parametrize(
    ("retry_after", "expected_first_wait"),
    [("30", 30.0), ("7", 7.0), ("2", 5.0), ("", 5.0), ("abc", 5.0), ("-10", 5.0), ("nan", 5.0)],
)
async def test_503_waits_for_retry_after_when_longer_than_the_backoff(
    http: respx.MockRouter, fake_time: FakeTime, retry_after: str, expected_first_wait: float
) -> None:
    headers = {"Retry-After": retry_after} if retry_after else {}
    http.get(PAGE).mock(
        side_effect=[
            httpx.Response(503, headers=headers, text="busy"),
            httpx.Response(200, text="ok"),
        ]
    )

    response = await make_fetcher(fake_time).get(PAGE)

    assert response.text == "ok"
    assert expected_first_wait in fake_time.sleeps
    assert max(fake_time.sleeps) == expected_first_wait


async def test_503_retry_after_given_as_an_http_date_is_honoured(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    now = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
    http.get(PAGE).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "Mon, 19 Oct 2026 08:01:00 GMT"}),
            httpx.Response(200, text="ok"),
        ]
    )
    fetcher = make_fetcher(fake_time, wall_now=lambda: now)

    assert (await fetcher.get(PAGE)).text == "ok"
    assert 60.0 in fake_time.sleeps


@pytest.mark.parametrize("retry_after", ["601", "86400", "inf"])
async def test_503_with_a_huge_retry_after_stops_without_waiting(
    http: respx.MockRouter, fake_time: FakeTime, retry_after: str
) -> None:
    page = http.get(PAGE).respond(503, headers={"Retry-After": retry_after}, text="down")

    with pytest.raises(FetchFailed, match="too long"):
        await make_fetcher(fake_time).get(PAGE)

    assert page.call_count == 1
    assert waits_between_requests(fake_time) == []


async def test_other_5xx_ignore_retry_after_and_keep_the_doubling_backoff(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(PAGE).respond(502, headers={"Retry-After": "300"}, text="bad gateway")

    with pytest.raises(FetchFailed):
        await make_fetcher(fake_time).get(PAGE)

    assert 300.0 not in fake_time.sleeps
    assert [wait for wait in fake_time.sleeps if wait > 5.0] == [10.0, 20.0]


# --- robots.txt quá 500 KiB ---------------------------------------------------------------------


async def test_a_robots_txt_over_500_kib_is_unavailable_and_not_cached() -> None:
    calls: list[str] = []

    async def loader(origin: str) -> tuple[int, str]:
        calls.append(origin)
        return 200, "User-agent: *\nDisallow: /early\n" + "#" * MAX_ROBOTS_CHARS

    cache = RobotsCache(loader, UA)

    for _ in range(2):
        with pytest.raises(RobotsUnavailable, match="500 KiB"):
            await cache.rules(SHOP)

    assert calls == [SHOP, SHOP]


async def test_a_robots_txt_of_exactly_500_kib_is_still_parsed() -> None:
    prefix = "User-agent: *\nDisallow: /early\n"

    async def loader(origin: str) -> tuple[int, str]:
        return 200, prefix + "#" * (MAX_ROBOTS_CHARS - len(prefix))

    rules = await RobotsCache(loader, UA).rules(SHOP)

    assert rules.allowed(f"{SHOP}/early") is False
    assert rules.allowed(f"{SHOP}/other") is True


async def test_fetcher_sends_no_page_request_when_robots_txt_is_over_500_kib(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    http.get(ROBOTS).respond(200, text="User-agent: *\n" + "#" * (MAX_ROBOTS_CHARS + 1))
    page = http.get(PAGE).respond(200, text="ok")

    with pytest.raises(RobotsUnavailable):
        await make_fetcher(fake_time).get(PAGE)

    assert page.call_count == 0


# --- Hai domain chạy song song ở mức Fetcher ----------------------------------------------------


async def test_a_domain_waiting_for_its_delay_does_not_hold_back_another_domain(
    http: respx.MockRouter,
) -> None:
    """A ngủ trong độ trễ 5 giây (bị giữ bằng Event); B vẫn hoàn tất `get` trong lúc A chưa dậy."""
    http.get(PAGE).respond(200, text="a")
    http.get(f"{OTHER}/p").respond(200, text="b")
    now = 0.0
    release_a = asyncio.Event()
    sleepers: list[str] = []
    a_is_sleeping = asyncio.Event()

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        sleepers.append("a" if not sleepers else "b")
        if len(sleepers) == 1:
            a_is_sleeping.set()
            await release_a.wait()  # lần ngủ đầu tiên là của domain A
        now += seconds

    fetcher = Fetcher(make_settings(), clock=clock, sleep=sleep, jitter=lambda: 0.0)
    task_a = asyncio.create_task(fetcher.get(PAGE))
    await asyncio.wait_for(a_is_sleeping.wait(), timeout=5)

    response_b = await asyncio.wait_for(fetcher.get(f"{OTHER}/p"), timeout=5)

    assert response_b.text == "b"
    assert not task_a.done()
    release_a.set()
    assert (await task_a).text == "a"
    assert sleepers == ["a", "b"]
