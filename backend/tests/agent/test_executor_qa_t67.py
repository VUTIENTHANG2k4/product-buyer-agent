"""QA T6.7e/v: `invalid_tool_calls`, id tool call thiếu/rỗng/trùng, log kèm `run_id`, trần gọi
`search_catalog` khi có lỗi tham số hoặc nhiều call cùng bước. Không DB, không mạng."""

import logging
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from app.agent.executor import FINAL_TOOL, TOOL_CALL_CAPS
from app.agent.planner import Planner
from app.agent.testing import ScriptedChatModel, tool_call_message
from tests.agent.test_executor_qa_m6 import Fake, FakeArgs, drive, final, several
from tests.agent.test_executor_t67e import invalid_call

SEARCH = "search_catalog"


def raw_invalid(**fields: Any) -> AIMessage:
    """AIMessage có một invalid tool call với các trường tùy ý (kể cả thiếu)."""
    call: Any = {"type": "invalid_tool_call", **fields}
    return AIMessage(content="", invalid_tool_calls=[call])


# ---- id tool call -----------------------------------------------------------------------------
@pytest.mark.parametrize("empty", [None, ""])
async def test_none_and_empty_string_ids_are_both_replaced(empty: Any) -> None:
    step = several((SEARCH, {"n": 1}, empty), (SEARCH, {"n": 2}, empty))

    run = await drive([step, final()], [Fake(SEARCH)])

    ids = [m.tool_call_id for m in run.tool_messages]
    assert ids == ["call_1_1", "call_1_2"]
    start_ids = [getattr(e, "call_id", None) for e in run.events]
    assert start_ids[0] == "call_1_1"


async def test_generated_ids_are_unique_across_steps() -> None:
    none_id: Any = None
    run = await drive(
        [
            several((SEARCH, {"n": 1}, none_id)),
            several((SEARCH, {"n": 2}, none_id)),
            final(),
        ],
        [Fake(SEARCH)],
    )

    ids = [m.tool_call_id for m in run.tool_messages]
    assert ids == ["call_1_1", "call_2_1"]


async def test_llm_supplied_ids_are_kept_untouched() -> None:
    run = await drive(
        [several((SEARCH, {"n": 1}, "abc"), (SEARCH, {"n": 2}, "xyz")), final()], [Fake(SEARCH)]
    )

    assert [m.tool_call_id for m in run.tool_messages] == ["abc", "xyz"]


async def test_generated_id_does_not_collide_with_an_id_the_llm_chose() -> None:
    none_id: Any = None
    # Call thứ hai không có id sẽ nhận "call_1_2", trùng id do LLM đặt cho call thứ nhất.
    step = several((SEARCH, {"n": 1}, "call_1_2"), (SEARCH, {"n": 2}, none_id))

    run = await drive([step, final()], [Fake(SEARCH)])

    ids = [m.tool_call_id for m in run.tool_messages]
    assert len(set(ids)) == len(ids) == 2


async def test_final_answer_and_invalid_call_in_one_step_both_get_ids_and_answer_later() -> None:
    none_id: Any = None
    reply = AIMessage(
        content="",
        tool_calls=[{"name": FINAL_TOOL, "args": {"text": "xong"}, "id": none_id}],
        invalid_tool_calls=[
            {
                "name": SEARCH,
                "args": "{",
                "id": none_id,
                "error": "bad",
                "type": "invalid_tool_call",
            }
        ],
    )

    run = await drive([reply, final()], [Fake(SEARCH)])

    ids = [m.tool_call_id for m in run.tool_messages]
    assert all(ids) and len(set(ids)) == 2
    assert run.error_codes() == ["INVALID_TOOL_CALL", "FINAL_TOO_EARLY"]
    assert run.outcome.stop_reason == "final"


# ---- invalid_tool_calls thiếu trường ----------------------------------------------------------
async def test_invalid_call_without_name_args_error_or_id_does_not_crash_the_loop() -> None:
    run = await drive([raw_invalid(), final()], [Fake(SEARCH)])

    assert run.error_codes() == ["INVALID_TOOL_CALL"]
    assert run.tool_messages[0].tool_call_id == "call_1_1"
    assert run.outcome.stop_reason == "final"


async def test_two_nameless_invalid_calls_in_a_row_stop_with_tool_failures() -> None:
    run = await drive(
        [raw_invalid(name=None), raw_invalid(name=None), {"text": "Tóm tắt."}], [Fake(SEARCH)]
    )

    assert run.outcome.stop_reason == "tool_failures"
    assert run.error_codes() == ["INVALID_TOOL_CALL"] * 2


async def test_invalid_call_error_text_is_truncated_to_a_short_message() -> None:
    run = await drive([raw_invalid(name=SEARCH, error="x" * 5000), final()], [Fake(SEARCH)])

    assert len(str(run.tool_messages[0].content)) < 600


async def test_invalid_final_answer_then_valid_final_answer_finishes_with_final() -> None:
    run = await drive(
        [raw_invalid(name=FINAL_TOOL, args='{"text":', id="f0", error="json"), final("ok")],
        [Fake(SEARCH)],
    )

    assert run.error_codes() == ["INVALID_TOOL_CALL"]
    assert run.outcome.stop_reason == "final"
    assert run.outcome.answer is not None and run.outcome.answer.text == "ok"


