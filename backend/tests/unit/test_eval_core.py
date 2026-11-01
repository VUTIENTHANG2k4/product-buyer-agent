"""T6.6: nạp queries.yaml, chấm điểm theo docs/05 §7 và viết báo cáo (không gọi LLM/CSDL)."""

from datetime import date
from pathlib import Path

import pytest

from scripts.eval_core import (
    THRESHOLDS,
    CaseRun,
    Constraint,
    EvalCase,
    Expected,
    ProductFacts,
    all_thresholds_met,
    check_intent,
    compute_metrics,
    load_cases,
    render_report,
    report_path,
    satisfies,
    score_case,
)


def facts(**overrides: object) -> ProductFacts:
    data: dict[str, object] = {
        "product_id": 1,
        "brand": "ASUS",
        "min_price": 25_000_000,
        "sites": frozenset({"gearvn", "fptshop"}),
        "specs": {"gpu_rank": 40, "ram_gb": 16, "connection": ["wired", "bluetooth"], "rgb": True},
    }
    data.update(overrides)
    return ProductFacts(**data)  # type: ignore[arg-type]


def case(**fields: object) -> EvalCase:
    return EvalCase.model_validate({"id": "X1", "query": "câu hỏi", **fields})


# ---- nạp câu hỏi ----
def test_real_queries_file_loads_with_at_least_thirty_unique_cases() -> None:
    cases = load_cases()
    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases)
    assert any(c.expect_clarification for c in cases) and any(c.context for c in cases)


def test_only_filters_cases_and_unknown_id_is_an_error() -> None:
    assert [c.id for c in load_cases(only=["C02", "L01"])] == ["L01", "C02"]
    with pytest.raises(ValueError, match="ZZZ"):
        load_cases(only=["L01", "ZZZ"])


def test_unknown_keys_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    typo = tmp_path / "typo.yaml"
    typo.write_text("cases:\n  - {id: A, query: q, expected: {tool_required: [x]}}\n", "utf-8")
    dup = tmp_path / "dup.yaml"
    dup.write_text("cases:\n  - {id: A, query: q}\n  - {id: A, query: r}\n", "utf-8")
    with pytest.raises(ValueError):
        load_cases(typo)
    with pytest.raises(ValueError, match="trùng"):
        load_cases(dup)


# ---- ràng buộc ----
@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("min_price", "lte", 30_000_000, True),
        ("min_price", "lte", 20_000_000, False),
        ("min_price", "gte", 25_000_000, True),
        ("spec.gpu_rank", "gte", 40, True),
        ("spec.gpu_rank", "gte", 50, False),
        ("spec.ram_gb", "eq", 16, True),
        ("spec.rgb", "eq", True, True),
        ("spec.rgb", "eq", False, False),
        ("brand", "in", ["ASUS", "Lenovo"], True),
        ("brand", "in", ["asus"], True),  # không phân biệt hoa/thường
        ("brand", "in", ["Dell"], False),
        ("brand", "eq", "ASUS", True),
        ("site", "in", ["gearvn"], True),
        ("site", "in", ["anphat"], False),
        ("spec.connection", "contains_any", ["bluetooth", "wireless_2_4"], True),
        ("spec.connection", "contains_any", ["wireless_2_4"], False),
        ("spec.connection", "contains", "wired", True),
        ("spec.weight_g", "lte", 70, False),  # thiếu thông số = không thỏa
        ("spec.gpu_rank", "lte", True, False),
    ],
)
def test_constraint_operators(field: str, op: str, value: object, expected: bool) -> None:
    constraint = Constraint.model_validate({"field": field, "op": op, "value": value})
    assert satisfies(facts(), constraint) is expected


def test_boolean_spec_is_not_treated_as_a_number() -> None:
    constraint = Constraint(field="spec.rgb", op="gte", value=0)
    assert satisfies(facts(), constraint) is False


def test_missing_price_never_satisfies() -> None:
    assert not satisfies(facts(min_price=None), Constraint(field="min_price", op="lte", value=1))


