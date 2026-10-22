"""Model chat giả theo kịch bản cho test đơn vị (docs/05 §2; `LLM_PROVIDER=fake` dùng `fake_llm`).

`ScriptedChatModel` phát lần lượt các phản hồi định sẵn: văn bản, `AIMessage` kèm tool call, hoặc
đối tượng có cấu trúc cho `with_structured_output`. Hết kịch bản thì ném `ScriptExhausted` để
test thấy ngay agent gọi LLM nhiều hơn dự kiến.
"""

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field


class ScriptExhausted(RuntimeError):
    """Agent gọi LLM nhiều lần hơn số phản hồi trong kịch bản."""


def tool_call_message(name: str, args: dict[str, Any], call_id: str = "call_1") -> AIMessage:
    """`AIMessage` rỗng nội dung, chứa đúng một tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class ScriptedChatModel(BaseChatModel):
    """Phát `script[0]`, `script[1]`… cho mỗi lần gọi (kể cả `with_structured_output`).

    Phần tử kịch bản: `str` / `AIMessage` (phản hồi thường), `BaseModel` / `dict` (đầu ra có cấu
    trúc; khi gọi thường thì được tuần tự hóa JSON), hoặc `Exception` (được ném ra).
    """

    script: list[Any] = Field(default_factory=list)
    cursor: int = 0
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def _next(self) -> Any:
        if self.cursor >= len(self.script):
            raise ScriptExhausted(f"kịch bản chỉ có {len(self.script)} phản hồi")
        item = self.script[self.cursor]
        self.cursor += 1
        if isinstance(item, Exception):
            raise item
        return item

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        item = self._next()
        if isinstance(item, AIMessage):
            message = item
        elif isinstance(item, BaseModel):
            message = AIMessage(content=item.model_dump_json())
        elif isinstance(item, dict):
            message = AIMessage(content=json.dumps(item, ensure_ascii=False))
        else:
            message = AIMessage(content=str(item))
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        """Ghi tên tool được gắn; trả về chính model để cả hai dùng chung con trỏ kịch bản."""
        for tool in tools:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", None) or str(tool)
            if name not in self.bound_tool_names:
                self.bound_tool_names.append(name)
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        """Trả phần tử kịch bản kế tiếp đã đổi sang `schema` (lớp Pydantic) hoặc dict."""

        def parse(messages: Any) -> Any:
            self.calls.append(list(messages) if isinstance(messages, list) else [messages])
            item = self._next()
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                if isinstance(item, schema):
                    return item
                if isinstance(item, dict):
                    return schema.model_validate(item)
                text = item.content if isinstance(item, AIMessage) else str(item)
                return schema.model_validate_json(str(text))
            return item.model_dump() if isinstance(item, BaseModel) else item

        return RunnableLambda(parse)
