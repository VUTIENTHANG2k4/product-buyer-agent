"""T6.5: kịch bản agent với ScriptedChatModel (planner → tool → final, guardrail, bộ nhớ)."""

from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlmodel import Session, select

from app.agent.executor import FINAL_TOOL
from app.agent.runner import HALLUCINATION_MESSAGE, STEP_LIMIT_NOTE
from app.agent.schemas import (
    ClarificationEvent,
    ErrorEvent,
    FinalAnswer,
    FinalEvent,
    PlanEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from app.agent.testing import tool_call_message
from app.db.models import AgentRun, Message, Product, ShoppingListItem
from app.domain.enums import AgentRunStatus, MessageRole
from app.domain.errors import NotFound, ValidationFailed
from app.services.shopping_list_service import ShoppingListService
from tests.agent.conftest import RunnerParts, collect, names
from tests.service_support import NOW, add_offer, add_product, clock

Make = Callable[..., RunnerParts]

LAPTOP_INTENT: dict[str, Any] = {
    "category": "laptop",
    "tier": 1,
    "price_max": 30_000_000,
    "plan_steps": ["Tìm laptop trong danh mục", "Lọc theo giá"],
}
SEARCH = tool_call_message(
    "search_catalog", {"category": "laptop", "price_max": 30_000_000, "limit": 10}, "c1"
)


def final_call(**fields: Any) -> AIMessage:
    return tool_call_message(FINAL_TOOL, {"text": "Có laptop phù hợp.", **fields}, "f1")


def make_laptops(session: Session) -> list[Product]:
    products = []
    for price in (20_000_000, 25_000_000, 30_000_000):
        product = add_product(session)
        add_offer(session, product, price=price)
        products.append(product)
    return products


def ids(products: list[Product]) -> list[int]:
    return [p.id for p in products if p.id is not None]


def stored_run(session: Session) -> AgentRun:
    session.expire_all()
    return session.exec(select(AgentRun)).one()


def stored_messages(session: Session) -> list[Message]:
    session.expire_all()
    return list(session.exec(select(Message).order_by("id")))  # type: ignore[arg-type]


# ---- luồng chuẩn ----
async def test_standard_question_streams_plan_tool_final_with_table_from_database(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    wanted = ids(products)[:2]
    parts = make_runner(
        [LAPTOP_INTENT],
        [SEARCH, final_call(product_ids=wanted, follow_up_suggestions=["So sánh 2 máy"])],
    )

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    assert names(events) == ["plan", "tool_start", "tool_end", "final"]
    plan, start, end, final = events
    assert isinstance(plan, PlanEvent) and plan.steps == LAPTOP_INTENT["plan_steps"]
    assert isinstance(start, ToolStartEvent) and start.tool == "search_catalog"
    assert start.call_id == end.call_id == "c1" and "category=laptop" in start.args_summary
    assert isinstance(end, ToolEndEvent) and end.ok and end.summary == "Tìm thấy 3 sản phẩm"
    assert isinstance(end.duration_ms, int) and end.duration_ms >= 0
    assert isinstance(final, FinalEvent)
    assert [row.product_id for row in final.table] == wanted
    assert [row.min_price for row in final.table] == [20_000_000, 25_000_000]
    assert final.suggestions == ["So sánh 2 máy"]
    assert final.data_as_of == NOW


async def test_run_is_persisted_for_replay(db_session: Session, make_runner: Make) -> None:
    products = make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=ids(products)[:1])])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    run = stored_run(db_session)
    assert run.events == [event.record() for event in events]
    assert [e["event"] for e in run.events] == ["plan", "tool_start", "tool_end", "final"]
    assert (run.status, run.tool_calls) == (AgentRunStatus.succeeded, 1)
    assert run.latency_ms is not None and run.latency_ms >= 0
    assert run.intent is not None and run.intent["category"] == "laptop"
    user, assistant = stored_messages(db_session)
    assert (user.role, user.content) == (MessageRole.user, "tìm laptop dưới 30 triệu")
    assert assistant.role is MessageRole.assistant and assistant.content == "Có laptop phù hợp."
    assert assistant.payload == {"product_ids": ids(products)[:1]}


