"""Bước 2–3 của agent: vòng lặp gọi tool rồi tổng hợp `FinalAnswer` (docs/05 §1, §5, §6).

Vòng lặp tự viết trên `bind_tools` của LangChain (không dùng `create_agent`) để kiểm soát được
số bước, sự kiện từng tool, chặn tool ghi khi người dùng không yêu cầu, và dừng khi tool lỗi lặp.
`FinalAnswer` được gắn như một "tool" thứ chín: LLM gọi nó khi đã đủ dữ liệu.
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from app.agent.guardrail import Evidence
from app.agent.schemas import FinalAnswer, ToolEndEvent, ToolStartEvent
from app.agent.tools import WRITE_TOOLS
from app.agent.tools.base import Result, error_result
from app.domain.errors import LlmUnavailable

logger = logging.getLogger(__name__)

FINAL_TOOL: Final = FinalAnswer.__name__
MAX_ARGS_SUMMARY: Final = 200
MAX_CALLS_PER_STEP: Final = 5
TOOL_FAILURE_LIMIT: Final = 2  # cùng một tool lỗi 2 lần thì dừng (docs/05 §5)

StopReason = Literal["final", "text_fallback", "step_limit", "tool_failures"]

_SYNTHESIS_HINTS: Final = {
    "text_fallback": "Hãy trả lời bằng FinalAnswer dựa trên kết quả tool ở trên.",
    "step_limit": (
        "Đã hết số bước cho phép. Hãy tổng hợp FinalAnswer từ những kết quả tool đã có, "
        "không gọi thêm tool và không bịa thêm."
    ),
    "tool_failures": (
        "Một tool liên tục lỗi. Hãy tổng hợp FinalAnswer từ những kết quả đã có và nói rõ phần "
        "nào chưa lấy được."
    ),
}


@dataclass
class LoopOutcome:
    """Kết quả của vòng lặp, điền dần trong lúc `ToolLoop.run` phát sự kiện."""

    evidence: Evidence = field(default_factory=Evidence)
    answer: FinalAnswer | None = None
    stop_reason: StopReason | None = None
    tool_calls: int = 0
    llm_steps: int = 0


def summarize_args(args: dict[str, Any]) -> str:
    """Tóm tắt tham số tool cho sự kiện `tool_start` ("category=laptop, price_max=30000000")."""
    parts: list[str] = []
    for key, value in args.items():
        shown = (
            value
            if isinstance(value, str | int | float | bool)
            else json.dumps(value, ensure_ascii=False)
        )
        parts.append(f"{key}={shown}")
    text = ", ".join(parts)
    return text if len(text) <= MAX_ARGS_SUMMARY else text[: MAX_ARGS_SUMMARY - 1] + "…"


def summarize_result(tool: str, result: Result) -> str:
    """Một dòng tiếng Việt cho sự kiện `tool_end`."""
    if result.get("ok") is False:
        return str(result.get("message", "Tool lỗi"))
    if tool == "search_catalog":
        return f"Tìm thấy {result.get('total', 0)} sản phẩm"
    if tool == "live_search_other":
        return str(result["reason"]).capitalize() if result.get("reason") else "Đã tìm trực tiếp"
    if tool == "compare_products":
        return f"So sánh {len(result.get('products', []))} sản phẩm"
    if tool == "get_product_detail":
        return f"Chi tiết: {result.get('name', 'sản phẩm')}"
    if tool == "get_price_history":
        return f"Lịch sử giá {result.get('days')} ngày ({len(result.get('series', []))} trang)"
    if tool == "add_to_shopping_list":
        return f"Đã thêm vào danh sách {result.get('list_name', '')}".strip()
    if tool == "create_price_alert":
        return "Đã đặt cảnh báo giá"
    if tool == "list_alerts":
        return f"{result.get('total', 0)} cảnh báo"
    return "Xong"


def _as_result(raw: Any) -> Result:
    """Kết quả `ainvoke` của tool (dict, hoặc chuỗi JSON khi tham số sai) thành dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return error_result("TOOL_ERROR", raw[:200])
        if isinstance(parsed, dict):
            return parsed
    return error_result("TOOL_ERROR", "Tool trả về dữ liệu không hợp lệ")


