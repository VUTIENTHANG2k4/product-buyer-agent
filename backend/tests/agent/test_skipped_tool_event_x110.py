"""X1.10: lời gọi bị chốt chặn phát `tool_end` với `skipped=true` để giao diện không hiện ✗ đỏ.

Hội thoại 50 (2026-11-09): lần `search_catalog` thứ 4 bị trần 3 lần/lượt và hiện như một lỗi.
"""

from app.agent.executor import TOOL_CALL_CAPS
from app.agent.schemas import ToolEndEvent
from app.agent.testing import tool_call_message
from tests.agent.test_executor_qa_m6 import Fake, drive, final

SEARCH = "search_catalog"


async def test_a_call_over_the_cap_is_reported_as_skipped_not_failed() -> None:
    cap = TOOL_CALL_CAPS[SEARCH]
    script = [tool_call_message(SEARCH, {"n": i}, f"c{i}") for i in range(cap + 1)]

    run = await drive([*script, final()], [Fake(SEARCH)])

    *ran, over = run.ends
    assert [(end.ok, end.skipped) for end in ran] == [(True, False)] * cap
    assert (over.ok, over.skipped) == (False, True)
    assert over.summary == "Bỏ qua: đã đủ số lần gọi trong lượt"
    assert over.record()["data"]["skipped"] is True


async def test_a_write_the_user_did_not_ask_for_is_skipped() -> None:
    script = [tool_call_message("add_to_shopping_list", {"product_id": 7}, "c1"), final()]

    run = await drive(script, [Fake("add_to_shopping_list")])

    (end,) = run.ends
    assert (end.ok, end.skipped, end.summary) == (False, True, "Bỏ qua: người dùng chưa yêu cầu")


async def test_a_real_tool_error_is_still_a_failure() -> None:
    broken = Fake(SEARCH, raises=RuntimeError("db down"))

    run = await drive([tool_call_message(SEARCH, {"n": 1}, "c1"), final()], [broken])

    (end,) = run.ends
    assert (end.ok, end.skipped) == (False, False)
    assert end.summary == "Lỗi hệ thống khi chạy tool"


def test_old_recorded_events_without_the_flag_still_load() -> None:
    event = ToolEndEvent.model_validate(
        {"call_id": "c1", "tool": SEARCH, "ok": True, "summary": "x", "duration_ms": 1}
    )

    assert event.skipped is False
