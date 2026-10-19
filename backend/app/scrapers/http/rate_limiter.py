"""Giới hạn tốc độ theo domain: mỗi domain tối đa một request mỗi `delay` giây (docs/06 §3)."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class DomainRateLimiter:
    """Khóa asyncio theo domain; `clock` (giây, đơn điệu) và `sleep` tiêm được cho test đồng hồ giả.

    Các domain khác nhau không chờ nhau. Request tiếp theo tới cùng domain chờ đến khi
    `now - lần gần nhất >= delay`; các request đồng thời tới cùng domain được xếp hàng.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, domain: str, delay: float) -> None:
        """Chờ tới lượt của `domain` rồi ghi nhận request; `delay` tính bằng giây (>= 0)."""
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            last = self._last.get(domain)
            if last is not None:
                remaining = last + delay - self._clock()
                if remaining > 0:
                    await self._sleep(remaining)
            self._last[domain] = self._clock()
