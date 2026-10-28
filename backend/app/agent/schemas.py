"""Kiểu dữ liệu của agent: câu trả lời cuối và các sự kiện tiến trình (docs/05 §4, §6)."""

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.catalog import ProductRow
from app.domain.dto import QueryIntent

MAX_SUGGESTIONS = 3


class LiveItem(BaseModel):
    """Một kết quả tìm trực tiếp tầng 2 (chưa chuẩn hóa)."""

    site: str
    title: str
    price: int | None = None
    url: str
    scraped_at: str | None = None


class FinalAnswer(BaseModel):
    """Lượt cuối của executor. `product_ids` chỉ gồm id đã xuất hiện trong kết quả tool."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="Short Vietnamese markdown answer for the user.")
    product_ids: list[int] = Field(
        default_factory=list, description="Product ids to show in the table, in display order."
    )
    live_items: list[LiveItem] = Field(
        default_factory=list, description="Tier-2 live search items taken from tool results."
    )
    follow_up_suggestions: list[str] = Field(
        default_factory=list, description="At most 3 short follow-up actions."
    )

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        """Câu trả lời rỗng hoặc chỉ có khoảng trắng bị từ chối để LLM viết lại (BUG-M6-14)."""
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


def _without_nul(value: Any) -> Any:
    """Bỏ ký tự NUL (U+0000; JSONB của PostgreSQL không lưu được) khỏi mọi chuỗi lồng nhau."""
    if isinstance(value, str):
        return value.replace(chr(0), "")
    if isinstance(value, list):
        return [_without_nul(item) for item in value]
    if isinstance(value, dict):
        return {key: _without_nul(item) for key, item in value.items()}
    return value


class AgentEvent(BaseModel):
    """Gốc của sự kiện SSE. `record()` là dạng lưu trong `agent_run.events` và phát cho client."""

    name: ClassVar[str]

    def record(self) -> dict[str, Any]:
        return {"event": self.name, "data": _without_nul(self.model_dump(mode="json"))}


class PlanEvent(AgentEvent):
    name: ClassVar[str] = "plan"
    intent: QueryIntent
    steps: list[str]


class ClarificationEvent(AgentEvent):
    name: ClassVar[str] = "clarification"
    question: str


class ToolStartEvent(AgentEvent):
    name: ClassVar[str] = "tool_start"
    call_id: str
    tool: str
    args_summary: str


class ToolEndEvent(AgentEvent):
    name: ClassVar[str] = "tool_end"
    call_id: str
    tool: str
    ok: bool
    summary: str
    duration_ms: int


class FinalEvent(AgentEvent):
    name: ClassVar[str] = "final"
    text: str
    table: list[ProductRow]
    live_items: list[LiveItem]
    suggestions: list[str]
    data_as_of: datetime | None


class ErrorEvent(AgentEvent):
    name: ClassVar[str] = "error"
    code: str
    message: str


AnyEvent = PlanEvent | ClarificationEvent | ToolStartEvent | ToolEndEvent | FinalEvent | ErrorEvent
