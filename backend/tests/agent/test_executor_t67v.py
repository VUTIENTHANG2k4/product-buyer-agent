"""T6.7v: trần gọi lặp `search_catalog` (eval L10 từng gọi 8 lần, 58 s, khi kết quả rỗng)."""

from app.agent.executor import TOOL_CALL_CAPS
from app.agent.testing import tool_call_message
from tests.agent.test_executor_qa_m6 import Fake, drive, final

SEARCH = "search_catalog"
CAP = TOOL_CALL_CAPS[SEARCH]


async def test_search_catalog_is_capped_per_turn_and_the_loop_still_answers() -> None:
    search = Fake(SEARCH)
    script = [tool_call_message(SEARCH, {"n": i}, f"c{i}") for i in range(CAP + 2)]

    run = await drive([*script, {"text": "Không có máy khớp."}], [search])

    assert len(search.calls) == CAP
    assert run.outcome.calls_by_tool == {SEARCH: CAP}
    assert run.error_codes() == ["TOOL_CALL_LIMIT"] * 2
    assert run.outcome.stop_reason == "tool_failures"
    assert run.outcome.answer is not None


async def test_cap_allows_as_many_searches_as_the_best_eval_case_needs() -> None:
    search = Fake(SEARCH)
    script = [tool_call_message(SEARCH, {"n": i}, f"c{i}") for i in range(3)] + [final()]

    run = await drive(script, [search])

    assert CAP >= 3 and len(search.calls) == 3
    assert run.error_codes() == []
    assert run.outcome.stop_reason == "final"
