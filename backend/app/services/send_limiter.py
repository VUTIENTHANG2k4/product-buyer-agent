"""Giới hạn tần suất gửi thông báo thử theo cảnh báo (T9.6).

`POST /alerts/{id}/test` không xác thực (ứng dụng chạy cho một người dùng) và gửi thư thật, nên ai
gọi được API cũng có thể bắt máy chủ gửi thư liên tục. Bộ giới hạn nằm trong bộ nhớ của tiến trình
(đủ cho một tiến trình `api`; nhiều tiến trình thì mỗi tiến trình giới hạn riêng).
"""

import math
import threading
import time
from collections.abc import Callable

DEFAULT_INTERVAL_SECONDS = 10.0
_MAX_TRACKED = 1000  # quá số này thì quên các mục đã hết hạn để bộ nhớ không phình ra

MonotonicClock = Callable[[], float]


class SendLimiter:
    """Mỗi `key` (id cảnh báo) chỉ được gửi lại sau `interval` giây kể từ lần gửi trước."""

    def __init__(
        self, interval: float = DEFAULT_INTERVAL_SECONDS, *, clock: MonotonicClock = time.monotonic
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._last: dict[int, float] = {}
        # Router là hàm đồng bộ nên chạy trong threadpool: kiểm tra và ghi nhận phải nguyên tử, nếu
        # không nhiều request song song cùng thấy "được gửi".
        self._lock = threading.Lock()

    def try_acquire(self, key: int) -> int:
        """0 và ghi nhận lần gửi này nếu được gửi ngay; ngược lại số giây (làm tròn lên) còn phải
        chờ, không ghi nhận gì."""
        with self._lock:
            now = self._clock()
            last = self._last.get(key)
            if last is not None:
                remaining = self._interval - (now - last)
                if remaining > 0:
                    return math.ceil(remaining)
            if len(self._last) >= _MAX_TRACKED:
                self._last = {k: t for k, t in self._last.items() if now - t < self._interval}
            self._last[key] = now
            return 0
