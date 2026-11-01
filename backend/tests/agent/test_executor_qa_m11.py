"""QA M11: trần số lần gọi `live_search_other` (TOOL_CALL_CAPS) khi kết hợp với các cổng và giới
hạn khác của ToolLoop: nhiều tool trong một bước, tool lạ, hết bước, tool ném lỗi, kết quả sai
định dạng, FinalAnswer cùng bước, tổng hợp khi dừng `tool_failures`, `call_id` lạ."""

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agent.executor import (
    _SYNTHESIS_HINTS,
    MAX_CALLS_PER_STEP,
    TOOL_CALL_CAPS,
    TOOL_FAILURE_LIMIT,
)
from app.agent.guardrail import ADD_TOOL
from app.agent.testing import tool_call_message
from app.agent.tools import TOOL_NAMES, WRITE_TOOLS, ToolContext
from app.agent.tools import live_search_other as live_tool_module
from tests.agent.test_executor_qa_m6 import Fake, drive, final, several

LIVE = "live_search_other"
SEARCH = "search_catalog"
CAP = TOOL_CALL_CAPS[LIVE]


def _live_result(url: str) -> dict[str, Any]:
    return {"ok": True, "items": [{"title": "Loa", "price": 500_000, "url": url, "site": "gearvn"}]}


class _Args(BaseModel):
    n: int = 0


class Scripted(Fake):
    """Tool giả trả/ném lần lượt từng phần tử (Exception thì ném; phần tử cuối lặp lại mãi)."""

    def __init__(self, name: str, items: list[Any]) -> None:
        super().__init__(name)
        self.count = 0
        self._items = items

    @property
    def tool(self) -> StructuredTool:
        async def run(n: int = 0) -> Any:
            item = self._items[min(self.count, len(self._items) - 1)]
            self.count += 1
            if isinstance(item, Exception):
                raise item
            return item

        return StructuredTool.from_function(
            coroutine=run, name=self.name, description="tool giả", args_schema=_Args
        )


class RealLive(Fake):
    """Tool `live_search_other` thật (không có service: trả rỗng, không chạm mạng/DB)."""

    def __init__(self) -> None:
        super().__init__(LIVE)

    @property
    def tool(self) -> StructuredTool:
        ctx = ToolContext(session_factory=lambda: None, settings=None, live_search=None)  # type: ignore[arg-type,return-value]
        return live_tool_module.build(ctx)


def _live_step(count: int, prefix: str = "c") -> list[AIMessage]:
    return [tool_call_message(LIVE, {"n": i}, f"{prefix}{i}") for i in range(count)]


# ---- cấu hình ----
def test_caps_name_real_tools_that_are_not_write_tools_and_cannot_be_mutated() -> None:
    assert set(TOOL_CALL_CAPS) <= set(TOOL_NAMES)  # gõ sai tên thì trần âm thầm mất tác dụng
    assert not set(TOOL_CALL_CAPS) & WRITE_TOOLS  # tool ghi có trần riêng MAX_WRITE_CALLS
    assert all(isinstance(cap, int) and cap >= 1 for cap in TOOL_CALL_CAPS.values())
    with pytest.raises(TypeError):
        TOOL_CALL_CAPS["search_catalog"] = 1  # type: ignore[index]


def test_synthesis_hint_for_tool_failures_mentions_the_call_limit() -> None:
    assert "hết số lần gọi" in _SYNTHESIS_HINTS["tool_failures"]


# ---- nhiều tool trong một bước ----
async def test_other_tools_in_the_same_step_run_before_and_after_the_blocked_call_in_order() -> (
    None
):
    live, search = Fake(LIVE), Fake(SEARCH)
    step = several(
        (SEARCH, {"n": 1}, "s1"),
        (LIVE, {"n": 1}, "l1"),
        (LIVE, {"n": 2}, "l2"),
        (LIVE, {"n": 3}, "l3"),  # bị chặn
        (SEARCH, {"n": 2}, "s2"),  # vẫn phải chạy
    )

    run = await drive([step, final()], [live, search])

    assert [(e.call_id, e.ok) for e in run.ends] == [
        ("s1", True),
        ("l1", True),
        ("l2", True),
        ("l3", False),
        ("s2", True),
    ]
    assert [c["n"] for c in search.calls] == [1, 2]
    assert [c["n"] for c in live.calls] == [1, 2]
    assert run.outcome.calls_by_tool == {SEARCH: 2, LIVE: CAP}
    assert run.outcome.tool_calls == 5  # lời gọi bị chặn vẫn tính vào tool_calls của run
    assert run.outcome.stop_reason == "final"  # mới 1 lỗi: chưa chạm TOOL_FAILURE_LIMIT


