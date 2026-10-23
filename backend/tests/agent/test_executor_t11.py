"""T11.1: trần số lần chạy thật của tool tìm trực tiếp trong một lượt (eval T03 từng gọi 8 lần)."""

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agent.executor import TOOL_CALL_CAPS
from app.agent.testing import tool_call_message
from tests.agent.test_executor_qa_m6 import Fake, drive, final, several

LIVE = "live_search_other"
SEARCH = "search_catalog"
CAP = TOOL_CALL_CAPS[LIVE]


class _NoArgs(BaseModel):
    n: int = 0


class Sequenced(Fake):
    """Tool giả trả lần lượt từng kết quả đã định sẵn (lần cuối lặp lại mãi)."""

    def __init__(self, name: str, results: list[dict[str, Any]]) -> None:
        super().__init__(name)
        self.count = 0
        self._results = results

    @property
    def tool(self) -> StructuredTool:
        async def run(n: int = 0) -> Any:
            result = self._results[min(self.count, len(self._results) - 1)]
            self.count += 1
            return result

        return StructuredTool.from_function(
            coroutine=run, name=self.name, description="tool giả", args_schema=_NoArgs
        )


def _live_result(url: str) -> dict[str, Any]:
    return {"ok": True, "items": [{"title": "Loa", "price": 500_000, "url": url, "site": "gearvn"}]}


async def test_live_search_is_capped_per_turn_and_the_loop_still_ends_with_an_answer() -> None:
    live = Fake(LIVE)
    script = [tool_call_message(LIVE, {"n": i}, f"c{i}") for i in range(4)]

    run = await drive([*script, {"text": "Tổng hợp từ kết quả đã có."}], [live])

    assert len(live.calls) == CAP
    assert run.outcome.calls_by_tool == {LIVE: CAP}
    assert run.error_codes() == ["TOOL_CALL_LIMIT"] * 2
    assert run.outcome.stop_reason == "tool_failures"
    assert run.outcome.answer is not None


async def test_calls_in_the_same_step_are_counted_one_by_one() -> None:
    live = Fake(LIVE)
    step = several(*[(LIVE, {"n": i}, f"c{i}") for i in range(CAP + 1)])

    run = await drive([step, final()], [live])

    assert len(live.calls) == CAP
    assert run.error_codes() == ["TOOL_CALL_LIMIT"]


async def test_a_failed_call_still_uses_up_the_cap() -> None:
    live = Sequenced(
        LIVE, [{"ok": False, "error": "X", "message": "lỗi"}, _live_result("https://a.example/1")]
    )
    script = [tool_call_message(LIVE, {"n": i}, f"c{i}") for i in range(CAP + 1)] + [final()]

    run = await drive(script, [live])

    assert live.count == CAP
    assert run.outcome.calls_by_tool == {LIVE: CAP}
    assert run.error_codes() == ["X", "TOOL_CALL_LIMIT"]


async def test_blocked_call_adds_nothing_to_the_evidence() -> None:
    urls = [f"https://shop.example/{i}" for i in range(3)]
    live = Sequenced(LIVE, [_live_result(url) for url in urls])
    script = [tool_call_message(LIVE, {"n": i}, f"c{i}") for i in range(3)] + [final()]

    run = await drive(script, [live])

    assert live.count == CAP
    assert run.outcome.evidence.live_urls == set(urls[:CAP])


async def test_the_counter_starts_from_zero_in_every_turn() -> None:
    for _ in range(2):
        live = Fake(LIVE)

        run = await drive(
            [tool_call_message(LIVE, {"n": i}, f"c{i}") for i in range(CAP)] + [final()], [live]
        )

        assert len(live.calls) == CAP
        assert run.error_codes() == []
        assert run.outcome.stop_reason == "final"


async def test_tools_without_a_cap_are_not_limited_and_not_counted() -> None:
    search = Fake(SEARCH)
    script = [tool_call_message(SEARCH, {"n": i}, f"s{i}") for i in range(6)] + [final()]

    run = await drive(script, [search])

    assert len(search.calls) == 6
    assert run.error_codes() == []
    assert run.outcome.stop_reason == "final"


async def test_two_tool_errors_end_the_loop_as_tool_failures_not_as_a_cap_error() -> None:
    live = Fake(LIVE, result={"ok": False, "error": "X", "message": "lỗi"})

    run = await drive(
        [tool_call_message(LIVE, {"n": 0}, "c0"), tool_call_message(LIVE, {"n": 1}, "c1"), final()],
        [live],
    )

    assert run.error_codes() == ["X", "X"]
    assert run.outcome.calls_by_tool == {LIVE: 2}
    assert run.outcome.stop_reason == "tool_failures"