async def test_executor_receives_prompt_intent_and_request(
    db_session: Session, make_runner: Make
) -> None:
    make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [final_call()])

    await collect(parts.runner, "tìm laptop dưới 30 triệu")

    system, human = parts.executor.calls[0]
    assert isinstance(system, SystemMessage) and "FinalAnswer" in str(system.content)
    assert isinstance(human, HumanMessage)
    assert "Yêu cầu của người dùng: tìm laptop dưới 30 triệu" in str(human.content)
    assert '"category":"laptop"' in str(human.content)
    assert "plan_steps" not in str(human.content)
    assert "FinalAnswer" in parts.executor.bound_tool_names
    assert len(parts.executor.bound_tool_names) == 9


async def test_tool_result_is_sent_back_to_the_llm_as_tool_message(
    db_session: Session, make_runner: Make
) -> None:
    make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call()])

    await collect(parts.runner, "tìm laptop dưới 30 triệu")

    second_call = parts.executor.calls[1]
    tool_message = second_call[-1]
    assert isinstance(tool_message, ToolMessage) and tool_message.tool_call_id == "c1"
    assert '"total": 3' in str(tool_message.content)


async def test_empty_search_still_ends_with_a_final_and_empty_table(
    db_session: Session, make_runner: Make
) -> None:
    parts = make_runner(
        [LAPTOP_INTENT], [SEARCH, final_call(text="Không có laptop nào dưới 30 triệu.")]
    )

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    final = events[-1]
    assert isinstance(final, FinalEvent) and final.table == [] and final.data_as_of is None
    assert "Không có laptop" in final.text


# ---- guardrail ----
async def test_invented_product_ids_are_removed_from_the_table(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    real = ids(products)[0]
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=[999_999, real, real])])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    final = events[-1]
    assert isinstance(final, FinalEvent) and [r.product_id for r in final.table] == [real]
    assert stored_messages(db_session)[-1].payload == {"product_ids": [real]}


async def test_id_that_exists_in_database_but_not_in_tool_results_is_still_removed(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    outsider = add_product(db_session)
    add_offer(db_session, outsider, price=99_000_000)  # có trong DB nhưng ngoài kết quả tìm
    parts = make_runner(
        [LAPTOP_INTENT], [SEARCH, final_call(product_ids=[outsider.id, products[0].id])]
    )

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    final = events[-1]
    assert isinstance(final, FinalEvent) and [r.product_id for r in final.table] == [products[0].id]


async def test_all_invented_ids_end_with_agent_hallucination_error(
    db_session: Session, make_runner: Make
) -> None:
    make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=[777_777, 888_888])])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    assert names(events) == ["plan", "tool_start", "tool_end", "error"]
    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.code == "AGENT_HALLUCINATION"
    assert error.message == HALLUCINATION_MESSAGE
    run = stored_run(db_session)
    assert run.status is AgentRunStatus.failed
    assert [m.role for m in stored_messages(db_session)] == [MessageRole.user]


async def test_table_prices_come_from_the_database_not_from_the_llm_text(
    db_session: Session, make_runner: Make
) -> None:
    (first, *_) = make_laptops(db_session)
    parts = make_runner(
        [LAPTOP_INTENT],
        [SEARCH, final_call(text="Chỉ 1.000.000 ₫ thôi!", product_ids=[first.id])],
    )

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    final = events[-1]
    assert isinstance(final, FinalEvent) and final.table[0].min_price == 20_000_000


async def test_more_than_three_suggestions_are_trimmed(
    db_session: Session, make_runner: Make
) -> None:
    parts = make_runner(
        [LAPTOP_INTENT], [SEARCH, final_call(follow_up_suggestions=["a", "b", "c", "d", " "])]
    )

    final = (await collect(parts.runner, "tìm laptop dưới 30 triệu"))[-1]

    assert isinstance(final, FinalEvent) and final.suggestions == ["a", "b", "c"]


