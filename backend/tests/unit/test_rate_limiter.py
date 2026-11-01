"""DomainRateLimiter (app/scrapers/http/rate_limiter.py) với đồng hồ giả."""

import asyncio

from app.scrapers.http.rate_limiter import DomainRateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make() -> tuple[DomainRateLimiter, FakeTime]:
    fake = FakeTime()
    return DomainRateLimiter(clock=fake.clock, sleep=fake.sleep), fake


async def test_first_request_to_a_domain_does_not_wait() -> None:
    limiter, fake = make()
    await limiter.wait("a.example", 5)
    assert fake.sleeps == []


async def test_second_request_waits_the_remaining_delay() -> None:
    limiter, fake = make()
    await limiter.wait("a.example", 5)
    fake.now = 2.0
    await limiter.wait("a.example", 5)
    assert fake.sleeps == [3.0]
    assert fake.now == 5.0


async def test_no_wait_when_the_delay_has_already_passed() -> None:
    limiter, fake = make()
    await limiter.wait("a.example", 5)
    fake.now = 5.0
    await limiter.wait("a.example", 5)
    assert fake.sleeps == []


async def test_zero_delay_never_sleeps() -> None:
    limiter, fake = make()
    for _ in range(3):
        await limiter.wait("a.example", 0)
    assert fake.sleeps == []


async def test_domains_do_not_wait_for_each_other() -> None:
    limiter, fake = make()
    await limiter.wait("a.example", 5)
    await limiter.wait("b.example", 5)
    assert fake.sleeps == []


async def test_concurrent_requests_to_one_domain_are_spaced_out() -> None:
    limiter, fake = make()
    times: list[float] = []

    async def hit() -> None:
        await limiter.wait("a.example", 5)
        times.append(fake.now)

    await asyncio.gather(hit(), hit(), hit())
    assert times == [0.0, 5.0, 10.0]


async def test_a_slow_domain_does_not_block_another_domain() -> None:
    gate = asyncio.Event()
    started: list[str] = []

    async def blocking_sleep(_: float) -> None:
        started.append("a")
        await gate.wait()

    limiter = DomainRateLimiter(clock=lambda: 0.0, sleep=blocking_sleep)
    await limiter.wait("a.example", 5)
    waiting = asyncio.create_task(limiter.wait("a.example", 5))
    await asyncio.sleep(0)
    await asyncio.wait_for(limiter.wait("b.example", 5), timeout=1)  # không bị a chặn
    assert not waiting.done()
    gate.set()
    await waiting
