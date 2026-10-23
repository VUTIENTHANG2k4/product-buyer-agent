"""T11.1: trần số lần chạy thật của tool tìm trực tiếp trong một lượt (eval T03 từng gọi 8 lần)."""

from app.agent.executor import TOOL_CALL_CAPS
from app.agent.testing import tool_call_message
from tests.agent.test_executor_qa_m6 import Fake, drive, final

LIVE = "live_search_other"
SEARCH = "search_catalog"


async def test_live_search_is_capped_per_turn_and_the_loop_still_ends_with_an_answer() -> None:
    live = Fake(LIVE)
    script = [tool_call_message(LIVE, {"n": i}, f"c{i}") for i in range(4)]

    run = await drive([*script, {"text": "Tổng hợp từ kết quả đã có."}], [live])

    assert len(live.calls) == TOOL_CALL_CAPS[LIVE]
    assert run.outcome.calls_by_tool == {LIVE: TOOL_CALL_CAPS[LIVE]}
    assert run.error_codes() == ["TOOL_CALL_LIMIT"] * 2
    assert run.outcome.stop_reason == "tool_failures"
    assert run.outcome.answer is not None


async def test_tools_without_a_cap_are_not_limited_and_not_counted() -> None:
    search = Fake(SEARCH)
    script = [tool_call_message(SEARCH, {"n": i}, f"s{i}") for i in range(6)] + [final()]

    run = await drive(script, [search])

    assert len(search.calls) == 6
    assert run.error_codes() == []
    assert run.outcome.stop_reason == "final"


async def test_repeated_tool_errors_stop_the_loop_before_the_call_cap() -> None:
    live = Fake(LIVE, result={"ok": False, "error": "X", "message": "lỗi"})

    run = await drive(
        [tool_call_message(LIVE, {"n": 0}, "c0"), tool_call_message(LIVE, {"n": 1}, "c1"), final()],
        [live],
    )

    # hai lần lỗi thật chạm trần lỗi (TOOL_FAILURE_LIMIT) trước khi chạm trần số lần gọi
    assert run.outcome.calls_by_tool == {LIVE: 2}
    assert run.outcome.stop_reason == "tool_failures"