async def test_blocked_live_calls_do_not_add_failures_to_the_other_tools() -> None:
    live, search = Fake(LIVE), Fake(SEARCH)
    step = several(*[(LIVE, {"n": i}, f"l{i}") for i in range(CAP)])
    blocked = several((LIVE, {"n": 9}, "lx"), (SEARCH, {"n": 1}, "s1"), (SEARCH, {"n": 2}, "s2"))

    run = await drive([step, blocked, final()], [live, search])

    assert len(search.calls) == 2
    assert run.error_codes() == ["TOOL_CALL_LIMIT"]
    assert run.outcome.stop_reason == "final"


async def test_cap_and_per_step_limit_together_blocked_and_extra_calls_get_one_message_each() -> (
    None
):
    live, search = Fake(LIVE), Fake(SEARCH)
    calls = [(LIVE, {"n": i}, f"l{i}") for i in range(MAX_CALLS_PER_STEP)]
    calls.append((SEARCH, {"n": 1}, "extra"))  # vượt MAX_CALLS_PER_STEP

    run = await drive([several(*calls), {"text": "Tổng hợp."}], [live, search])

    assert len(live.calls) == CAP and search.calls == []
    assert run.error_codes() == ["TOOL_CALL_LIMIT"] * (MAX_CALLS_PER_STEP - CAP) + [
        "TOO_MANY_CALLS"
    ]
    ids = [m.tool_call_id for m in run.tool_messages]
    assert sorted(ids) == sorted([*(f"l{i}" for i in range(MAX_CALLS_PER_STEP)), "extra"])
    assert run.outcome.stop_reason == "tool_failures"  # 3 lần bị chặn >= TOOL_FAILURE_LIMIT


# ---- tên / call_id lạ ----
@pytest.mark.parametrize(
    "name", ["Live_Search_Other", "LIVE_SEARCH_OTHER", " live_search_other", "live_search_other\n"]
)
async def test_name_variants_are_unknown_tools_and_never_use_the_cap(name: str) -> None:
    live = Fake(LIVE)
    script = [
        tool_call_message(name, {"n": 0}, "v1"),
        tool_call_message(LIVE, {"n": 1}, "c1"),
        tool_call_message(LIVE, {"n": 2}, "c2"),
        final(),
    ]

    run = await drive(script, [live])

    assert run.error_codes() == ["UNKNOWN_TOOL"]
    assert len(live.calls) == CAP  # hai lần thật vẫn chạy đủ
    assert run.outcome.calls_by_tool == {LIVE: CAP}


async def test_live_tool_that_is_not_registered_is_unknown_and_not_counted() -> None:
    run = await drive([_live_step(1)[0], final()], [Fake(SEARCH)])

    assert run.error_codes() == ["UNKNOWN_TOOL"]
    assert run.outcome.calls_by_tool == {}


async def test_duplicate_call_ids_are_each_counted_and_each_get_a_message() -> None:
    live = Fake(LIVE)
    step = several(*[(LIVE, {"n": i}, "dup") for i in range(CAP + 1)])

    run = await drive([step, final()], [live])

    assert len(live.calls) == CAP
    assert run.outcome.calls_by_tool == {LIVE: CAP}
    assert [m.tool_call_id for m in run.tool_messages] == ["dup"] * (CAP + 1)
    assert run.error_codes() == ["TOOL_CALL_LIMIT"]


