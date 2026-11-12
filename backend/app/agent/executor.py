"""Bước 2–3 của agent: vòng lặp gọi tool rồi tổng hợp `FinalAnswer` (docs/05 §1, §5, §6).

Vòng lặp tự viết trên `bind_tools` của LangChain (không dùng `create_agent`) để kiểm soát được
số bước, sự kiện từng tool, chặn tool ghi khi người dùng không yêu cầu, và dừng khi tool lỗi lặp.
`FinalAnswer` được gắn như một "tool" thứ chín: LLM gọi nó khi đã đủ dữ liệu.
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from app.agent.guardrail import (
    READ_ON_REQUEST_TOOLS,
    Evidence,
    check_write_args,
    ground_search_args,
)
from app.agent.schemas import FinalAnswer, ToolEndEvent, ToolStartEvent
from app.agent.tools import WRITE_TOOLS
from app.agent.tools.base import Result, error_result
from app.domain.dto import QueryIntent
from app.domain.errors import LlmUnavailable

logger = logging.getLogger(__name__)

FINAL_TOOL: Final = FinalAnswer.__name__
SEARCH_TOOL: Final = "search_catalog"
COMPARE_TOOL: Final = "compare_products"
MAX_ARGS_SUMMARY: Final = 200
MAX_CALLS_PER_STEP: Final = 5
MAX_WRITE_CALLS: Final = 5  # tool ghi tối đa mỗi lượt
TOOL_FAILURE_LIMIT: Final = 2  # cùng một tool lỗi 2 lần thì dừng (docs/05 §5)
# Trần số lần chạy thật của một tool mỗi lượt. Tìm trực tiếp đi qua Fetcher (độ trễ ≥ 5 s/trang)
# nên gọi lặp làm lượt rất chậm: eval T03 từng gọi 8 lần (78 s). Tool ghi có trần riêng ở trên.
# `search_catalog` rẻ nhưng LLM gọi đi gọi lại khi kết quả rỗng (eval L10: 8 lần, 58 s); 3 lần là
# nhiều nhất một câu hợp lệ cần (eval L07: tìm, nới điều kiện, rồi tìm thêm).
TOOL_CALL_CAPS: Final[Mapping[str, int]] = MappingProxyType(
    {"live_search_other": 2, "search_catalog": 3}
)

# Mã lỗi của lời gọi bị chốt chặn (tool không chạy): báo `skipped` cho giao diện, không phải lỗi.
SKIPPED_REASONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "TOOL_CALL_LIMIT": "đã đủ số lần gọi trong lượt",
        "TOOL_NOT_REQUESTED": "người dùng không hỏi tới",
        "SEARCH_DONE": "đã có kết quả tìm",
        "WRITE_NOT_REQUESTED": "người dùng chưa yêu cầu rõ ràng",
    }
)

# Lời gọi người dùng không cần (khác hết trần `TOOL_CALL_LIMIT`, khi LLM còn thiếu dữ liệu): dừng
# vì chúng thì lời nhắc tổng hợp không nói "chưa lấy được".
UNNEEDED_CALLS: Final = frozenset({"SEARCH_DONE", "TOOL_NOT_REQUESTED", "WRITE_NOT_REQUESTED"})

StopReason = Literal[
    "final", "text_fallback", "step_limit", "tool_failures", "skipped_calls", "search_done"
]

SYNTHESIS_HINTS: Final = {
    # Đã có kết quả tìm và không còn tool nào người dùng cần (X1.12): tổng hợp ngay thay vì hỏi
    # LLM có tool, vì Gemini hay thử tìm lại rồi bị `SEARCH_DONE` chặn, tốn thêm một lượt.
    "search_done": (
        "Đã có kết quả tìm kiếm đủ cho câu hỏi. Hãy tổng hợp FinalAnswer từ kết quả tool ở trên, "
        "không gọi thêm tool. Kết quả ít là bình thường: chỉ nêu những sản phẩm đã tìm được."
    ),
    "text_fallback": "Hãy trả lời bằng FinalAnswer dựa trên kết quả tool ở trên.",
    "step_limit": (
        "Đã hết số bước cho phép. Hãy tổng hợp FinalAnswer từ những kết quả tool đã có, "
        "không gọi thêm tool và không bịa thêm."
    ),
    # Lời gọi bị chốt chặn lặp lại không phải lỗi: đừng để LLM báo "chưa lấy được" thứ người dùng
    # không hỏi (review X1.10).
    "skipped_calls": (
        "Đã đủ dữ liệu cho câu hỏi. Hãy tổng hợp FinalAnswer từ những kết quả tool đã có, "
        "không gọi thêm tool và không nhắc tới các lời gọi đã bị bỏ qua."
    ),
    "tool_failures": (
        "Một tool liên tục lỗi hoặc đã hết số lần gọi cho phép trong lượt. Hãy tổng hợp "
        "FinalAnswer từ những kết quả đã có và nói rõ phần nào chưa lấy được."
    ),
}


@dataclass
class LoopOutcome:
    """Kết quả của vòng lặp, điền dần trong lúc `ToolLoop.run` phát sự kiện."""

    evidence: Evidence = field(default_factory=Evidence)
    answer: FinalAnswer | None = None
    stop_reason: StopReason | None = None
    tool_calls: int = 0
    write_calls: int = 0  # số lần tool ghi thật sự chạy trong lượt (trần `MAX_WRITE_CALLS`)
    calls_by_tool: dict[str, int] = field(default_factory=dict)  # lần chạy thật, theo tên tool
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
        note = " (đã bỏ từ khóa vì không có kết quả)" if result.get("keywords_relaxed") else ""
        return f"Tìm thấy {result.get('total', 0)} sản phẩm{note}"
    if tool == "live_search_other":
        if result.get("reason"):
            return str(result["reason"]).capitalize()
        skipped = len(result.get("sites_skipped", []))
        note = f", bỏ qua {skipped} trang" if skipped else ""
        return (
            f"Tìm trực tiếp: {len(result.get('items', []))} kết quả "
            f"từ {len(result.get('sites_searched', []))} trang{note}"
        )
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
        user_amounts: Collection[int] = frozenset(),
        clock: Callable[[], float] = time.perf_counter,
        run_id: object | None = None,
        intent: QueryIntent | None = None,
        message: str = "",
        hidden_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._tag = "" if run_id is None else f"[run {run_id}] "  # tiền tố log (docs/05 §5)
        self._model = model
        self._tools = {tool.name: tool for tool in tools}
        # Tool ẩn không được đưa cho LLM (X1.10: tool đọc người dùng không hỏi tới), nên LLM không
        # tốn một lượt gọi chúng; gọi tên đoán mò vẫn bị chặn ở `_run_tool`.
        self._all_tools = list(tools)
        self._hidden = hidden_tools
        self._bound = self._bind()
        # Đã có lần `search_catalog` ra ≥ 1 sản phẩm: từ bước LLM sau, không đưa tool tìm nữa
        # (X1.10: eval A04 tìm 3 lần cùng điều kiện, lần nào cũng 1 sản phẩm). Kết quả rỗng vẫn cho
        # tìm lại để nới điều kiện; lời gọi song song cùng bước (chuột và bàn phím) vẫn chạy hết.
        self._search_found = False
        self._search_locked = False
        # Khóa tìm kiếm mà không còn tool nào cần gọi: bước sau tổng hợp thẳng (X1.12).
        self._finish_after_search = False
        self._skips: dict[str, int] = {}  # lời gọi bị bỏ qua theo tool (phần của bộ đếm lỗi)
        self._max_steps = max_steps
        self._allowed_writes = allowed_writes
        self._user_amounts = user_amounts  # số tiền người dùng nêu, để bắt tham số sai thang
        self._clock = clock
        # Ý định + câu người dùng: căn cứ để bỏ điều kiện `search_catalog` họ không nêu (X1.10).
        self._intent = intent
        self._message = message

    def _bind(self) -> Any:
        return self._model.bind_tools(
            [*(tool for tool in self._all_tools if tool.name not in self._hidden), FinalAnswer]
        )

    async def run(
        self, messages: list[BaseMessage], outcome: LoopOutcome
    ) -> AsyncIterator[ToolStartEvent | ToolEndEvent]:
        """Chạy vòng lặp, phát sự kiện tool; `messages` và `outcome` được cập nhật tại chỗ."""
        failures: dict[str, int] = {}
        for step in range(1, self._max_steps + 1):
            if self._finish_after_search:
                outcome.stop_reason = "search_done"
                outcome.answer = await self._synthesize(messages, "search_done")
                return
            reply = await self._ask(self._bound, messages)
            outcome.llm_steps += 1
            _ensure_call_ids(reply, step)  # trước khi vào lịch sử: id AIMessage = id ToolMessage
            messages.append(reply)
            calls = list(reply.tool_calls)
            invalid = list(reply.invalid_tool_calls)
            if not calls and not invalid:
                outcome.stop_reason = "text_fallback"
                outcome.answer = await self._synthesize(messages, "text_fallback")
                return

            for bad in invalid:  # tham số không phải JSON hợp lệ: báo lại để LLM gọi lại
                name = str(bad.get("name") or "unknown")
                logger.warning("%sLLM gọi %s với tham số hỏng", self._tag, name[:40])
                failures[name] = failures.get(name, 0) + 1
                messages.append(
                    _tool_message(
                        {"id": bad["id"], "name": name},
                        error_result(
                            "INVALID_TOOL_CALL",
                            "Tham số tool không phải JSON hợp lệ: "
                            f"{str(bad.get('error') or '')[:200]}. Hãy gọi lại đúng định dạng",
                        ),
                    )
                )

            real = [call for call in calls if call["name"] != FINAL_TOOL]
            for call in real[:MAX_CALLS_PER_STEP]:
                async for event in self._run_tool(call, messages, outcome, failures):
                    yield event
            # Người dùng hỏi so sánh thì có thể cần tìm lần lượt từng máy: không khóa tìm kiếm.
            compare_wanted = COMPARE_TOOL in self._tools and COMPARE_TOOL not in self._hidden
            if self._search_found and not self._search_locked and not compare_wanted:
                self._search_locked = True
                self._hidden = self._hidden | {SEARCH_TOOL}
                self._bound = self._bind()
                self._finish_after_search = self._nothing_left_to_call(real)
            for call in real[MAX_CALLS_PER_STEP:]:  # LLM đòi quá nhiều tool trong một bước
                messages.append(
                    _tool_message(
                        {"id": call["id"], "name": call["name"]},
                        error_result(
                            "TOO_MANY_CALLS",
                            f"Tối đa {MAX_CALLS_PER_STEP} tool mỗi bước; bỏ qua lời gọi này",
                        ),
                    )
                )
            for call in calls:
                if call["name"] != FINAL_TOOL:
                    continue
                if real or invalid:
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
            reached = [name for name, count in failures.items() if count >= TOOL_FAILURE_LIMIT]
            if reached:
                # Dừng như cũ (lỗi và lời gọi bị bỏ qua cùng tính); chỉ khi mọi lần tính vào trần
                # đều là bị bỏ qua thì lời nhắc tổng hợp không nói tới "chưa lấy được".
                only_skips = all(self._skips.get(name, 0) >= failures[name] for name in reached)
                outcome.stop_reason = "skipped_calls" if only_skips else "tool_failures"
                outcome.answer = await self._synthesize(messages, outcome.stop_reason)
                return

        outcome.stop_reason = "step_limit"
        if outcome.evidence.product_ids or outcome.evidence.live_urls or outcome.tool_calls:
            outcome.answer = await self._synthesize(messages, "step_limit")

    def _nothing_left_to_call(self, step_calls: Sequence[Any]) -> bool:
        """Sau khi khóa tìm kiếm, lượt này còn cần tool nào nữa không (X1.12).

        Không còn khi: người dùng không yêu cầu ghi, không hỏi chi tiết/so sánh/lịch sử giá (mọi
        tool đọc theo yêu cầu đều ẩn hoặc không có), ý định là tầng 1 (không cần tìm trực tiếp) và
        bước vừa rồi chỉ gọi `search_catalog` (gọi tool khác thì để LLM tự quyết bước sau).
        """
        if self._allowed_writes:
            return False
        if any(name in self._tools and name not in self._hidden for name in READ_ON_REQUEST_TOOLS):
            return False
        if self._intent is not None and self._intent.tier != 1:
            return False
        return all(call["name"] == SEARCH_TOOL for call in step_calls)

    async def _run_tool(
        self,
        call: Any,
        messages: list[BaseMessage],
        outcome: LoopOutcome,
        failures: dict[str, int],
    ) -> AsyncIterator[ToolStartEvent | ToolEndEvent]:
        name: str = call["name"]
        call_id = str(call["id"])
        args: dict[str, Any] = dict(call.get("args") or {})
        ignored: list[str] = []
        if name == SEARCH_TOOL and self._intent is not None:
            args, ignored = ground_search_args(args, self._intent, self._message)
            if ignored:
                logger.warning(
                    "%sBỏ điều kiện người dùng không nêu khỏi %s: %s", self._tag, name, ignored
                )
        outcome.tool_calls += 1
        yield ToolStartEvent(call_id=call_id, tool=name, args_summary=summarize_args(args))

        started = self._clock()
        tool = self._tools.get(name)
        if tool is None:
            result = error_result("UNKNOWN_TOOL", f"Không có tool {name[:40]}")
        elif name == SEARCH_TOOL and self._search_locked:
            result = error_result(
                "SEARCH_DONE",
                "Đã có kết quả tìm kiếm; hãy trả lời bằng FinalAnswer từ kết quả đó",
            )
        elif name in self._hidden:
            result = error_result(
                "TOOL_NOT_REQUESTED",
                "Người dùng không hỏi tới thao tác này; hãy trả lời từ kết quả đã có",
            )
        elif name in WRITE_TOOLS and name not in self._allowed_writes:
            logger.warning("%sChặn tool ghi %s: người dùng chưa yêu cầu rõ ràng", self._tag, name)
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
        elif name in WRITE_TOOLS and outcome.write_calls >= MAX_WRITE_CALLS:
            # Lệnh bị tiêm qua nội dung web không thể thêm hàng loạt sản phẩm trong một lượt.
            result = error_result(
                "TOO_MANY_WRITES", f"Tối đa {MAX_WRITE_CALLS} thao tác ghi mỗi lượt"
            )
        elif (bad_args := check_write_args(name, args, self._user_amounts)) is not None:
            result = bad_args
        elif name in TOOL_CALL_CAPS and outcome.calls_by_tool.get(name, 0) >= TOOL_CALL_CAPS[name]:
            result = error_result(
                "TOOL_CALL_LIMIT",
                f"Đã gọi {name} đủ số lần cho phép trong lượt; hãy dùng kết quả đã có",
            )
        else:
            if name in WRITE_TOOLS:
                outcome.write_calls += 1
            try:
                result = _as_result(await tool.ainvoke(args))
            except Exception:
                logger.exception("%sTool %s lỗi hệ thống", self._tag, name)
                result = error_result("TOOL_ERROR", "Lỗi hệ thống khi chạy tool")
            if result.get("error") != "VALIDATION_ERROR":  # sai tham số: chưa tới Fetcher
                outcome.calls_by_tool[name] = outcome.calls_by_tool.get(name, 0) + 1

        ok = result.get("ok") is not False
        if ok and name == SEARCH_TOOL and int(result.get("total") or 0) > 0:
            self._search_found = True
        if ok and ignored:  # để LLM biết điều kiện đó không được áp dụng, đừng thêm lại
            result = {**result, "ignored_filters": ignored}
        skipped = SKIPPED_REASONS.get(str(result.get("error")))
        if ok:
            outcome.evidence.add_result(name, result)
        else:
            failures[name] = failures.get(name, 0) + 1
            if result.get("error") in UNNEEDED_CALLS:
                self._skips[name] = self._skips.get(name, 0) + 1
        messages.append(_tool_message({"id": call_id, "name": name}, result))
        yield ToolEndEvent(
            call_id=call_id,
            tool=name,
            ok=ok,
            summary=f"Bỏ qua: {skipped}" if skipped else summarize_result(name, result),
            skipped=skipped is not None,
            duration_ms=max(0, round((self._clock() - started) * 1000)),
        )

    async def _ask(self, runnable: Any, messages: list[BaseMessage]) -> AIMessage:
        try:
            reply = await runnable.ainvoke(messages)
        except Exception as error:
            logger.error(
                "%sExecutor không gọi được LLM: %s: %s",
                self._tag,
                type(error).__name__,
                str(error)[:200],
            )
            raise LlmUnavailable(details={"stage": "executor"}) from error
        if not isinstance(reply, AIMessage):
            raise LlmUnavailable("LLM trả về dữ liệu không hợp lệ", details={"stage": "executor"})
        return reply

    async def _synthesize(
        self, messages: list[BaseMessage], reason: StopReason
    ) -> FinalAnswer | None:
        """Một lần gọi structured output để lấy `FinalAnswer` (không gọi thêm tool)."""
        prompt = [*messages, HumanMessage(content=SYNTHESIS_HINTS[reason])]
        try:
            result = await self._model.with_structured_output(FinalAnswer).ainvoke(prompt)
        except (ValidationError, OutputParserException):
            logger.warning(
                "%sLLM trả FinalAnswer không hợp lệ (%s)", self._tag, reason, exc_info=True
            )
            return None
        except Exception as error:  # lỗi gọi LLM (429, 503, hết hạn…) khác lỗi dữ liệu
            logger.error(
                "%sExecutor không gọi được LLM khi tổng hợp: %s: %s",
                self._tag,
                type(error).__name__,
                str(error)[:200],
            )
            raise LlmUnavailable(details={"stage": "executor"}) from error
        if isinstance(result, FinalAnswer):
            return result
        try:
            return FinalAnswer.model_validate(result)
        except ValidationError:
            logger.warning(
                "%sLLM trả FinalAnswer không hợp lệ (%s)", self._tag, reason, exc_info=True
            )
            return None


def _ensure_call_ids(reply: AIMessage, step: int) -> None:
    """Gán id `call_<bước>_<thứ tự>` cho tool call thiếu id (Gemini hay trả `id=None`). Sửa tại
    chỗ để AIMessage và ToolMessage khớp nhau; id LLM đã đặt (kể cả trùng) được giữ nguyên, còn id
    sinh ra không bao giờ trùng một id có trong phản hồi."""
    calls = [*reply.tool_calls, *reply.invalid_tool_calls]
    taken = {str(call["id"]) for call in calls if call.get("id")}
    for index, call in enumerate(calls, start=1):
        if call.get("id"):
            continue
        candidate = f"call_{step}_{index}"
        while candidate in taken:
            candidate += "_"
        taken.add(candidate)
        call["id"] = candidate


def _tool_message(call: Any, result: Result) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False),
        tool_call_id=str(call["id"]),
        name=str(call["name"]),
    )
