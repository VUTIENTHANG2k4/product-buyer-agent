"""Tác vụ nền của API (thu thập, lượt chạy agent): giữ tham chiếu để không bị thu gom giữa chừng."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(
        self, work: Coroutine[Any, Any, Any], *, name: str | None = None
    ) -> asyncio.Task[Any]:
        """Chạy `work` nền trên event loop hiện tại; lỗi không bắt được chỉ ghi log."""
        task = asyncio.get_running_loop().create_task(work, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Tác vụ nền %s lỗi", task.get_name(), exc_info=task.exception())

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def wait_all(self) -> None:
        """Chờ mọi tác vụ đang chạy (kể cả tác vụ sinh thêm trong lúc chờ). Dùng trong test."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel_all(self) -> None:
        """Hủy mọi tác vụ rồi chờ chúng dọn xong (lượt thu thập tự chốt trạng thái khi bị hủy)."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