# ---- giới hạn bước và lỗi tool ----
async def test_step_limit_synthesizes_from_results_so_far(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    synth = FinalAnswer(text="Tạm thời có 3 máy.", product_ids=ids(products))
    parts = make_runner([LAPTOP_INTENT], [SEARCH, SEARCH, synth], max_steps=2)

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    assert names(events).count("tool_start") == 2
    final = events[-1]
    assert isinstance(final, FinalEvent) and final.text.endswith(STEP_LIMIT_NOTE)
    assert len(final.table) == 3
    assert len(parts.executor.calls) == 3  # 2 bước + 1 lần tổng hợp
    assert "hết số bước" in str(parts.executor.calls[-1][-1].content)


async def test_step_limit_without_any_answer_is_an_error_event(
    db_session: Session, make_runner: Make
) -> None:
    broken_final = tool_call_message(FINAL_TOOL, {"text": 123}, "f1")  # sai kiểu
    parts = make_runner([LAPTOP_INTENT], [broken_final, broken_final], max_steps=2)

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.code == "AGENT_STEP_LIMIT"
    assert stored_run(db_session).status is AgentRunStatus.failed
    tool_message = parts.executor.calls[1][-1]
    assert isinstance(tool_message, ToolMessage) and "VALIDATION_ERROR" in str(tool_message.content)


async def test_invalid_final_answer_can_be_corrected_in_the_next_step(
    db_session: Session, make_runner: Make
) -> None:
    broken_final = tool_call_message(FINAL_TOOL, {"text": 123}, "f1")
    parts = make_runner([LAPTOP_INTENT], [broken_final, final_call(text="Xin lỗi, sửa lại.")])

    final = (await collect(parts.runner, "tìm laptop dưới 30 triệu"))[-1]

    assert isinstance(final, FinalEvent) and final.text == "Xin lỗi, sửa lại."


async def test_a_failed_tool_call_can_be_retried_and_succeed(
    db_session: Session, make_runner: Make
) -> None:
    make_laptops(db_session)
    bad = tool_call_message("search_catalog", {"category": "laptop", "limit": 99}, "c1")
    parts = make_runner([LAPTOP_INTENT], [bad, SEARCH, final_call()])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert [e.ok for e in ends] == [False, True]
    assert "limit" in ends[0].summary
    assert isinstance(events[-1], FinalEvent)


async def test_same_tool_failing_twice_stops_the_loop_and_synthesizes(
    db_session: Session, make_runner: Make
) -> None:
    make_laptops(db_session)
    unknown = tool_call_message("get_product_detail", {"product_id": 999_999}, "c1")
    unknown2 = tool_call_message("get_product_detail", {"product_id": 888_888}, "c2")
    synth = FinalAnswer(text="Không lấy được chi tiết sản phẩm.")
    parts = make_runner([LAPTOP_INTENT], [unknown, unknown2, synth, final_call()])

    events = await collect(parts.runner, "chi tiết sản phẩm 999999")

    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert [e.ok for e in ends] == [False, False]
    final = events[-1]
    assert isinstance(final, FinalEvent) and final.text == "Không lấy được chi tiết sản phẩm."
    assert len(parts.executor.calls) == 3  # dừng sau lần lỗi thứ hai, không gọi tiếp
    assert "liên tục lỗi" in str(parts.executor.calls[-1][-1].content)


async def test_system_error_inside_a_tool_becomes_a_failed_tool_end(
    db_session: Session, make_runner: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.catalog_service import CatalogService

    def boom(self: object, filters: object) -> None:
        raise RuntimeError("DB sập")

    monkeypatch.setattr(CatalogService, "search", boom)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(text="Tạm thời lỗi.")])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    end = next(e for e in events if isinstance(e, ToolEndEvent))
    assert end.ok is False and end.summary == "Lỗi hệ thống khi chạy tool"
    assert "DB sập" not in end.summary
    assert isinstance(events[-1], FinalEvent)


