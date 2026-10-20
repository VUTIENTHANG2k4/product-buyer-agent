"""Bước 1 của agent: biến câu hỏi thành `QueryIntent` (docs/05 §1, §4).

Planner gọi LLM với structured output, thử lại một lần khi kết quả không hợp lệ (trường lạ, sai
kiểu, khoảng giá ngược), rồi chạy `postprocess_intent` để sửa các lỗi có luật rõ ràng.
"""

import logging
from collections.abc import Sequence

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.intent import postprocess_intent
from app.agent.prompts import load_prompt
from app.domain.dto import QueryIntent
from app.domain.errors import LlmUnavailable
from app.normalize.specs.gpu_rank import GPU_RANKS

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # lần đầu + 1 lần thử lại (docs/05 §2)
MAX_HISTORY_MESSAGES = 3
MAX_MESSAGE_CHARS = 1000


def render_planner_prompt() -> str:
    """Prompt hệ thống của planner, bảng hạng GPU lấy từ `GPU_RANKS` để không lệch với code."""
    table = "\n".join(
        f"  - {name} = {rank}" for name, rank in sorted(GPU_RANKS.items(), key=lambda x: x[1])
    )
    return load_prompt("planner").replace("{{GPU_RANKS}}", table)


def build_messages(message: str, history: Sequence[str]) -> list[BaseMessage]:
    """System prompt + (các lượt người dùng trước, nếu có) + yêu cầu hiện tại."""
    recent = [text[:MAX_MESSAGE_CHARS] for text in history[-MAX_HISTORY_MESSAGES:]]
    if recent:
        lines = "\n".join(f"- {text}" for text in recent)
        body = f"Các yêu cầu trước của người dùng:\n{lines}\n\nYêu cầu hiện tại:\n{message}"
    else:
        body = message
    return [SystemMessage(content=render_planner_prompt()), HumanMessage(content=body)]


class Planner:
    def __init__(self, model: BaseChatModel) -> None:
        self._structured = model.with_structured_output(QueryIntent)

    async def plan(self, message: str, history: Sequence[str] = ()) -> QueryIntent:
        """`QueryIntent` đã hậu xử lý; hai lần không hợp lệ hoặc LLM lỗi → `LlmUnavailable`."""
        message = message.strip()[:MAX_MESSAGE_CHARS]
        messages = build_messages(message, history)
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = await self._structured.ainvoke(messages)
                intent = (
                    result
                    if isinstance(result, QueryIntent)
                    else QueryIntent.model_validate(result)
                )
                return postprocess_intent(intent, message)
            except (ValueError, OutputParserException) as error:  # gồm pydantic.ValidationError
                last_error = error
                logger.warning("Planner lần %d trả kết quả không hợp lệ: %s", attempt, error)
                messages = [
                    *messages,
                    HumanMessage(
                        content=(
                            "Kết quả trước không hợp lệ: "
                            f"{str(error)[:300]}. Trả lại đúng khung, không thêm trường lạ."
                        )
                    ),
                ]
            except Exception as error:
                raise LlmUnavailable(details={"stage": "planner"}) from error
        raise LlmUnavailable(
            "Planner không trả về ý định hợp lệ", details={"stage": "planner"}
        ) from last_error
