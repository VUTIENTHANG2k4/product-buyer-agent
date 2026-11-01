"""Khe thời gian gửi request theo domain dùng chung cho `api` và `worker` (T9.8, docs/06 §7).

`DomainRateLimiter` chỉ giữ độ trễ trong một tiến trình; bộ này đặt chỗ trong PostgreSQL nên hai
tiến trình tải cùng một domain vẫn cách nhau >= độ trễ của domain (quy tắc ≥ 5 s/domain).
"""

import asyncio

from app.db.repositories import DomainThrottleRepository
from app.services.database import SessionFactory


class DbDomainThrottle:
    """Khớp `SharedDelay` của `scrapers/http/rate_limiter.py`."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reserve(self, domain: str, delay: float) -> float:
        """Số giây phải chờ trước khi gửi; chỗ được giữ (commit) ngay cả khi người gọi bị hủy."""
        return await asyncio.to_thread(self._reserve, domain, delay)

    def _reserve(self, domain: str, delay: float) -> float:
        with self._session_factory() as session:
            wait = DomainThrottleRepository(session).reserve(domain, delay)
            session.commit()
        return wait
