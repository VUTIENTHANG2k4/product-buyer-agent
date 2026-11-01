"""Tác vụ nền của API (thu thập, lượt chạy agent): giữ tham chiếu để không bị thu gom giữa chừng."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._on_cancel: dict[asyncio.Task[Any], Callable[[], Awaitable[None]]] = {}

    def spawn(
        self,
        work: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
        on_cancel: Callable[[], Awaitable[None]] | None = None,
    ) -> asyncio.Task[Any]:
        """Chạy `work` nền trên event loop hiện tại; lỗi không bắt được chỉ ghi log.

        `on_cancel`: dọn dẹp chạy khi task bị hủy, kể cả khi bị hủy trước lần chạy đầu tiên (lúc đó
        thân `work` không bao giờ chạy nên không tự dọn được). Phải idempotent.
        """
        task = asyncio.get_running_loop().create_task(work, name=name)
        self._tasks.add(task)
        if on_cancel is not None:
            self._on_cancel[task] = on_cancel
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        cleanup = self._on_cancel.pop(task, None)
        if task.cancelled():
            if cleanup is not None:
                name = f"cleanup-{task.get_name()}"
                self.spawn(self._cleanup(name, cleanup), name=name)
            return
        if task.exception() is not None:
            logger.error("Tác vụ nền %s lỗi", task.get_name(), exc_info=task.exception())

    @staticmethod
    async def _cleanup(name: str, cleanup: Callable[[], Awaitable[None]]) -> None:
        try:
            await cleanup()
        except Exception:
            logger.exception("Dọn dẹp tác vụ bị hủy %s lỗi", name)

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def wait_all(self) -> None:
        """Chờ mọi tác vụ đang chạy (kể cả tác vụ sinh thêm trong lúc chờ). Dùng trong test."""
        while self._tasks:
            batch = list(self._tasks)
            await asyncio.gather(*batch, return_exceptions=True)
            # Callback `_finished` có thể chưa chạy: bỏ thẳng các tác vụ đã xong để không quay vòng.
            self._tasks.difference_update(task for task in batch if task.done())
            await asyncio.sleep(0)

    async def cancel_all(self) -> None:
        """Hủy mọi tác vụ rồi chờ chúng dọn xong (lượt thu thập tự chốt trạng thái khi bị hủy)."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.wait_all()  # các tác vụ dọn dẹp sinh ra từ những tác vụ vừa bị hủy