def test_unsupported_constraint_field_raises() -> None:
    with pytest.raises(ValueError, match="color"):
        satisfies(facts(), Constraint(field="color", op="eq", value="red"))


# ---- intent ----
def test_intent_compares_only_declared_fields_with_loose_text_and_sets() -> None:
    c = case(expected={"intent": {"category": "laptop", "tier": 1, "sites": ["gearvn", "fptshop"]}})
    actual = {
        "category": "laptop",
        "tier": 1,
        "sites": ["fptshop", "gearvn"],
        "price_max": 99,
    }
    assert [x.ok for x in check_intent(c, actual)] == [True, True, True]
    wrong = {"category": "mouse", "tier": 1, "sites": []}
    assert [x.ok for x in check_intent(c, wrong)] == [False, True, False]
    assert not any(x.ok for x in check_intent(c, None))


# ---- chấm ca ----
def test_search_case_passes_when_everything_matches() -> None:
    c = case(
        expected={
            "intent": {"category": "laptop"},
            "constraints": [{"field": "min_price", "op": "lte", "value": 30_000_000}],
            "min_results": 1,
            "tools_required": ["search_catalog"],
            "tools_forbidden": ["create_price_alert"],
        }
    )
    run = CaseRun(
        intent={"category": "laptop"},
        tools_called=["search_catalog"],
        products=[facts()],
        final_text="ok",
        latency_s=3.0,
    )

    score = score_case(c, run)

    assert score.passed and (score.products_checked, score.products_satisfying) == (1, 1)
    assert score.tools_ok and score.min_results_ok and score.clarification_ok is None


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        (
            CaseRun(tools_called=["search_catalog", "create_price_alert"], final_text="x"),
            "forbidden",
        ),
        (CaseRun(tools_called=[], final_text="x"), "missing"),
        (CaseRun(tools_called=["search_catalog"], clarification="hỏi?"), "asked"),
        (
            CaseRun(tools_called=["search_catalog"], final_text="x", error_code="AGENT_STEP_LIMIT"),
            "e",
        ),
        (CaseRun(tools_called=["search_catalog"], crashed="RuntimeError: x"), "crash"),
        (
            CaseRun(tools_called=["search_catalog"], final_text="x", dropped_product_ids=[9]),
            "hallucination",
        ),
    ],
)
def test_case_fails_for_each_kind_of_problem(run: CaseRun, reason: str) -> None:
    c = case(
        expected={"tools_required": ["search_catalog"], "tools_forbidden": ["create_price_alert"]}
    )
    assert score_case(c, run).passed is False, reason


def test_constraint_violations_and_min_results_are_counted() -> None:
    c = case(
        expected={
            "constraints": [{"field": "spec.ram_gb", "op": "gte", "value": 32}],
            "min_results": 2,
        }
    )
    run = CaseRun(products=[facts(), facts(specs={"ram_gb": 32})], final_text="x")

    score = score_case(c, run)

    assert (score.products_checked, score.products_satisfying) == (2, 1)
    assert score.min_results_ok is True and score.passed is False
    assert score_case(c, CaseRun(products=[facts()])).min_results_ok is False


def test_clarification_case_needs_a_question_and_no_tools() -> None:
    c = case(expect_clarification=True)
    assert score_case(c, CaseRun(clarification="Bạn cần gì?")).passed
    assert not score_case(c, CaseRun(clarification="?", tools_called=["search_catalog"])).passed
    assert not score_case(c, CaseRun(final_text="đây là kết quả")).passed


def test_blocked_guardrail_error_counts_as_hallucination() -> None:
    run = CaseRun(error_code="AGENT_HALLUCINATION")
    assert score_case(case(), run).hallucinated is True


# ---- chỉ số ----
def metrics_of(*pairs: tuple[EvalCase, CaseRun]) -> dict[str, tuple[float | None, bool | None]]:
    scores = [score_case(c, r) for c, r in pairs]
    return {m.key: (m.value, m.ok) for m in compute_metrics(scores)}


