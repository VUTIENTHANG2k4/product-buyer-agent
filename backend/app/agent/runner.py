"""Điều phối một lượt chạy agent: planner → executor → guardrail → bảng từ CSDL (docs/05 §1).

`start()` tạo hội thoại/lượt chạy (API trả `run_id` ngay), `stream()` phát sự kiện và lưu từng sự
kiện vào `agent_run.events` để phát lại. Agent chỉ gọi tool và các service; không truy cập CSDL
hay web trực tiếp.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlmodel import Session

from app.agent.executor import LoopOutcome, ToolLoop
from app.agent.guardrail import Evidence, GuardrailOutcome, allowed_write_tools, apply_guardrail
from app.agent.intent import extract_amounts
from app.agent.memory import ConversationContext, to_context
from app.agent.planner import Planner
from app.agent.prompts import load_prompt
from app.agent.schemas import (
    AnyEvent,
    ClarificationEvent,
    ErrorEvent,
    FinalEvent,
    PlanEvent,
    ToolStartEvent,
)
from app.agent.tools import ToolContext, build_tools
from app.config import Settings
from app.db.models import utc_now
from app.domain.dto import QueryIntent
from app.domain.enums import AgentRunStatus
from app.domain.errors import LlmUnavailable
from app.services.catalog_service import CatalogService
from app.services.conversation_service import ConversationService, RunStart

logger = logging.getLogger(__name__)

T = TypeVar("T")
STEP_LIMIT_NOTE: Final = "\n\n_(Đã đạt giới hạn số bước; kết quả dựa trên dữ liệu đã thu thập.)_"
HALLUCINATION_MESSAGE: Final = (
    "Tôi không tìm được sản phẩm phù hợp trong dữ liệu hiện có. Bạn thử đổi điều kiện nhé."
)
STEP_LIMIT_MESSAGE: Final = (
    "Tôi chưa xử lý xong yêu cầu trong số bước cho phép. Bạn thử hỏi cụ thể hơn."
)

Reply = tuple[str, dict[str, object] | None]


@dataclass(frozen=True)
class RunHandle:
    run_id: uuid.UUID
    conversation_id: int
    context: ConversationContext


@dataclass(frozen=True)
class Finish:
    """Thông tin chốt lượt, đi kèm sự kiện cuối cùng của lượt."""

    status: AgentRunStatus
    tool_calls: int = 0
    reply: Reply | None = None


class AgentRunner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        *,
        planner_model: BaseChatModel,
        executor_model: BaseChatModel,
        now: Callable[[], datetime] = utc_now,
        clock: Callable[[], float] = time.perf_counter,
        observer: Callable[[GuardrailOutcome], None] | None = None,
    ) -> None:
        # `observer` nhận kết quả guardrail của mỗi lượt (eval đo hallucination trước khi lọc).
        self.observer = observer
        self._session_factory = session_factory
        self._settings = settings
        self._now = now
        self._clock = clock
        self._planner = Planner(planner_model)
        self._executor_model = executor_model
        self._tools = build_tools(ToolContext(session_factory, settings, now))

    # ---- vòng đời ----
    async def start(self, message: str, conversation_id: int | None = None) -> RunHandle:
        """Tạo (hoặc dùng lại) hội thoại, ghi tin nhắn người dùng và tạo lượt chạy `running`."""

        def begin(session: Session) -> RunStart:
            service = ConversationService(session, now=self._now)
            service.fail_stale_runs()  # dọn lượt kẹt `running` của tiến trình đã chết
            return service.start_run(message, conversation_id)

        started = await self._db(begin)
        return RunHandle(started.run_id, started.conversation_id, to_context(started.snapshot))

    async def run(
        self, message: str, conversation_id: int | None = None
    ) -> AsyncIterator[AnyEvent]:
        """`start` rồi `stream` (tiện cho test, CLI và eval)."""
        handle = await self.start(message, conversation_id)
        async for event in self.stream(handle, message.strip()):
            yield event

    async def stream(self, handle: RunHandle, message: str) -> AsyncIterator[AnyEvent]:
        """Phát sự kiện của một lượt; mỗi sự kiện được lưu trước khi phát. Luôn chốt lượt."""
        started = self._clock()
        tool_calls = 0
        closed = False
        try:
            async for event, done in self._pipeline(handle, message):
                await self._record(handle, event)
                if isinstance(event, ToolStartEvent):
                    tool_calls += 1
                if done is not None:
                    # Chốt lượt TRƯỚC khi phát sự kiện cuối: client thấy `final` rồi gửi lượt kế
                    # ngay, hoặc dừng đọc luồng, cũng không làm mất tin nhắn/bảng đã lưu.
                    # Đánh dấu đã chốt trước khi chờ: bị hủy giữa lúc chờ thì việc chốt (được
                    # shield) vẫn chạy tiếp, `finally` không chốt lần hai đè trạng thái.
                    closed = True
                    await self._close(handle, done, started)
                yield event
        except LlmUnavailable as error:
            event = ErrorEvent(code=error.code, message=error.message)
            await self._record(handle, event)
            closed = True
            await self._close(handle, Finish(AgentRunStatus.failed, tool_calls), started)
            yield event
        except Exception:
            logger.exception("Lượt chạy agent %s lỗi", handle.run_id)
            event = ErrorEvent(code="INTERNAL_ERROR", message="Đã xảy ra lỗi, vui lòng thử lại")
            await self._record(handle, event)
            closed = True
            await self._close(handle, Finish(AgentRunStatus.failed, tool_calls), started)
            yield event
        finally:
            if not closed:  # bị hủy / consumer đóng luồng giữa chừng
                await self._close(handle, Finish(AgentRunStatus.failed, tool_calls), started)

    async def _close(self, handle: RunHandle, finish: Finish, started: float) -> None:
        """Chốt lượt (không bị hủy giữa chừng); lỗi lưu chỉ ghi log để không đè lỗi gốc."""
        latency = round((self._clock() - started) * 1000)
        try:
            await asyncio.shield(self._finish(handle, finish, latency))
        except Exception:
            logger.exception("Không chốt được lượt chạy agent %s", handle.run_id)

    # ---- các bước ----
    async def _pipeline(
        self, handle: RunHandle, message: str
    ) -> AsyncIterator[tuple[AnyEvent, Finish | None]]:
        """Phát (sự kiện, thông tin chốt lượt). Thông tin chốt chỉ có ở sự kiện cuối."""
        intent = await self._planner.plan(message, handle.context.user_messages)
        await self._db(
            lambda s: ConversationService(s, now=self._now).set_intent(
                handle.run_id, intent.model_dump(mode="json")
            )
        )
        yield PlanEvent(intent=intent, steps=intent.plan_steps), None

        if intent.needs_clarification:
            question = intent.clarification_question or ""
            yield (
                ClarificationEvent(question=question),
                Finish(AgentRunStatus.needs_clarification, reply=(question, None)),
            )
            return

        messages: list[BaseMessage] = [
            SystemMessage(content=load_prompt("executor")),
            *handle.context.history,
            HumanMessage(content=_user_turn(message, intent, handle.context)),
        ]
        # Sản phẩm trong bảng lượt trước đã hiển thị cho người dùng nên được phép nhắc lại
        # ("báo tôi khi máy đầu tiên xuống dưới 25 triệu").
        previous = Evidence(product_ids={pid for pid, _ in handle.context.last_results})
        outcome = LoopOutcome(evidence=previous)
        amounts = extract_amounts(message) | {
            value for value in (intent.price_min, intent.price_max) if value
        }
        loop = ToolLoop(
            self._executor_model,
            self._tools,
            max_steps=self._settings.agent_max_steps,
            allowed_writes=allowed_write_tools(message),
            user_amounts=amounts,
            clock=self._clock,
        )
        async for tool_event in loop.run(messages, outcome):
            yield tool_event, None

        failed = Finish(AgentRunStatus.failed, tool_calls=outcome.tool_calls)
        if outcome.answer is None:
            if outcome.stop_reason == "step_limit":
                yield ErrorEvent(code="AGENT_STEP_LIMIT", message=STEP_LIMIT_MESSAGE), failed
            else:
                yield (
                    ErrorEvent(code="INTERNAL_ERROR", message="Không tạo được câu trả lời"),
                    failed,
                )
            return

        verdict = apply_guardrail(outcome.answer, outcome.evidence, user_amounts=amounts)
        if self.observer is not None:
            self.observer(verdict)
        if verdict.dropped_product_ids or verdict.dropped_live_urls or verdict.dropped_text_urls:
            logger.warning(
                "Run %s: guardrail loại id %s, link %s và link trong văn bản %s không có trong "
                "kết quả tool",
                handle.run_id,
                verdict.dropped_product_ids,
                verdict.dropped_live_urls,
                verdict.dropped_text_urls,
            )
        if verdict.price_warnings:
            logger.warning("Số tiền trong câu trả lời lệch giá CSDL: %s", verdict.price_warnings)
        if verdict.hallucinated:
            yield ErrorEvent(code="AGENT_HALLUCINATION", message=HALLUCINATION_MESSAGE), failed
            return

        answer = verdict.answer
        rows = await self._db(lambda s: CatalogService(s, now=self._now).rows(answer.product_ids))
        as_of = min((row.offers[0].scraped_at for row in rows if row.offers), default=None)
        text = answer.text + (STEP_LIMIT_NOTE if outcome.stop_reason == "step_limit" else "")
        final = FinalEvent(
            text=text,
            table=rows,
            live_items=answer.live_items,
            suggestions=answer.follow_up_suggestions,
            data_as_of=as_of,
        )
        payload: dict[str, object] = {"product_ids": [row.product_id for row in rows]}
        yield (
            final,
            Finish(AgentRunStatus.succeeded, outcome.tool_calls, reply=(text, payload)),
        )

    # ---- lưu trữ ----
    async def _db(self, work: Callable[[Session], T]) -> T:
        """Chạy `work` trong luồng riêng với session mới và commit khi xong."""

        def job() -> T:
            with self._session_factory() as session:
                result = work(session)
                session.commit()
                return result

        return await asyncio.to_thread(job)

    async def _record(self, handle: RunHandle, event: AnyEvent) -> None:
        await self._db(
            lambda s: ConversationService(s, now=self._now).append_event(
                handle.run_id, event.record()
            )
        )

    async def _finish(self, handle: RunHandle, finish: Finish, latency_ms: int) -> None:
        await self._db(
            lambda s: ConversationService(s, now=self._now).finish_run(
                handle.run_id,
                finish.status,
                tool_calls=finish.tool_calls,
                latency_ms=latency_ms,
                reply=finish.reply,
            )
        )


def _user_turn(message: str, intent: QueryIntent, context: ConversationContext) -> str:
    parts: list[str] = []
    last = context.describe_last_results()
    if last:
        parts.append(last)
    parts.append(
        "Ý định đã phân tích: "
        + intent.model_dump_json(exclude_defaults=True, exclude={"plan_steps"})
    )
    parts.append(f"Yêu cầu của người dùng: {message}")
    return "\n\n".join(parts)
