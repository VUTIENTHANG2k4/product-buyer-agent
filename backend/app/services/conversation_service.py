"""Hội thoại và lượt chạy agent: tạo, ghi sự kiện, chốt kết quả (docs/05 §6, docs/07 §3.2).

Agent không truy cập CSDL trực tiếp; mọi việc ghi/đọc hội thoại đi qua lớp này.
"""

import unicodedata
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

from sqlmodel import Session

from app.db.models import AgentRun, utc_now
from app.db.repositories import (
    AgentRunRepository,
    ConversationRepository,
    MessageRepository,
    ProductRepository,
)
from app.domain.chat import ConversationView, EventBatch, MessageView, RunSnapshot
from app.domain.enums import AgentRunStatus, MessageRole
from app.domain.errors import NotFound, RunNotFound, ValidationFailed
from app.services.views import Clock

MAX_MESSAGE_CHARS: Final = 1000
TITLE_CHARS: Final = 60
HISTORY_LIMIT: Final = 6  # số tin nhắn gần nhất đưa cho LLM
MAX_REFERENCED: Final = 20  # số sản phẩm của bảng lượt trước có thể được tham chiếu
MAX_NAME: Final = 80
STALE_RUN_AFTER: Final = timedelta(minutes=15)  # lượt còn `running` quá lâu = tiến trình đã chết
MAX_LISTED_MESSAGES: Final = 500


@dataclass(frozen=True)
class ConversationSnapshot:
    """Ngữ cảnh đọc TRƯỚC khi ghi tin nhắn của lượt mới."""

    messages: list[tuple[MessageRole, str]] = field(default_factory=list)
    last_results: list[tuple[int, str]] = field(
        default_factory=list
    )  # (product_id, tên) theo thứ tự


@dataclass(frozen=True)
class RunStart:
    run_id: uuid.UUID
    conversation_id: int
    snapshot: ConversationSnapshot


def _visible(text: str) -> bool:
    """Có ít nhất một ký tự nhìn thấy được (không phải khoảng trắng hay ký tự định dạng vô hình)."""
    return any(not ch.isspace() and unicodedata.category(ch) != "Cf" for ch in text)


