"""T9.6: giới hạn tần suất gửi thông báo thử."""

import threading

import pytest

from app.services.send_limiter import SendLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_first_send_is_allowed_then_blocked_until_the_interval_passes() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)

    assert limiter.try_acquire(1) == 0
    assert limiter.try_acquire(1) == 10  # bị từ chối không làm mới mốc
    clock.now += 3.5
    assert limiter.try_acquire(1) == 7  # làm tròn lên
    clock.now += 6.5
    assert limiter.try_acquire(1) == 0


def test_keys_are_limited_independently() -> None:
    limiter = SendLimiter(10, clock=FakeClock())

    assert limiter.try_acquire(1) == 0
    assert limiter.try_acquire(1) > 0
    assert limiter.try_acquire(2) == 0


@pytest.mark.parametrize("extra", [0, 5])
def test_expired_entries_are_forgotten_when_the_table_is_full(extra: int) -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(1000 + extra):
        limiter.try_acquire(key)
    clock.now += 11

    assert limiter.try_acquire(-1) == 0

    assert len(limiter._last) == 1  # noqa: SLF001
    assert limiter.try_acquire(0) == 0  # mục hết hạn đã bị quên, gửi lại được


def test_parallel_requests_for_one_key_let_exactly_one_through() -> None:
    limiter = SendLimiter(10, clock=FakeClock())
    threads = 20
    barrier = threading.Barrier(threads)
    results: list[int] = []

    def attempt() -> None:
        barrier.wait()
        results.append(limiter.try_acquire(7))

    workers = [threading.Thread(target=attempt) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert results.count(0) == 1
    assert len(results) == threads