async def test_calls_without_an_id_get_distinct_generated_ids_and_are_still_capped() -> None:
    live = Fake(LIVE)
    step = AIMessage(
        content="", tool_calls=[{"name": LIVE, "args": {"n": i}, "id": None} for i in range(3)]
    )

    run = await drive([step, final()], [live])

    ids = [m.tool_call_id for m in run.tool_messages]
    assert len(set(ids)) == 3
    assert len(live.calls) == CAP and run.error_codes() == ["TOOL_CALL_LIMIT"]


# ---- FinalAnswer cùng bước với lời gọi bị chặn ----
@pytest.mark.parametrize("final_first", [False, True])
async def test_final_answer_in_the_same_step_as_a_blocked_call_is_rejected_then_accepted(
    final_first: bool,
) -> None:
    live = Fake(LIVE)
    blocked = (LIVE, {"n": 9}, "lx")
    fin = ("FinalAnswer", {"text": "quá sớm"}, "f_early")
    step = several(fin, blocked) if final_first else several(blocked, fin)

    run = await drive([*_live_step(CAP), step, final("đúng")], [live])

    assert run.error_codes() == ["TOOL_CALL_LIMIT", "FINAL_TOO_EARLY"]
    assert run.outcome.stop_reason == "final"
    assert run.outcome.answer is not None and run.outcome.answer.text == "đúng"
    assert len(live.calls) == CAP
    ids = [m.tool_call_id for m in run.tool_messages]
    assert ids.count("lx") == 1 and ids.count("f_early") == 1


async def test_final_answer_with_two_blocked_calls_stops_on_failures_and_resynthesizes() -> None:
    live = Fake(LIVE)
    step = several(
        (LIVE, {"n": 8}, "lx"),
        (LIVE, {"n": 9}, "ly"),
        ("FinalAnswer", {"text": "từ bước"}, "f1"),
    )

    run = await drive([*_live_step(CAP), step, {"text": "từ tổng hợp"}], [live])

    assert run.outcome.stop_reason == "tool_failures"
    assert run.error_codes() == ["TOOL_CALL_LIMIT", "TOOL_CALL_LIMIT", "FINAL_TOO_EARLY"]
    assert run.outcome.answer is not None and run.outcome.answer.text == "từ tổng hợp"


# ---- dừng `tool_failures` do trần: câu trả lời lấy từ evidence đã có ----
async def test_stop_after_blocked_calls_synthesizes_from_results_already_collected() -> None:
    urls = [f"https://shop.example/{i}" for i in range(3)]
    live = Scripted(LIVE, [_live_result(url) for url in urls])

    run = await drive([*_live_step(4), {"text": "Dựa trên 2 kết quả."}], [live])

    assert run.outcome.stop_reason == "tool_failures"
    assert run.outcome.answer is not None and run.outcome.answer.text == "Dựa trên 2 kết quả."
    assert run.outcome.evidence.live_urls == set(urls[:CAP])
    last_prompt = run.model.calls[-1]
    assert isinstance(last_prompt[-1], HumanMessage)
    assert last_prompt[-1].content == _SYNTHESIS_HINTS["tool_failures"]
    sent = " ".join(str(m.content) for m in last_prompt if isinstance(m, ToolMessage))
    assert all(url in sent for url in urls[:CAP]) and urls[CAP] not in sent
    assert run.model.cursor == 5  # 4 bước + 1 lần tổng hợp


async def test_invalid_synthesis_after_blocked_calls_leaves_no_answer_but_keeps_evidence() -> None:
    live = Scripted(LIVE, [_live_result("https://shop.example/1")])

    run = await drive([*_live_step(4), {"text": 1}], [live])

    assert run.outcome.stop_reason == "tool_failures"
    assert run.outcome.answer is None
    assert run.outcome.evidence.live_urls == {"https://shop.example/1"}


