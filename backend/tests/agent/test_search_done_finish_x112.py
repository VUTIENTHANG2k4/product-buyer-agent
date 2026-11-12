"""X1.12: đã có kết quả tìm và không còn tool nào cần gọi thì tổng hợp ngay.

Eval A04 "phím cơ không dây hotswap tầm 2 triệu" (2026-11-12, ×10): lần tìm đầu ra 1 sản phẩm,
Gemini thử tìm lại với khoảng giá rộng hơn ở 9/10 lần; lời gọi bị `SEARCH_DONE` chặn nên dữ liệu
đúng nhưng tốn thêm một lượt LLM (~5 s). Executor giờ bỏ bước hỏi LLM có tool đó và gọi thẳng
`with_structured_output(FinalAnswer)`.
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent.executor import SYNTHESIS_HINTS, LoopOutcome, ToolLoop
from app.agent.schemas import FinalAnswer, ToolStartEvent
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.domain.dto import QueryIntent
from app.domain.enums import Category
from tests.agent.test_executor_qa_m6 import Driven, Fake, final, several

A04 = "phím cơ không dây hotswap tầm 2 triệu"
SEARCH = "search_catalog"
DETAIL = "get_product_detail"
ADD = "add_to_shopping_list"
KEYBOARD = QueryIntent(category=Category.keyboard, price_min=1_800_000, price_max=2_200_000)


def found(total: int) -> dict[str, object]:
    return {"ok": True, "total": total, "items": []}


async def drive(
    script: list[Any],
    tools: list[Fake],
    *,
    message: str = A04,
    intent: QueryIntent | None = KEYBOARD,
    hidden: frozenset[str] = frozenset(),
    allowed_writes: frozenset[str] = frozenset(),
) -> Driven:
    model = ScriptedChatModel(script=script)
    messages: list[BaseMessage] = [HumanMessage(content=message)]
    outcome = LoopOutcome()
    loop = ToolLoop(
        model,
        [fake.tool for fake in tools],
        max_steps=6,
        allowed_writes=allowed_writes,
        intent=intent,
        message=message,
        hidden_tools=hidden,
    )
    events = [event async for event in loop.run(messages, outcome)]
    return Driven(events, outcome, messages, model)


def starts(run: Driven) -> list[str]:
    return [event.tool for event in run.events if isinstance(event, ToolStartEvent)]


async def test_a_search_with_results_is_followed_directly_by_the_synthesis() -> None:
    search = Fake(SEARCH, result=found(1))
    answer = FinalAnswer(text="Có 1 bàn phím.")

    run = await drive([tool_call_message(SEARCH, {"n": 1}, "c1"), answer], [search])

    assert starts(run) == [SEARCH]  # không còn lời gọi tìm lại bị chặn
    assert run.outcome.stop_reason == "search_done"
    assert run.outcome.answer == answer
    assert run.outcome.llm_steps == 1
    assert len(run.model.calls) == 2  # một bước có tool + một lần tổng hợp
    last = run.model.calls[-1]
    assert isinstance(last[-1], HumanMessage)
    assert last[-1].content == SYNTHESIS_HINTS["search_done"]
    assert isinstance(last[-2], ToolMessage) and last[-2].tool_call_id == "c1"


async def test_a_scripted_final_answer_tool_call_is_accepted_by_the_synthesis() -> None:
    run = await drive(
        [tool_call_message(SEARCH, {"n": 1}, "c1"), final("Có 1 bàn phím.")],
        [Fake(SEARCH, result=found(1))],
    )

    assert run.outcome.answer is not None and run.outcome.answer.text == "Có 1 bàn phím."


async def test_an_empty_search_still_lets_the_llm_relax_the_conditions() -> None:
    search = Fake(SEARCH, result=found(0))
    script = [
        tool_call_message(SEARCH, {"n": 1}, "c1"),
        tool_call_message(SEARCH, {"n": 2}, "c2"),
        final(),
    ]

    run = await drive(script, [search])

    assert [call["n"] for call in search.calls] == [1, 2]
    assert run.outcome.stop_reason == "final"  # lần tìm thứ hai cũng rỗng: LLM tự trả lời


async def test_relaxed_search_with_results_then_finishes_by_synthesis() -> None:
    results = iter([found(0), found(2)])

    class Sequenced(Fake):
        @property
        def tool(self) -> Any:
            tool = super().tool
            original = tool.coroutine

            async def run(product_id: int | None = None, n: int = 0) -> Any:
                await original(product_id=product_id, n=n)
                return next(results)

            tool.coroutine = run
            return tool

    search = Sequenced(SEARCH)
    script = [
        tool_call_message(SEARCH, {"n": 1}, "c1"),
        tool_call_message(SEARCH, {"n": 2}, "c2"),
        FinalAnswer(text="Có 2 bàn phím."),
    ]

    run = await drive(script, [search])

    assert [call["n"] for call in search.calls] == [1, 2]
    assert run.outcome.stop_reason == "search_done"
    assert len(run.model.calls) == 3


async def test_no_shortcut_when_the_user_asked_for_details() -> None:
    script = [
        tool_call_message(SEARCH, {"n": 1}, "c1"),
        tool_call_message(DETAIL, {}, "c2"),
        final(),
    ]
    detail = Fake(DETAIL)

    run = await drive(script, [Fake(SEARCH, result=found(1)), detail])

    assert starts(run) == [SEARCH, DETAIL] and len(detail.calls) == 1
    assert run.outcome.stop_reason == "final"


async def test_a_hidden_read_tool_does_not_prevent_the_shortcut() -> None:
    """Tool chi tiết bị ẩn (người dùng không hỏi) thì coi như không có: vẫn tổng hợp ngay."""
    script = [tool_call_message(SEARCH, {"n": 1}, "c1"), FinalAnswer(text="ok")]

    run = await drive(
        script, [Fake(SEARCH, result=found(1)), Fake(DETAIL)], hidden=frozenset({DETAIL})
    )

    assert run.outcome.stop_reason == "search_done"


async def test_no_shortcut_when_the_user_asked_for_a_write() -> None:
    add = Fake(ADD)
    script = [tool_call_message(SEARCH, {"n": 1}, "c1"), tool_call_message(ADD, {}, "c2"), final()]

    run = await drive(
        script,
        [Fake(SEARCH, result=found(1)), add],
        message="thêm bàn phím rẻ nhất vào danh sách",
        allowed_writes=frozenset({ADD}),
    )

    assert starts(run) == [SEARCH, ADD]
    assert run.outcome.stop_reason == "final"


async def test_no_shortcut_for_a_tier_two_intent() -> None:
    other = QueryIntent(category=Category.other, tier=2, keywords=["loa"])
    script = [tool_call_message(SEARCH, {"n": 1}, "c1"), final()]

    run = await drive(script, [Fake(SEARCH, result=found(1))], intent=other)

    assert run.outcome.stop_reason == "final"


async def test_no_shortcut_when_another_tool_ran_in_the_same_step() -> None:
    script = [
        several((SEARCH, {"n": 1}, "c1"), ("list_alerts", {}, "c2")),
        final(),
    ]

    run = await drive(script, [Fake(SEARCH, result=found(1)), Fake("list_alerts")])

    assert starts(run) == [SEARCH, "list_alerts"]
    assert run.outcome.stop_reason == "final"


async def test_without_intent_the_shortcut_still_applies() -> None:
    script = [tool_call_message(SEARCH, {"n": 1}, "c1"), FinalAnswer(text="ok")]

    run = await drive(script, [Fake(SEARCH, result=found(1))], intent=None)

    assert run.outcome.stop_reason == "search_done"


async def test_an_invalid_synthesis_falls_back_to_a_tool_bound_step() -> None:
    """Review X1c: tổng hợp hỏng thì hỏi lại LLM có tool như trước X1.12 (FinalAnswer sai còn được
    báo lại để viết lại), thay vì kết thúc lượt không có câu trả lời."""
    script = [
        tool_call_message(SEARCH, {"n": 1}, "c1"),
        AIMessage(content="không phải JSON"),  # lần tổng hợp hỏng
        final("Có 1 bàn phím."),  # bước có tool kế tiếp
    ]

    run = await drive(script, [Fake(SEARCH, result=found(1))])

    assert run.outcome.stop_reason == "final"
    assert run.outcome.answer is not None and run.outcome.answer.text == "Có 1 bàn phím."
    assert run.outcome.llm_steps == 2 and len(run.model.calls) == 3


async def test_a_search_locked_on_the_last_step_is_not_reported_as_a_step_limit() -> None:
    model = ScriptedChatModel(
        script=[tool_call_message(SEARCH, {"n": 1}, "c1"), FinalAnswer(text="ok")]
    )
    messages: list[BaseMessage] = [HumanMessage(content=A04)]
    outcome = LoopOutcome()
    loop = ToolLoop(
        model,
        [Fake(SEARCH, result=found(1)).tool],
        max_steps=1,
        allowed_writes=frozenset(),
        intent=KEYBOARD,
        message=A04,
    )

    _ = [event async for event in loop.run(messages, outcome)]

    assert outcome.stop_reason == "search_done"
    assert outcome.answer is not None and outcome.answer.text == "ok"