class ConversationService:
    def __init__(self, session: Session, *, now: Clock = utc_now) -> None:
        self._now = now
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._runs = AgentRunRepository(session)
        self._products = ProductRepository(session)

    def start_run(self, message: str, conversation_id: int | None = None) -> RunStart:
        """Tạo (hoặc dùng lại) hội thoại, ghi tin nhắn người dùng và tạo lượt chạy `running`."""
        text = message.strip()
        if not 1 <= len(text) <= MAX_MESSAGE_CHARS or chr(0) in text or not _visible(text):
            raise ValidationFailed(
                f"Tin nhắn phải dài 1–{MAX_MESSAGE_CHARS} ký tự, không chứa NUL, "
                "không chỉ gồm ký tự vô hình"
            )
        moment = self._now()
        if conversation_id is None:
            conversation = self._conversations.create(text[:TITLE_CHARS], now=moment)
        else:
            found = self._conversations.get(conversation_id)
            if found is None:
                raise NotFound("Không tìm thấy hội thoại", details={"id": conversation_id})
            conversation = found
        if conversation.id is None:  # pragma: no cover - flush luôn gán id
            raise RuntimeError("conversation has no id")
        snapshot = self._snapshot(conversation.id)
        self._messages.add(conversation.id, MessageRole.user, text, now=moment)
        run = self._runs.create(conversation.id, now=moment)
        return RunStart(run.id, conversation.id, snapshot)

    def set_intent(self, run_id: uuid.UUID, intent: Mapping[str, Any]) -> None:
        self._runs.set_intent(self._require_run(run_id), intent)

    def append_event(self, run_id: uuid.UUID, event: Mapping[str, Any]) -> None:
        self._runs.append_event(self._require_run(run_id), event)

    def finish_run(
        self,
        run_id: uuid.UUID,
        status: AgentRunStatus,
        *,
        tool_calls: int,
        latency_ms: int,
        reply: tuple[str, Mapping[str, Any] | None] | None = None,
    ) -> None:
        """Chốt lượt chạy; `reply` (nội dung, payload) được lưu thành tin nhắn của trợ lý."""
        run = self._require_run(run_id)
        self._runs.finish(run, status, tool_calls=tool_calls, latency_ms=max(0, latency_ms))
        if reply is not None:
            content, payload = reply
            self._messages.add(
                run.conversation_id,
                MessageRole.assistant,
                content,
                payload=payload,
                now=self._now(),
            )

    def fail_stale_runs(self, older_than: timedelta = STALE_RUN_AFTER) -> int:
        """Lượt còn `running` quá `older_than` coi như đã chết giữa chừng: đổi sang `failed`."""
        return self._runs.fail_stale(self._now() - older_than)

    def get_run(self, run_id: uuid.UUID) -> RunSnapshot:
        run = self._require_run(run_id)
        return RunSnapshot(
            run_id=run.id,
            conversation_id=run.conversation_id,
            status=run.status,
            intent=run.intent,
            events=list(run.events),
        )

    def events_since(self, run_id: uuid.UUID, after: int) -> EventBatch:
        """Sự kiện từ vị trí `after` (0 = từ đầu) và trạng thái lượt, đọc cùng một lần.

        Lượt còn `running` quá `STALE_RUN_AFTER` được báo là `failed` (tiến trình đã chết), để
        luồng SSE đóng thay vì chờ mãi.
        """
        run = self._require_run(run_id)
        status = run.status
        if status is AgentRunStatus.running and run.created_at < self._now() - STALE_RUN_AFTER:
            status = AgentRunStatus.failed
        return EventBatch(status=status, events=list(run.events[max(0, after) :]))

    def list_conversations(self, limit: int = 20) -> list[ConversationView]:
        """Hội thoại gần nhất trước."""
        return [
            ConversationView(
                conversation_id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
            )
            for conversation in self._conversations.list_recent(limit=limit)
            if conversation.id is not None
        ]

    def list_messages(
        self, conversation_id: int, limit: int = MAX_LISTED_MESSAGES
    ) -> list[MessageView]:
        """Tin nhắn của hội thoại, cũ → mới (tối đa `limit` tin cuối)."""
        if self._conversations.get(conversation_id) is None:
            raise NotFound("Không tìm thấy hội thoại", details={"id": conversation_id})
        return [
            MessageView(
                message_id=message.id,
                role=message.role,
                content=message.content,
                payload=message.payload,
                created_at=message.created_at,
            )
            for message in self._messages.list_for_conversation(conversation_id, limit=limit)
            if message.id is not None
        ]

    def _require_run(self, run_id: uuid.UUID) -> AgentRun:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(details={"run_id": str(run_id)})
        return run

    def _snapshot(self, conversation_id: int) -> ConversationSnapshot:
        messages = self._messages.list_for_conversation(conversation_id, limit=HISTORY_LIMIT)
        payload = self._messages.latest_assistant_payload(conversation_id)
        raw_ids = payload.get("product_ids", []) if payload else []
        ids = [pid for pid in raw_ids if isinstance(pid, int)][:MAX_REFERENCED]
        names = {p.id: p.canonical_name for p in self._products.get_many(ids)}
        return ConversationSnapshot(
            messages=[(m.role, m.content) for m in messages],
            last_results=[
                (pid, " ".join(names[pid].split())[:MAX_NAME]) for pid in ids if pid in names
            ],
        )


def read_run_events(factory: Callable[[], Session], run_id: uuid.UUID, after: int) -> EventBatch:
    """Đọc sự kiện của một lượt bằng session ngắn hạn (để theo dõi lượt đang chạy qua SSE)."""
    with factory() as session:
        return ConversationService(session).events_since(run_id, after)


def require_run(factory: Callable[[], Session], run_id: uuid.UUID) -> RunSnapshot:
    """Lượt chạy `run_id` (`RunNotFound` nếu không có), đọc bằng session ngắn hạn."""
    with factory() as session:
        return ConversationService(session).get_run(run_id)
