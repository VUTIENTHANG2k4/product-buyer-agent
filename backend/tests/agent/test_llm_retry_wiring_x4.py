"""X4: planner, executor (bước có tool, bước tổng hợp) và `AgentRunner` thử lại khi LLM lỗi tạm
thời.

Lỗi giả có `code` như `google.genai.errors.ServerError`; `ScriptedChatModel` ném phần tử kịch bản là
`Exception`. `sleep` được ghi lại, không chờ thật.
"""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from sqlmodel import Session

from app.agent.executor import LoopOutcome, ToolLoop
from app.agent.llm_retry import RetryPolicy
from app.agent.planner import Planner
from app.agent.runner import AgentRunner
from app.agent.schemas import FinalAnswer, FinalEvent
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.agent.tools import ToolContext
from app.domain.dto import QueryIntent
from app.domain.enums import Category
from app.domain.errors import LlmUnavailable
from tests.agent.conftest import collect, names
from tests.agent.test_executor_qa_m6 import Fake, final
from tests.agent.test_runner import LAPTOP_INTENT, SEARCH, final_call, make_laptops
from tests.service_support import clock, make_settings


class Overloaded(Exception):
    """Giống `ServerError` của google-genai: mã HTTP ở `code`."""

    def __init__(self, code: int = 503) -> None:
        super().__init__(f"{code} UNAVAILABLE. This model is currently experiencing high demand.")
        self.code = code


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def retrying(sleeps: Sleeps, attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        attempts=attempts,
        base_delay_s=2.0,
        max_delay_s=10.0,
        max_total_wait_s=20.0,
        sleep=sleeps,
        random=lambda: 1.0,
    )


LAPTOP = QueryIntent(category=Category.laptop, price_max=30_000_000)


# ---- planner ----
async def test_planner_retries_a_503_and_returns_the_intent() -> None:
    sleeps = Sleeps()
    model = ScriptedChatModel(script=[Overloaded(), LAPTOP])

    intent = await Planner(model, retry=retrying(sleeps)).plan("laptop dưới 30 triệu")

    assert intent.category is Category.laptop and intent.price_max == 30_000_000
    assert len(model.calls) == 2 and sleeps.calls == [2.0]


async def test_planner_gives_up_after_the_last_attempt() -> None:
    sleeps = Sleeps()
    model = ScriptedChatModel(script=[Overloaded(), Overloaded(504), Overloaded(429)])

    try:
        await Planner(model, retry=retrying(sleeps)).plan("laptop dưới 30 triệu")
    except LlmUnavailable as error:
        assert error.details == {"stage": "planner"}
    else:
        raise AssertionError("phải ném LlmUnavailable")
    assert len(model.calls) == 3 and sleeps.calls == [2.0, 4.0]


async def test_planner_does_not_retry_a_bad_request() -> None:
    sleeps = Sleeps()
    model = ScriptedChatModel(script=[Overloaded(400), LAPTOP])

    try:
        await Planner(model, retry=retrying(sleeps)).plan("laptop")
    except LlmUnavailable:
        pass
    else:
        raise AssertionError("phải ném LlmUnavailable")
    assert len(model.calls) == 1 and sleeps.calls == []


async def test_planner_without_policy_keeps_failing_fast() -> None:
    model = ScriptedChatModel(script=[Overloaded(), LAPTOP])

    try:
        await Planner(model).plan("laptop")
    except LlmUnavailable:
        pass
    else:
        raise AssertionError("mặc định không thử lại")
    assert len(model.calls) == 1


# ---- executor ----
async def drive(script: list[Any], tools: list[Fake], sleeps: Sleeps) -> LoopOutcome:
    model = ScriptedChatModel(script=script)
    messages: list[BaseMessage] = [HumanMessage(content="laptop dưới 30 triệu")]
    outcome = LoopOutcome()
    loop = ToolLoop(
        model,
        [fake.tool for fake in tools],
        max_steps=6,
        allowed_writes=frozenset(),
        intent=LAPTOP,
        message="laptop dưới 30 triệu",
        retry=retrying(sleeps),
    )
    _ = [event async for event in loop.run(messages, outcome)]
    return outcome


async def test_a_tool_bound_step_is_retried() -> None:
    sleeps = Sleeps()
    script = [Overloaded(), final("Không cần tìm.")]

    outcome = await drive(script, [Fake("search_catalog")], sleeps)

    assert outcome.answer is not None and outcome.answer.text == "Không cần tìm."
    assert outcome.llm_steps == 1 and sleeps.calls == [2.0]


async def test_the_search_done_synthesis_is_retried() -> None:
    sleeps = Sleeps()
    found = {"ok": True, "total": 1, "items": []}
    script = [
        tool_call_message("search_catalog", {"n": 1}, "c1"),
        Overloaded(504),
        FinalAnswer(text="Có 1 laptop."),
    ]

    outcome = await drive(script, [Fake("search_catalog", result=found)], sleeps)

    assert outcome.stop_reason == "search_done"
    assert outcome.answer is not None and outcome.answer.text == "Có 1 laptop."
    assert sleeps.calls == [2.0]


async def test_the_executor_raises_llm_unavailable_after_the_last_attempt() -> None:
    sleeps = Sleeps()
    script: list[Any] = [Overloaded(), Overloaded(), Overloaded()]

    try:
        await drive(script, [Fake("search_catalog")], sleeps)
    except LlmUnavailable as error:
        assert error.details == {"stage": "executor"}
    else:
        raise AssertionError("phải ném LlmUnavailable")
    assert sleeps.calls == [2.0, 4.0]


# ---- cả lượt qua AgentRunner ----
async def test_a_single_503_in_the_planner_still_ends_with_a_table(
    db_session: Session, tool_ctx: ToolContext
) -> None:
    products = make_laptops(db_session)
    sleeps = Sleeps()
    planner = ScriptedChatModel(script=[Overloaded(), LAPTOP_INTENT])
    executor = ScriptedChatModel(
        script=[SEARCH, Overloaded(503), final_call(product_ids=[products[0].id])]
    )
    runner = AgentRunner(
        tool_ctx.session_factory,
        make_settings(),
        planner_model=planner,
        executor_model=executor,
        now=clock,
        retry=retrying(sleeps),
    )

    events = await collect(runner, "tìm laptop dưới 30 triệu")

    assert names(events) == ["plan", "tool_start", "tool_end", "final"]
    final_event = events[-1]
    assert isinstance(final_event, FinalEvent) and len(final_event.table) == 1
    assert sleeps.calls == [2.0, 2.0]  # một lần ở planner, một lần ở bước tổng hợp


async def test_the_runner_builds_its_policy_from_settings(tool_ctx: ToolContext) -> None:
    runner = AgentRunner(
        tool_ctx.session_factory,
        make_settings(llm_retry_attempts=4, llm_retry_base_seconds=1.5),
        planner_model=ScriptedChatModel(),
        executor_model=ScriptedChatModel(),
        now=clock,
    )

    assert runner._retry.attempts == 4 and runner._retry.base_delay_s == 1.5
