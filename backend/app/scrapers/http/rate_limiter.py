"""Giới hạn tốc độ theo domain: mỗi domain tối đa một request mỗi `delay` giây (docs/06 §3)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol


class SharedDelay(Protocol):
    """Khe thời gian dùng chung giữa các tiến trình (cài đặt ở lớp services, T9.8)."""

    async def reserve(self, domain: str, delay: float) -> float:
        """Đặt chỗ một request tới `domain`; trả số giây (>= 0) phải chờ trước khi gửi."""
        ...


class DomainRateLimiter:
    """Khóa asyncio theo domain; `clock` (giây, đơn điệu) và `sleep` tiêm được cho test đồng hồ giả.

    Các domain khác nhau không chờ nhau. Request tiếp theo tới cùng domain chờ đến khi
    `now - lần gần nhất >= delay`; các request đồng thời tới cùng domain được xếp hàng.
    `shared` (tùy chọn) áp thêm khe dùng chung giữa các tiến trình (`api` và `worker`).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        shared: SharedDelay | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._shared = shared
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
            if self._shared is not None and delay > 0:
                # Còn trong khóa của domain nên request cùng tiến trình vẫn xếp hàng; lỗi đặt chỗ
                # được ném lên (fail-closed), không ghi nhận request.
                extra = await self._shared.reserve(domain, delay)
                if extra > 0:
                    await self._sleep(extra)
            self._last[domain] = self._clock()