async def test_invalid_call_mixed_with_a_valid_call_in_one_step_runs_the_valid_one() -> None:
    search = Fake(SEARCH)
    reply = AIMessage(
        content="",
        tool_calls=[{"name": SEARCH, "args": {"n": 1}, "id": "ok1"}],
        invalid_tool_calls=invalid_call(call_id="bad1").invalid_tool_calls,
    )

    run = await drive([reply, final()], [search])

    assert len(search.calls) == 1
    assert sorted(m.tool_call_id for m in run.tool_messages) == ["bad1", "ok1"]
    assert run.error_codes() == ["INVALID_TOOL_CALL"]


async def test_invalid_calls_alone_do_not_count_toward_the_search_cap() -> None:
    search = Fake(SEARCH)
    script = [invalid_call(call_id=f"b{i}") for i in range(1)] + [
        *[tool_call_message(SEARCH, {"n": i}, f"c{i}") for i in range(3)],
        final(),
    ]

    run = await drive(script, [search])

    assert len(search.calls) == 3
    assert run.outcome.stop_reason == "final"


# ---- trần search_catalog ----------------------------------------------------------------------
class SearchWithBadArgs(Fake):
    """Lần gọi có `n < 0` trả VALIDATION_ERROR (sai tham số, chưa tới Fetcher)."""

    @property
    def tool(self) -> StructuredTool:
        async def run(product_id: int | None = None, n: int = 0) -> Any:
            self.calls.append({"product_id": product_id, "n": n})
            if n < 0:
                return {"ok": False, "error": "VALIDATION_ERROR", "message": "n < 0"}
            return {"ok": True, "product_id": 7}

        return StructuredTool.from_function(
            coroutine=run, name=self.name, description="tool giả", args_schema=FakeArgs
        )


async def test_validation_errors_do_not_use_up_the_search_cap() -> None:
    cap = TOOL_CALL_CAPS[SEARCH]
    search = SearchWithBadArgs(SEARCH)
    bad = tool_call_message(SEARCH, {"n": -1}, "bad")
    good = [tool_call_message(SEARCH, {"n": i}, f"g{i}") for i in range(cap)]

    run = await drive([bad, *good, final()], [search])

    assert len(search.calls) == cap + 1  # 1 lần sai tham số + đủ 3 lần chạy thật
    assert run.outcome.calls_by_tool == {SEARCH: cap}
    assert "TOOL_CALL_LIMIT" not in run.error_codes()
    assert run.outcome.stop_reason == "final"


async def test_cap_applies_to_calls_inside_one_step() -> None:
    cap = TOOL_CALL_CAPS[SEARCH]
    search = Fake(SEARCH)
    step = several(*[(SEARCH, {"n": i}, f"c{i}") for i in range(cap + 1)])

    run = await drive([step, final()], [search])

    assert len(search.calls) == cap
    assert run.error_codes() == ["TOOL_CALL_LIMIT"]
    assert run.outcome.stop_reason == "final"  # 1 lỗi chưa tới ngưỡng dừng


async def test_a_failing_search_still_counts_toward_the_cap() -> None:
    cap = TOOL_CALL_CAPS[SEARCH]
    search = Fake(SEARCH, result={"ok": False, "error": "NO_DATA", "message": "x"})
    script = [tool_call_message(SEARCH, {"n": i}, f"c{i}") for i in range(cap)]

    run = await drive([*script, {"text": "Không có dữ liệu."}], [search])

    # 2 lỗi liên tiếp dừng vòng lặp trước khi tới trần: không bao giờ chạy quá `cap` lần.
    assert len(search.calls) <= cap
    assert run.outcome.stop_reason == "tool_failures"


async def test_other_tools_are_not_limited_by_the_search_cap() -> None:
    other = Fake("get_product_details")
    script = [tool_call_message("get_product_details", {"n": i}, f"c{i}") for i in range(5)]

    run = await drive([*script, final()], [Fake(SEARCH), other])

    assert len(other.calls) == 5
    assert "TOOL_CALL_LIMIT" not in run.error_codes()


# ---- log kèm run_id ---------------------------------------------------------------------------
async def test_planner_without_run_id_has_no_tag(caplog: pytest.LogCaptureFixture) -> None:
    planner = Planner(ScriptedChatModel(script=[RuntimeError("503")]))

    with caplog.at_level(logging.ERROR, logger="app.agent.planner"), pytest.raises(Exception):  # noqa: B017
        await planner.plan("laptop 20 triệu")

    assert caplog.records[0].getMessage().startswith("Planner không gọi")


async def test_planner_invalid_output_log_carries_the_run_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    planner = Planner(ScriptedChatModel(script=[{"price_max": "không phải số"}, {"limit": 999}]))

    with caplog.at_level(logging.WARNING, logger="app.agent.planner"), pytest.raises(Exception):  # noqa: B017
        await planner.plan("laptop", run_id=123)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and all(w.startswith("[run 123] Planner lần") for w in warnings)
