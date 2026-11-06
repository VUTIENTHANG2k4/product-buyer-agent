"""T6.7e: `invalid_tool_calls`, id tool call thiếu và log kèm `run_id`."""

import logging
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.executor import FINAL_TOOL, LoopOutcome, ToolLoop
from app.agent.guardrail import Evidence
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.domain.errors import LlmUnavailable
from tests.agent.test_executor_qa_m6 import Fake, drive, final, several

SEARCH = "search_catalog"


def invalid_call(name: str = SEARCH, call_id: str | None = "bad1") -> AIMessage:
    """Phản hồi mà LangChain không parse được tham số JSON của tool call."""
    return AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": name,
                "args": '{"query": ',
                "id": call_id,
                "error": "Function search_catalog arguments: not valid JSON",
                "type": "invalid_tool_call",
            }
        ],
    )


async def test_invalid_tool_call_gets_an_error_message_and_the_llm_is_asked_again() -> None:
    search = Fake(SEARCH)

    run = await drive(
        [invalid_call(), tool_call_message(SEARCH, {"n": 1}, "c1"), final()], [search]
    )

    assert run.outcome.stop_reason == "final"  # không bị coi là text_fallback
    assert run.error_codes() == ["INVALID_TOOL_CALL"]
    assert run.tool_messages[0].tool_call_id == "bad1"
    assert len(search.calls) == 1  # lần gọi hợp lệ sau đó vẫn chạy


async def test_two_invalid_calls_of_the_same_tool_stop_the_loop_with_tool_failures() -> None:
    run = await drive(
        [invalid_call(), invalid_call(call_id="bad2"), {"text": "Tóm tắt."}], [Fake(SEARCH)]
    )

    assert run.outcome.stop_reason == "tool_failures"
    assert run.error_codes() == ["INVALID_TOOL_CALL"] * 2


async def test_invalid_call_next_to_final_answer_makes_the_final_too_early() -> None:
    reply = AIMessage(
        content="",
        tool_calls=[{"name": FINAL_TOOL, "args": {"text": "xong"}, "id": "f1"}],
        invalid_tool_calls=invalid_call().invalid_tool_calls,
    )

    run = await drive([reply, final()], [Fake(SEARCH)])

    assert run.error_codes() == ["INVALID_TOOL_CALL", "FINAL_TOO_EARLY"]
    assert run.outcome.stop_reason == "final"


async def test_missing_call_ids_are_filled_and_match_the_ai_message() -> None:
    none_id: Any = None
    step = several((SEARCH, {"n": 1}, none_id), (SEARCH, {"n": 2}, none_id))
    search = Fake(SEARCH)

    run = await drive([step, final()], [search])

    ai_message = run.messages[1]
    assert isinstance(ai_message, AIMessage)
    ai_ids = [call["id"] for call in ai_message.tool_calls]
    tool_ids = [m.tool_call_id for m in run.tool_messages]
    assert ai_ids == ["call_1_1", "call_1_2"]
    assert tool_ids == ai_ids
    assert len(search.calls) == 2


async def test_missing_id_on_an_over_limit_call_and_on_final_too_early_get_ids() -> None:
    none_id: Any = None
    calls = [(SEARCH, {"n": i}, none_id) for i in range(6)]  # MAX_CALLS_PER_STEP = 5
    step = AIMessage(
        content="",
        tool_calls=[
            *several(*calls).tool_calls,
            {"name": FINAL_TOOL, "args": {"text": "xong"}, "id": None},
        ],
    )

    run = await drive([step, final()], [Fake(SEARCH)])

    ids = [m.tool_call_id for m in run.tool_messages]
    assert all(ids) and len(set(ids)) == len(ids) == 7
    assert "TOO_MANY_CALLS" in run.error_codes() and "FINAL_TOO_EARLY" in run.error_codes()


async def test_log_lines_carry_the_run_id(caplog: pytest.LogCaptureFixture) -> None:
    model = ScriptedChatModel(
        script=[tool_call_message("add_to_shopping_list", {"product_id": 1}), RuntimeError("503")]
    )
    loop = ToolLoop(
        model,
        [Fake("add_to_shopping_list").tool],
        max_steps=4,
        allowed_writes=frozenset(),
        run_id="run-42",
    )
    outcome = LoopOutcome(evidence=Evidence(product_ids=set()))

    with (
        caplog.at_level(logging.WARNING, logger="app.agent.executor"),
        pytest.raises(LlmUnavailable),
    ):
        _ = [e async for e in loop.run([HumanMessage(content="thêm")], outcome)]

    tagged = [r.getMessage() for r in caplog.records if "[run run-42]" in r.getMessage()]
    assert any("Chặn tool ghi" in line for line in tagged)
    assert any("không gọi được LLM" in line for line in tagged)


async def test_log_lines_have_no_tag_without_a_run_id(caplog: pytest.LogCaptureFixture) -> None:
    loop = ToolLoop(
        ScriptedChatModel(script=[tool_call_message("add_to_shopping_list", {}), final()]),
        [Fake("add_to_shopping_list").tool],
        max_steps=3,
        allowed_writes=frozenset(),
    )

    with caplog.at_level(logging.WARNING, logger="app.agent.executor"):
        _ = [
            e
            async for e in loop.run(
                [HumanMessage(content="x")], LoopOutcome(evidence=Evidence(product_ids=set()))
            )
        ]

    assert [r.getMessage() for r in caplog.records if "Chặn tool ghi" in r.getMessage()] == [
        "Chặn tool ghi add_to_shopping_list: người dùng chưa yêu cầu rõ ràng"
    ]


async def test_planner_logs_carry_the_run_id(caplog: pytest.LogCaptureFixture) -> None:
    from app.agent.planner import Planner

    planner = Planner(ScriptedChatModel(script=[RuntimeError("503")]))

    with caplog.at_level(logging.ERROR, logger="app.agent.planner"), pytest.raises(LlmUnavailable):
        await planner.plan("laptop 20 triệu", run_id="run-7")

    assert [r.getMessage() for r in caplog.records][0].startswith("[run run-7] Planner không gọi")
