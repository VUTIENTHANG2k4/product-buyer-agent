"""Repository cho `AgentRun`: lưu sự kiện SSE để phát lại và debug."""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from app.db.models import AgentRun, utc_now
from app.domain.enums import AgentRunStatus


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

    def list_for_conversation(self, conversation_id: int) -> list[AgentRun]:
        """Các lượt chạy của hội thoại, cũ nhất trước."""
        statement = (
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_id)
            .order_by(col(AgentRun.created_at), col(AgentRun.id))
        )
        return list(self._session.exec(statement))
