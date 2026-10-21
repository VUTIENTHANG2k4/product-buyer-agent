"""Theo dõi sự kiện của một lượt chạy agent để phát qua SSE (docs/07 §3.2, docs/05 §6).

Mọi sự kiện được `AgentRunner` lưu vào `agent_run.events` trước khi phát, nên luồng SSE chỉ đọc lại
từ CSDL: cùng một đường cho lượt đang chạy (thăm dò) và lượt đã xong (phát lại), không cần kênh
trong bộ nhớ, và kết nối lại không mất sự kiện.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Final

from app.domain.chat import EventBatch
from app.domain.enums import AgentRunStatus

POLL_INTERVAL_S: Final = 0.25
# Sau các sự kiện này lượt không phát thêm gì (`AgentRunner` chốt lượt ngay sau đó).
TERMINAL_EVENTS: Final = frozenset({"final", "error", "clarification"})


async def follow_events(
    read: Callable[[int], EventBatch],
    after: int = 0,
    *,
    interval: float = POLL_INTERVAL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    """Phát `(vị trí, sự kiện)` từ vị trí `after`, đợi sự kiện mới cho tới khi lượt kết thúc.

    `read(vị trí)` chạy trong luồng riêng (truy cập CSDL đồng bộ). Dừng sau sự kiện cuối
    (`final`/`error`/`clarification`), hoặc khi lượt đã đóng mà không còn sự kiện nào mới (lượt bị
    hủy hoặc đánh `failed` vì kẹt).
    """
    position = max(0, after)
    while True:
        batch = await asyncio.to_thread(read, position)
        for record in batch.events:
            yield position, record
            position += 1
            if record.get("event") in TERMINAL_EVENTS:
                return
        if batch.status is not AgentRunStatus.running and not batch.events:
            return
        await sleep(interval)


async def drain(stream: AsyncIterator[Any]) -> None:
    """Chạy hết một luồng sự kiện của runner (tác vụ nền; sự kiện đã được runner lưu)."""
    async for _ in stream:
        pass
