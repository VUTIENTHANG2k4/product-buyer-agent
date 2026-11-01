"""Repository cho `Conversation` và `Message`."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from app.db.models import Conversation, Message
from app.db.repositories.ids import fits_int4
from app.domain.clock import utc_now
from app.domain.enums import MessageRole


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, title: str | None = None, *, now: datetime | None = None) -> Conversation:
        conversation = Conversation(title=title, created_at=now or utc_now())
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def get(self, conversation_id: int) -> Conversation | None:
        return (
            self._session.get(Conversation, conversation_id) if fits_int4(conversation_id) else None
        )

    def list_recent(self, *, limit: int = 20) -> list[Conversation]:
        statement = (
            select(Conversation)
            .order_by(col(Conversation.created_at).desc(), col(Conversation.id).desc())
            .limit(limit)
        )
        return list(self._session.exec(statement))

    def set_title(self, conversation: Conversation, title: str) -> Conversation:
        conversation.title = title
        self._session.flush()
        return conversation

    def delete(self, conversation: Conversation) -> None:
        """Xóa hội thoại; tin nhắn và lượt chạy agent bị xóa theo (`ON DELETE CASCADE`)."""
        self._session.delete(conversation)
        self._session.flush()
        self._session.expire_all()


class MessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        conversation_id: int,
        role: MessageRole,
        content: str,
        *,
        payload: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            payload=None if payload is None else dict(payload),
            created_at=now or utc_now(),
        )
        self._session.add(message)
        self._session.flush()
        return message

    def list_for_conversation(
        self, conversation_id: int, *, limit: int | None = None
    ) -> list[Message]:
        """Tin nhắn theo thứ tự thời gian; có `limit` thì lấy `limit` tin cuối (vẫn cũ → mới)."""
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(col(Message.created_at).desc(), col(Message.id).desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(reversed(self._session.exec(statement).all()))

    def latest_assistant_payload(self, conversation_id: int) -> dict[str, Any] | None:
        """`payload` của tin nhắn trợ lý gần nhất có payload (danh sách `product_id` có thứ tự)."""
        statement = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.assistant,
                col(Message.payload).is_not(None),
            )
            .order_by(col(Message.created_at).desc(), col(Message.id).desc())
        )
        message = self._session.exec(statement).first()
        return None if message is None else message.payload
