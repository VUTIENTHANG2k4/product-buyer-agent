"""Repository cho `AgentRun`: lưu sự kiện SSE để phát lại và debug."""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import cast, func, update
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlmodel import Session, col, select

from app.db.models import AgentRun
from app.domain.clock import utc_now
from app.domain.enums import AgentRunStatus

_MAX_POSITION = 2**31 - 1  # giới hạn số nguyên của jsonpath


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        conversation_id: int,
        *,
        run_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=run_id or uuid.uuid4(),
            conversation_id=conversation_id,
            created_at=now or utc_now(),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: uuid.UUID) -> AgentRun | None:
        return self._session.get(AgentRun, run_id)

    def exists(self, run_id: uuid.UUID) -> bool:
        """Có lượt `run_id` không; chỉ đọc khóa chính (không tải cột `events` lớn)."""
        found = self._session.execute(select(col(AgentRun.id)).where(col(AgentRun.id) == run_id))
        return found.first() is not None

    def events_after(
        self, run_id: uuid.UUID, after: int
    ) -> tuple[AgentRunStatus, datetime, list[Any]] | None:
        """(trạng thái, `created_at`, sự kiện từ vị trí `after`) của lượt, hoặc `None` nếu không có.

        Cắt mảng JSONB ngay trong SQL (`jsonb_path_query_array`) nên mỗi nhịp theo dõi SSE chỉ tải
        phần đuôi chưa gửi, không tải cả cột `events`. `after` âm coi như 0.
        """
        start = min(max(0, int(after)), _MAX_POSITION)  # vị trí quá lớn: jsonpath tràn số nguyên
        tail = func.jsonb_path_query_array(
            col(AgentRun.events), cast(f"$[{start} to last]", JSONPATH)
        )
        row = self._session.execute(
            select(col(AgentRun.status), col(AgentRun.created_at), tail).where(
                col(AgentRun.id) == run_id
            )
        ).first()
        if row is None:
            return None
        status, created_at, events = row
        return status, created_at, list(events or [])

    def append_event(self, run: AgentRun, event: Mapping[str, Any]) -> AgentRun:
        """Thêm một sự kiện vào cuối `events` (gán lại cả list, JSONB không theo dõi)."""
        run.events = [*run.events, dict(event)]
        self._session.flush()
        return run

    def set_intent(self, run: AgentRun, intent: Mapping[str, Any]) -> AgentRun:
        run.intent = dict(intent)
        self._session.flush()
        return run

    def finish(
        self,
        run: AgentRun,
        status: AgentRunStatus,
        *,
        tool_calls: int | None = None,
        latency_ms: int | None = None,
    ) -> AgentRun:
        """Chốt trạng thái cuối; `tool_calls` và `latency_ms` (ms) chỉ đặt khi được truyền."""
        run.status = status
        if tool_calls is not None:
            run.tool_calls = tool_calls
        if latency_ms is not None:
            run.latency_ms = latency_ms
        self._session.flush()
        return run

    def fail_stale(self, before: datetime) -> int:
        """Đánh `failed` các lượt còn `running` tạo trước `before` (tiến trình đã chết giữa lượt
        hoặc không chốt được lượt); trả số lượt vừa đổi."""
        statement = (
            update(AgentRun)
            .where(
                col(AgentRun.status) == AgentRunStatus.running,
                col(AgentRun.created_at) < before,
            )
            .values(status=AgentRunStatus.failed)
            .execution_options(synchronize_session="fetch")
        )
        result = self._session.exec(statement)
        self._session.flush()
        return int(result.rowcount)

    def list_for_conversation(self, conversation_id: int) -> list[AgentRun]:
        """Các lượt chạy của hội thoại, cũ nhất trước."""
        statement = (
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_id)
            .order_by(col(AgentRun.created_at), col(AgentRun.id))
        )
        return list(self._session.exec(statement))
