"""T9.6: giới hạn tần suất gửi thông báo thử."""

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

    assert limiter.wait_seconds(1) == 0
    limiter.record(1)
    assert limiter.wait_seconds(1) == 10
    clock.now += 3.5
    assert limiter.wait_seconds(1) == 7  # làm tròn lên
    clock.now += 6.5
    assert limiter.wait_seconds(1) == 0


def test_keys_are_limited_independently() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)

    limiter.record(1)

    assert limiter.wait_seconds(1) > 0
    assert limiter.wait_seconds(2) == 0


@pytest.mark.parametrize("extra", [0, 5])
def test_expired_entries_are_forgotten_when_the_table_is_full(extra: int) -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(1000 + extra):
        limiter.record(key)
    clock.now += 11

    limiter.record(-1)

    assert limiter.wait_seconds(0) == 0
    assert limiter.wait_seconds(-1) == 10
    assert len(limiter._last) == 1  # noqa: SLF001
