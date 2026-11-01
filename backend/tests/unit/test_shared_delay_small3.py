"""T9.8: khe thời gian dùng chung giữa các tiến trình (SharedDelay) trong limiter và Fetcher."""

from collections.abc import Iterator

import pytest
import respx

from app.scrapers.http.errors import FetchFailed
from app.scrapers.http.fetcher import Fetcher
from app.scrapers.http.rate_limiter import DomainRateLimiter
from tests.unit.test_fetcher import SHOP, FakeTime, make_settings, robots


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


class RecordingShared:
    def __init__(self, waits: list[float] | None = None, error: Exception | None = None) -> None:
        self.waits = waits or []
        self.error = error
        self.calls: list[tuple[str, float]] = []

    async def reserve(self, domain: str, delay: float) -> float:
        self.calls.append((domain, delay))
        if self.error is not None:
            raise self.error
        return self.waits.pop(0) if self.waits else 0.0


def make(shared: RecordingShared) -> tuple[DomainRateLimiter, FakeTime]:
    fake = FakeTime()
    return DomainRateLimiter(clock=fake.clock, sleep=fake.sleep, shared=shared), fake


async def test_the_shared_wait_is_slept_on_top_of_the_local_delay() -> None:
    shared = RecordingShared(waits=[0.0, 4.0])
    limiter, fake = make(shared)

    await limiter.wait("a.example", 5)  # lần đầu: không chờ ở cả hai nơi
    fake.now = 2.0
    await limiter.wait("a.example", 5)  # local chờ 3 s, dùng chung chờ thêm 4 s

    assert shared.calls == [("a.example", 5), ("a.example", 5)]
    assert fake.sleeps == [3.0, 4.0]
    assert fake.now == 9.0


async def test_zero_delay_never_touches_the_shared_slot() -> None:
    shared = RecordingShared()
    limiter, _ = make(shared)

    await limiter.wait("localhost:8100", 0)
    await limiter.wait("localhost:8100", 0)

    assert shared.calls == []


async def test_a_shared_failure_propagates_and_is_not_recorded_as_a_request() -> None:
    shared = RecordingShared(error=RuntimeError("db down"))
    limiter, fake = make(shared)

    with pytest.raises(RuntimeError):
        await limiter.wait("a.example", 5)

    shared.error = None  # lần sau không bị coi là vừa gửi (không có mốc local)
    await limiter.wait("a.example", 5)
    assert fake.sleeps == []


async def test_fetcher_does_not_send_a_request_when_the_shared_slot_cannot_be_reserved(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    page = http.get(f"{SHOP}/p").respond(200, text="ok")
    fetcher = Fetcher(
        make_settings(),
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        jitter=lambda: 0.0,
        shared_delay=RecordingShared(error=ConnectionError("db down")),
    )

    with pytest.raises(FetchFailed, match="khe dùng chung"):
        await fetcher.get(f"{SHOP}/p")

    assert page.call_count == 0
    assert http.calls.call_count == 0  # kể cả robots.txt cũng không được tải


async def test_fetcher_reserves_one_slot_per_request_for_real_sites_only(
    http: respx.MockRouter, fake_time: FakeTime
) -> None:
    robots(http)
    http.get(f"{SHOP}/p").respond(200, text="ok")
    http.get("http://localhost:8100/robots.txt").respond(200, text="")
    http.get("http://localhost:8100/c/laptop").respond(200, text="ok")
    shared = RecordingShared()
    fetcher = Fetcher(
        make_settings(mock_shop_delay_seconds=0),
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        jitter=lambda: 0.0,
        shared_delay=shared,
    )

    await fetcher.get(f"{SHOP}/p")
    shop_calls = list(shared.calls)
    await fetcher.get("http://localhost:8100/c/laptop")

    assert {domain for domain, _ in shop_calls} == {"shop.example"}  # robots.txt + trang
    assert len(shop_calls) == 2
    assert shared.calls == shop_calls  # mock-shop (độ trễ 0) không đặt chỗ
