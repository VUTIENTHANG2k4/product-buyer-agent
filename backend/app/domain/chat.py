"""DTO đọc hội thoại và lượt chạy agent (docs/07 §3.2). Không phụ thuộc kiểu sự kiện của agent:
sự kiện là dict `{"event", "data"}` đúng như lưu trong `agent_run.events`."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.enums import AgentRunStatus, MessageRole


class ConversationView(BaseModel):
    conversation_id: int
    title: str | None
    created_at: datetime


class MessageView(BaseModel):
    """Một tin nhắn; `payload` của tin trợ lý chứa `product_ids` của bảng đã hiển thị."""

    message_id: int
    role: MessageRole
    content: str
    payload: dict[str, Any] | None
    created_at: datetime


class RunSnapshot(BaseModel):
    """Trạng thái một lượt chạy cùng toàn bộ sự kiện đã lưu."""

    run_id: uuid.UUID
    conversation_id: int
    status: AgentRunStatus
    intent: dict[str, Any] | None
    events: list[dict[str, Any]]


class EventBatch(BaseModel):
    """Các sự kiện từ một vị trí trở đi, và trạng thái lượt chạy ở cùng thời điểm đọc."""

    status: AgentRunStatus
    events: list[dict[str, Any]]