async def test_unknown_tool_name_is_reported_to_the_llm(
    db_session: Session, make_runner: Make
) -> None:
    ghost = tool_call_message("delete_everything", {}, "c1")
    parts = make_runner([LAPTOP_INTENT], [ghost, final_call()])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    end = next(e for e in events if isinstance(e, ToolEndEvent))
    assert (end.ok, end.summary) == (False, "Không có tool delete_everything")


async def test_final_answer_in_the_same_message_as_a_tool_is_ignored(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    early = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_catalog", "args": {"category": "laptop"}, "id": "c1"},
            {"name": FINAL_TOOL, "args": {"text": "bịa", "product_ids": [1]}, "id": "f0"},
        ],
    )
    parts = make_runner(
        [LAPTOP_INTENT], [early, final_call(text="Đã xem kết quả.", product_ids=ids(products))]
    )

    events = await collect(parts.runner, "tìm laptop")

    final = events[-1]
    assert isinstance(final, FinalEvent) and final.text == "Đã xem kết quả."
    replies = [m for m in parts.executor.calls[1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in replies] == ["c1", "f0"]
    assert "FINAL_TOO_EARLY" in str(replies[1].content)


async def test_plain_text_reply_falls_back_to_structured_final_answer(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    synth = FinalAnswer(text="Đây là kết quả.", product_ids=ids(products)[:1])
    parts = make_runner([LAPTOP_INTENT], [SEARCH, AIMessage(content="Xong rồi nhé"), synth])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    final = events[-1]
    assert isinstance(final, FinalEvent) and len(final.table) == 1
    assert "FinalAnswer" in str(parts.executor.calls[-1][-1].content)


# ---- tool ghi ----
async def test_write_tool_is_blocked_when_the_user_did_not_ask(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    sneaky = tool_call_message("add_to_shopping_list", {"product_id": products[0].id}, "c1")
    alert = tool_call_message(
        "create_price_alert", {"product_id": products[0].id, "target_price": 1}, "c2"
    )
    parts = make_runner([LAPTOP_INTENT], [sneaky, alert, final_call()])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert [e.ok for e in ends] == [False, False]
    assert "chưa yêu cầu rõ ràng" in ends[0].summary
    assert ShoppingListService(db_session, now=clock).list_lists() == []
    db_session.expire_all()
    assert db_session.exec(select(ShoppingListItem)).all() == []


async def test_write_tool_runs_when_the_user_asks_explicitly(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    add = tool_call_message("add_to_shopping_list", {"product_id": products[1].id}, "c1")
    parts = make_runner(
        [{"plan_steps": ["Thêm vào danh sách"]}], [add, final_call(text="Đã thêm.")]
    )

    events = await collect(parts.runner, f"thêm máy id {products[1].id} vào danh sách mua")

    end = next(e for e in events if isinstance(e, ToolEndEvent))
    assert end.ok and end.summary.startswith("Đã thêm vào danh sách")
    (lst,) = ShoppingListService(db_session, now=clock).list_lists()
    assert lst.item_count == 1 and lst.total_price == 25_000_000


# ---- hỏi lại và lỗi LLM ----
async def test_ambiguous_request_asks_once_and_calls_no_tool(
    db_session: Session, make_runner: Make
) -> None:
    parts = make_runner(
        [{"needs_clarification": True, "clarification_question": "Bạn cần gì?"}], []
    )

    events = await collect(parts.runner, "tìm cái nào rẻ rẻ")

    assert names(events) == ["plan", "clarification"]
    assert isinstance(events[1], ClarificationEvent) and events[1].question == "Bạn cần gì?"
    assert parts.executor.calls == []
    run = stored_run(db_session)
    assert (run.status, run.tool_calls) == (AgentRunStatus.needs_clarification, 0)
    last = stored_messages(db_session)[-1]
    assert (last.role, last.content, last.payload) == (MessageRole.assistant, "Bạn cần gì?", None)


async def test_planner_failure_ends_with_llm_unavailable(
    db_session: Session, make_runner: Make
) -> None:
    parts = make_runner([TimeoutError("quá hạn")], [])

    events = await collect(parts.runner, "tìm laptop")

    assert names(events) == ["error"]
    error = events[0]
    assert isinstance(error, ErrorEvent) and error.code == "LLM_UNAVAILABLE"
    assert stored_run(db_session).status is AgentRunStatus.failed


async def test_executor_failure_ends_with_llm_unavailable_after_the_plan(
    db_session: Session, make_runner: Make
) -> None:
    parts = make_runner([LAPTOP_INTENT], [TimeoutError("quá hạn")])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    assert names(events) == ["plan", "error"]
    assert isinstance(events[-1], ErrorEvent) and events[-1].code == "LLM_UNAVAILABLE"
    assert "quá hạn" not in events[-1].message


async def test_unexpected_exception_is_reported_without_leaking_details(
    db_session: Session, make_runner: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import catalog_service

    def boom(self: object, ids: object) -> None:
        raise RuntimeError("mật khẩu=hunter2")

    monkeypatch.setattr(catalog_service.CatalogService, "rows", boom)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call()])

    events = await collect(parts.runner, "tìm laptop dưới 30 triệu")

    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.code == "INTERNAL_ERROR"
    assert "hunter2" not in error.message
    assert stored_run(db_session).status is AgentRunStatus.failed


# ---- hội thoại nhiều lượt ----
async def test_second_turn_resolves_ordinal_references_from_the_previous_table(
    db_session: Session, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    first_ids = ids(products)
    turn1 = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=first_ids)])
    events1 = await collect(turn1.runner, "tìm laptop dưới 30 triệu")
    conversation_id = stored_run(db_session).conversation_id
    assert isinstance(events1[-1], FinalEvent)

    add = tool_call_message("add_to_shopping_list", {"product_id": first_ids[1]}, "c1")
    turn2 = make_runner(
        [{"plan_steps": ["Thêm máy thứ 2 vào danh sách"]}], [add, final_call(text="Đã thêm.")]
    )
    events2 = await collect(turn2.runner, "thêm máy thứ 2 vào danh sách mua", conversation_id)

    human = turn2.executor.calls[0][-1]
    assert f"1) id={first_ids[0]}" in str(human.content)
    assert f"2) id={first_ids[1]}" in str(human.content)
    contents = [str(m.content) for m in turn2.executor.calls[0] if isinstance(m, AIMessage)]
    assert contents == ["Có laptop phù hợp."]  # lịch sử lượt trước được đưa vào
    assert "tìm laptop dưới 30 triệu" in str(turn2.planner.calls[0][-1].content)
    end = next(e for e in events2 if isinstance(e, ToolEndEvent))
    assert end.ok
    (lst,) = ShoppingListService(db_session, now=clock).list_lists()
    detail = ShoppingListService(db_session, now=clock).get_list(lst.list_id)
    assert [item.product_id for item in detail.items] == [first_ids[1]]


async def test_first_turn_has_no_reference_block(db_session: Session, make_runner: Make) -> None:
    parts = make_runner([LAPTOP_INTENT], [final_call()])
    await collect(parts.runner, "tìm laptop")
    assert "Kết quả gần nhất" not in str(parts.executor.calls[0][-1].content)


# ---- start() ----
async def test_start_rejects_empty_and_overlong_messages(
    db_session: Session, make_runner: Make
) -> None:
    runner = make_runner([], []).runner
    for text in ("", "   ", "x" * 1001):
        with pytest.raises(ValidationFailed):
            await runner.start(text)


async def test_start_with_unknown_conversation_raises_not_found(
    db_session: Session, make_runner: Make
) -> None:
    with pytest.raises(NotFound):
        await make_runner([], []).runner.start("tìm laptop", conversation_id=999_999)


async def test_start_creates_conversation_titled_with_the_first_message(
    db_session: Session, make_runner: Make
) -> None:
    runner = make_runner([], []).runner

    handle = await runner.start("tìm laptop gaming " + "x" * 100)

    run = stored_run(db_session)
    assert run.id == handle.run_id and run.status is AgentRunStatus.running
    assert run.events == []
    assert handle.context.history == [] and handle.context.last_results == []
