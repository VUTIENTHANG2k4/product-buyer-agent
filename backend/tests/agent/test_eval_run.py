"""T6.6: harness chạy câu hỏi qua AgentRunner thật (model giả) và chấm điểm."""

from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from app.agent.guardrail import GuardrailOutcome
from app.agent.testing import tool_call_message
from app.agent.tools import ToolContext
from scripts.eval_core import EvalCase, ProductFacts, compute_metrics, score_case
from scripts.run_eval import make_facts_of, run_all, run_case
from tests.agent.conftest import RunnerParts
from tests.agent.test_runner import LAPTOP_INTENT, SEARCH, final_call, ids, make_laptops

Make = Callable[..., RunnerParts]

LAPTOP_CASE = EvalCase.model_validate(
    {
        "id": "L01",
        "query": "laptop dưới 30 triệu",
        "expected": {
            "intent": {"category": "laptop", "price_max": 30_000_000},
            "constraints": [
                {"field": "min_price", "op": "lte", "value": 30_000_000},
                {"field": "spec.gpu_rank", "op": "gte", "value": 40},
            ],
            "min_results": 2,
            "tools_required": ["search_catalog"],
            "tools_forbidden": ["add_to_shopping_list"],
        },
    }
)


def wire(parts: RunnerParts, tool_ctx: ToolContext) -> tuple[list[GuardrailOutcome], Any]:
    guard: list[GuardrailOutcome] = []
    parts.runner.observer = guard.append
    return guard, make_facts_of(tool_ctx.session_factory)


async def test_run_case_records_intent_tools_products_and_latency(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=ids(products)[:2])])
    guard, facts_of = wire(parts, tool_ctx)

    run = await run_case(LAPTOP_CASE, parts.runner, guard, facts_of)

    assert run.crashed is None and run.error_code is None
    assert run.intent is not None and run.intent["category"] == "laptop"
    assert run.tools_called == ["search_catalog"]
    assert [p.product_id for p in run.products] == ids(products)[:2]
    first = run.products[0]
    assert isinstance(first, ProductFacts)
    assert (first.brand, first.min_price) == ("MockBrand", 20_000_000)
    assert first.sites == {"mockshop"} and first.specs["gpu_rank"] == 40
    assert run.latency_s is not None and run.latency_s >= 0
    assert run.final_text == "Có laptop phù hợp."

    score = score_case(LAPTOP_CASE, run)
    assert score.passed and (score.products_checked, score.products_satisfying) == (2, 2)


async def test_run_case_counts_dropped_ids_as_hallucination(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    parts = make_runner(
        [LAPTOP_INTENT], [SEARCH, final_call(product_ids=[999_999, *ids(products)[:2]])]
    )
    guard, facts_of = wire(parts, tool_ctx)

    run = await run_case(LAPTOP_CASE, parts.runner, guard, facts_of)

    assert run.dropped_product_ids == [999_999]
    assert len(run.products) == 2  # người dùng chỉ thấy id thật, nhưng ca vẫn bị tính lỗi
    assert score_case(LAPTOP_CASE, run).hallucinated and not score_case(LAPTOP_CASE, run).passed


async def test_context_turns_run_first_but_only_the_last_turn_is_measured(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    case = EvalCase.model_validate(
        {
            "id": "C02",
            "query": "thêm máy thứ 2 vào danh sách mua",
            "context": ["tìm laptop dưới 30 triệu"],
            "expected": {"tools_required": ["add_to_shopping_list"]},
        }
    )
    add = tool_call_message("add_to_shopping_list", {"product_id": ids(products)[1]}, "c9")
    parts = make_runner(
        [LAPTOP_INTENT, {"plan_steps": ["Thêm vào danh sách"]}],
        [
            SEARCH,
            final_call(product_ids=[999_999, *ids(products)]),  # ngữ cảnh có id bịa
            add,
            final_call(text="Đã thêm."),
        ],
    )
    guard, facts_of = wire(parts, tool_ctx)

    run = await run_case(case, parts.runner, guard, facts_of)

    assert run.tools_called == ["add_to_shopping_list"]
    assert run.dropped_product_ids == []  # id bịa ở lượt ngữ cảnh không tính
    assert "Kết quả gần nhất" in str(parts.executor.calls[2][-1].content)
    assert score_case(case, run).passed


async def test_clarification_case_is_observed_without_tools(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    case = EvalCase.model_validate({"id": "Q01", "query": "rẻ rẻ", "expect_clarification": True})
    parts = make_runner([{"needs_clarification": True, "clarification_question": "Loại nào?"}], [])
    guard, facts_of = wire(parts, tool_ctx)

    run = await run_case(case, parts.runner, guard, facts_of)

    assert (run.clarification, run.tools_called, run.final_text) == ("Loại nào?", [], None)
    assert score_case(case, run).passed


async def test_agent_error_event_is_recorded_not_raised(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    parts = make_runner([TimeoutError("quá hạn")], [])
    guard, facts_of = wire(parts, tool_ctx)

    run = await run_case(LAPTOP_CASE, parts.runner, guard, facts_of)

    assert run.error_code == "LLM_UNAVAILABLE" and run.crashed is None
    assert not score_case(LAPTOP_CASE, run).passed


async def test_unexpected_exception_is_captured_as_crash(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    parts = make_runner([LAPTOP_INTENT], [SEARCH, final_call(product_ids=ids(products)[:1])])
    guard, _ = wire(parts, tool_ctx)

    def broken(_: list[int]) -> list[ProductFacts]:
        raise RuntimeError("hỏng facts")

    run = await run_case(LAPTOP_CASE, parts.runner, guard, broken)

    assert run.crashed == "RuntimeError: hỏng facts"
    assert not score_case(LAPTOP_CASE, run).passed


async def test_run_all_reports_progress_and_keeps_case_order(
    db_session: Session, tool_ctx: ToolContext, make_runner: Make
) -> None:
    products = make_laptops(db_session)
    second = EvalCase.model_validate({"id": "Q01", "query": "rẻ rẻ", "expect_clarification": True})
    parts = make_runner(
        [LAPTOP_INTENT, {"needs_clarification": True}],
        [SEARCH, final_call(product_ids=ids(products)[:2])],
    )
    guard, facts_of = wire(parts, tool_ctx)
    lines: list[str] = []

    runs = await run_all([LAPTOP_CASE, second], parts.runner, guard, facts_of, report=lines.append)

    assert len(runs) == 2
    assert lines[0].startswith("[1/2] L01 PASS") and lines[1].startswith("[2/2] Q01 PASS")
    metrics = {
        m.key: m.ok
        for m in compute_metrics([score_case(LAPTOP_CASE, runs[0]), score_case(second, runs[1])])
    }
    assert metrics["clarification"] is True and metrics["hallucination"] is True


def test_facts_of_with_no_ids_does_not_touch_the_database() -> None:
    def never() -> Session:
        raise AssertionError("không được mở session")

    assert make_facts_of(never)([]) == []