# ---- max_steps ----
@pytest.mark.parametrize(
    ("max_steps", "calls", "reason"),
    [
        (1, CAP + 1, "step_limit"),  # 1 lần bị chặn < TOOL_FAILURE_LIMIT, hết bước
        (1, CAP + TOOL_FAILURE_LIMIT, "tool_failures"),  # đủ lỗi thì dừng trước khi hết bước
    ],
)
async def test_max_steps_smaller_than_the_number_of_calls(
    max_steps: int, calls: int, reason: str
) -> None:
    live = Fake(LIVE)
    step = several(*[(LIVE, {"n": i}, f"c{i}") for i in range(calls)])

    run = await drive([step, {"text": "Tổng hợp."}], [live], max_steps=max_steps)

    assert len(live.calls) == CAP
    assert run.outcome.stop_reason == reason
    assert run.outcome.answer is not None and run.outcome.answer.text == "Tổng hợp."
    assert run.outcome.llm_steps == 1


async def test_blocked_call_on_the_last_step_still_synthesizes_the_step_limit_answer() -> None:
    live = Fake(LIVE)

    run = await drive([*_live_step(CAP + 1), {"text": "Hết bước."}], [live], max_steps=CAP + 1)

    assert run.outcome.stop_reason == "step_limit"
    assert run.error_codes() == ["TOOL_CALL_LIMIT"]
    assert run.outcome.answer is not None and run.outcome.answer.text == "Hết bước."


# ---- tool lỗi / kết quả sai định dạng vẫn tiêu tốn trần ----
async def test_tool_exception_uses_the_cap_and_error_plus_blocked_call_stop_the_loop() -> None:
    boom = RuntimeError("secret=hunter2")
    live = Scripted(LIVE, [boom, _live_result("https://shop.example/1")])

    run = await drive([*_live_step(3), {"text": "Một phần."}], [live])

    assert live.count == CAP
    assert run.error_codes() == ["TOOL_ERROR", "TOOL_CALL_LIMIT"]
    assert run.outcome.stop_reason == "tool_failures"  # 1 lỗi tool + 1 bị chặn = 2 lần lỗi cùng tên
    assert run.outcome.evidence.live_urls == {"https://shop.example/1"}
    assert "hunter2" not in " ".join(str(m.content) for m in run.messages)


@pytest.mark.parametrize("bad", [["không", "phải", "dict"], None, "không phải JSON", 42])
async def test_malformed_result_counts_against_the_cap_like_any_other_failed_call(bad: Any) -> None:
    live = Scripted(LIVE, [bad, _live_result("https://shop.example/1")])

    run = await drive([*_live_step(3), final()], [live])

    assert live.count == CAP
    assert run.error_codes() == ["TOOL_ERROR", "TOOL_CALL_LIMIT"]
    assert run.outcome.evidence.live_urls == {"https://shop.example/1"}


# ---- độc lập với ngân sách tool ghi ----
async def test_live_cap_and_write_budget_are_independent() -> None:
    live, write = Fake(LIVE), Fake(ADD_TOOL)
    step = several(
        (LIVE, {"n": 1}, "l1"),
        (LIVE, {"n": 2}, "l2"),
        (LIVE, {"n": 3}, "l3"),
        (ADD_TOOL, {"product_id": 7}, "w1"),
    )

    run = await drive([step, final()], [live, write], allowed=frozenset({ADD_TOOL}), seen_ids={7})

    assert run.error_codes() == ["TOOL_CALL_LIMIT"]
    assert len(write.calls) == 1
    assert run.outcome.write_calls == 1  # lời gọi live bị chặn không ăn ngân sách ghi
    assert run.outcome.calls_by_tool == {LIVE: CAP, ADD_TOOL: 1}


# ---- BUG-M11-1 ----
async def test_validation_error_before_the_search_does_not_use_up_the_cap() -> None:
    script = [
        tool_call_message(LIVE, {}, "bad"),  # thiếu `query`
        tool_call_message(LIVE, {"query": "loa jbl"}, "ok1"),
        tool_call_message(LIVE, {"query": "loa sony"}, "ok2"),
        final(),
    ]

    run = await drive(script, [RealLive()])

    codes = run.error_codes()
    assert codes == ["VALIDATION_ERROR"]  # sửa ở M11 (BUG-M11-1): sai tham số không ăn trần
    bodies = [json.loads(str(m.content)) for m in run.tool_messages]
    assert [b.get("reason") for b in bodies[1:]] == ["tìm trực tiếp chưa khả dụng"] * CAP