class ToolLoop:
    def __init__(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        *,
        max_steps: int,
        allowed_writes: frozenset[str],
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._model = model
        self._tools = {tool.name: tool for tool in tools}
        self._bound = model.bind_tools([*tools, FinalAnswer])
        self._max_steps = max_steps
        self._allowed_writes = allowed_writes
        self._clock = clock

    async def run(
        self, messages: list[BaseMessage], outcome: LoopOutcome
    ) -> AsyncIterator[ToolStartEvent | ToolEndEvent]:
        """Chạy vòng lặp, phát sự kiện tool; `messages` và `outcome` được cập nhật tại chỗ."""
        failures: dict[str, int] = {}
        for _ in range(self._max_steps):
            reply = await self._ask(self._bound, messages)
            outcome.llm_steps += 1
            messages.append(reply)
            calls = list(reply.tool_calls)
            if not calls:
                outcome.stop_reason = "text_fallback"
                outcome.answer = await self._synthesize(messages, "text_fallback")
                return

            real = [call for call in calls if call["name"] != FINAL_TOOL]
            for call in real[:MAX_CALLS_PER_STEP]:
                async for event in self._run_tool(call, messages, outcome, failures):
                    yield event
            for call in real[MAX_CALLS_PER_STEP:]:  # LLM đòi quá nhiều tool trong một bước
                messages.append(
                    _tool_message(
                        {"id": call.get("id") or "call_extra", "name": call["name"]},
                        error_result(
                            "TOO_MANY_CALLS",
                            f"Tối đa {MAX_CALLS_PER_STEP} tool mỗi bước; bỏ qua lời gọi này",
                        ),
                    )
                )
            for call in calls:
                if call["name"] != FINAL_TOOL:
                    continue
                if real:
                    messages.append(
                        _tool_message(
                            call,
                            error_result(
                                "FINAL_TOO_EARLY",
                                "Chưa có kết quả tool; xem kết quả rồi gọi lại FinalAnswer",
                            ),
                        )
                    )
                    continue
                try:
                    outcome.answer = FinalAnswer.model_validate(call["args"])
                except ValidationError as error:
                    messages.append(
                        _tool_message(call, error_result("VALIDATION_ERROR", str(error)[:300]))
                    )
                    continue
                outcome.stop_reason = "final"
                return
            if any(count >= TOOL_FAILURE_LIMIT for count in failures.values()):
                outcome.stop_reason = "tool_failures"
                outcome.answer = await self._synthesize(messages, "tool_failures")
                return

        outcome.stop_reason = "step_limit"
        if outcome.evidence.product_ids or outcome.evidence.live_urls or outcome.tool_calls:
            outcome.answer = await self._synthesize(messages, "step_limit")

    async def _run_tool(
        self,
        call: Any,
        messages: list[BaseMessage],
        outcome: LoopOutcome,
        failures: dict[str, int],
    ) -> AsyncIterator[ToolStartEvent | ToolEndEvent]:
        name: str = call["name"]
        call_id: str = call.get("id") or f"call_{outcome.tool_calls + 1}"
        args: dict[str, Any] = dict(call.get("args") or {})
        outcome.tool_calls += 1
        yield ToolStartEvent(call_id=call_id, tool=name, args_summary=summarize_args(args))

        started = self._clock()
        tool = self._tools.get(name)
        if tool is None:
            result = error_result("UNKNOWN_TOOL", f"Không có tool {name[:40]}")
        elif name in WRITE_TOOLS and name not in self._allowed_writes:
            logger.warning("Chặn tool ghi %s: người dùng chưa yêu cầu rõ ràng", name)
            result = error_result(
                "WRITE_NOT_REQUESTED",
                "Người dùng chưa yêu cầu rõ ràng thao tác này nên không thực hiện",
            )
        elif name in WRITE_TOOLS and args.get("product_id") not in outcome.evidence.product_ids:
            # Tool ghi chỉ tác động lên sản phẩm đã xuất hiện trong kết quả của lượt này hoặc
            # trong bảng lượt trước, không phải id tùy ý (kể cả id do nội dung web gợi ý).
            result = error_result(
                "UNKNOWN_PRODUCT",
                "Sản phẩm chưa xuất hiện trong kết quả; hãy tìm trước rồi mới ghi",
            )
        else:
            try:
                result = _as_result(await tool.ainvoke(args))
            except Exception:
                logger.exception("Tool %s lỗi hệ thống", name)
                result = error_result("TOOL_ERROR", "Lỗi hệ thống khi chạy tool")

        ok = result.get("ok") is not False
        if ok:
            outcome.evidence.add_result(name, result)
        else:
            failures[name] = failures.get(name, 0) + 1
        messages.append(_tool_message({"id": call_id, "name": name}, result))
        yield ToolEndEvent(
            call_id=call_id,
            tool=name,
            ok=ok,
            summary=summarize_result(name, result),
            duration_ms=max(0, round((self._clock() - started) * 1000)),
        )

    async def _ask(self, runnable: Any, messages: list[BaseMessage]) -> AIMessage:
        try:
            reply = await runnable.ainvoke(messages)
        except Exception as error:
            logger.error(
                "Executor không gọi được LLM: %s: %s", type(error).__name__, str(error)[:200]
            )
            raise LlmUnavailable(details={"stage": "executor"}) from error
        if not isinstance(reply, AIMessage):
            raise LlmUnavailable("LLM trả về dữ liệu không hợp lệ", details={"stage": "executor"})
        return reply

    async def _synthesize(
        self, messages: list[BaseMessage], reason: StopReason
    ) -> FinalAnswer | None:
        """Một lần gọi structured output để lấy `FinalAnswer` (không gọi thêm tool)."""
        prompt = [*messages, HumanMessage(content=_SYNTHESIS_HINTS[reason])]
        try:
            result = await self._model.with_structured_output(FinalAnswer).ainvoke(prompt)
        except (ValidationError, OutputParserException):
            logger.warning("LLM trả FinalAnswer không hợp lệ (%s)", reason, exc_info=True)
            return None
        except Exception as error:  # lỗi gọi LLM (429, 503, hết hạn…) khác lỗi dữ liệu
            logger.error(
                "Executor không gọi được LLM khi tổng hợp: %s: %s",
                type(error).__name__,
                str(error)[:200],
            )
            raise LlmUnavailable(details={"stage": "executor"}) from error
        if isinstance(result, FinalAnswer):
            return result
        try:
            return FinalAnswer.model_validate(result)
        except ValidationError:
            logger.warning("LLM trả FinalAnswer không hợp lệ (%s)", reason, exc_info=True)
            return None


def _tool_message(call: Any, result: Result) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False),
        tool_call_id=str(call["id"]),
        name=str(call["name"]),
    )