def test_metrics_aggregate_per_field_product_and_case() -> None:
    intent_case = case(id="A", expected={"intent": {"category": "laptop", "tier": 1}})
    wrong_tier = CaseRun(intent={"category": "laptop", "tier": 2}, final_text="x", latency_s=10.0)
    constraint_case = case(
        id="B", expected={"constraints": [{"field": "min_price", "op": "lte", "value": 30_000_000}]}
    )
    two_products = CaseRun(
        products=[facts(), facts(min_price=40_000_000)], final_text="x", latency_s=20.0
    )
    ask = case(id="C", expect_clarification=True)
    asked = CaseRun(clarification="?")
    tool_case = case(id="D", expected={"tools_required": ["list_alerts"]})
    called = CaseRun(tools_called=["list_alerts"], final_text="x", latency_s=30.0)

    result = metrics_of(
        (intent_case, wrong_tier),
        (constraint_case, two_products),
        (ask, asked),
        (tool_case, called),
    )

    assert result["intent_accuracy"] == (0.5, False)
    assert result["constraint_satisfaction"] == (0.5, False)
    assert result["hallucination"] == (0.0, True)
    assert result["clarification"] == (1.0, True)
    assert result["tool_correctness"] == (1.0, True)
    assert result["latency_p50_s"] == (20.0, False)


def test_metrics_without_applicable_cases_are_unmeasured_not_failed() -> None:
    result = metrics_of((case(), CaseRun(final_text="x")))
    assert result["intent_accuracy"] == (None, None)
    assert result["constraint_satisfaction"] == (None, None)
    assert result["clarification"] == (None, None)
    assert all_thresholds_met(compute_metrics([score_case(case(), CaseRun(final_text="x"))]))


def test_hallucination_metric_names_the_cases() -> None:
    metrics = compute_metrics(
        [score_case(case(id="L07"), CaseRun(dropped_product_ids=[1], final_text="x"))]
    )
    hallucination = next(m for m in metrics if m.key == "hallucination")
    assert (hallucination.value, hallucination.ok, hallucination.detail) == (1.0, False, "L07")
    assert not all_thresholds_met(metrics)


def test_thresholds_match_docs_05() -> None:
    assert THRESHOLDS["intent_accuracy"] == 0.90 and THRESHOLDS["constraint_satisfaction"] == 0.95
    assert THRESHOLDS["hallucination"] == 0 and THRESHOLDS["clarification"] == 1.0
    assert THRESHOLDS["tool_correctness"] == 0.90 and THRESHOLDS["latency_p50_s"] == 15.0


# ---- báo cáo ----
def test_report_lists_metrics_cases_and_failure_details() -> None:
    good = (
        case(id="L01", query="laptop | gaming", expected={"tools_required": ["search_catalog"]}),
        CaseRun(tools_called=["search_catalog"], final_text="ok", latency_s=4.2),
    )
    bad = (
        case(id="Q01", query="rẻ rẻ", expect_clarification=True),
        CaseRun(tools_called=["search_catalog"], final_text="Đây là kết quả bịa", latency_s=2.0),
    )
    scores = [score_case(*good), score_case(*bad)]

    text = render_report(
        scores,
        compute_metrics(scores),
        today=date(2026, 10, 21),
        provider="gemini",
        model="gemini-test",
        partial=True,
    )

    assert text.startswith("# Báo cáo eval agent — 2026-10-21")
    assert "`gemini` / `gemini-test`" in text and "chạy một phần" in text
    assert "| Intent accuracy |" in text and "| Clarification | 0.0% | ≥ 100% | ❌ |" in text
    assert "| L01 | laptop \\| gaming | ✅ |" in text
    assert "### Q01 — rẻ rẻ" in text and "Cần hỏi lại không gọi tool" in text
    assert "### L01" not in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_report_path_marks_partial_runs() -> None:
    folder = Path("reports")
    assert report_path(folder, date(2026, 10, 21), partial=False) == folder / "eval-2026-10-21.md"
    assert report_path(folder, date(2026, 10, 21), partial=True) == (
        folder / "eval-2026-10-21-partial.md"
    )


def test_expected_model_defaults_are_empty() -> None:
    expected = Expected()
    assert (expected.intent, expected.constraints, expected.min_results) == ({}, [], None)
