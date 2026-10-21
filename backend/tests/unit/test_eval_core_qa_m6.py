"""QA M6: eval_core với dữ liệu hỏng, ca không đo được và báo cáo có ký tự lạ."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.eval_core import (
    CaseRun,
    Constraint,
    EvalCase,
    ProductFacts,
    all_thresholds_met,
    compute_metrics,
    load_cases,
    render_report,
    satisfies,
    score_case,
)


def case(**fields: object) -> EvalCase:
    return EvalCase.model_validate({"id": "Q1", "query": "câu hỏi", **fields})


def facts(**overrides: object) -> ProductFacts:
    data: dict[str, object] = {
        "product_id": 1,
        "brand": "ASUS",
        "min_price": 25_000_000,
        "sites": frozenset({"gearvn"}),
        "specs": {"gpu_rank": 40, "rgb": True, "connection": ["wired", "bluetooth"]},
    }
    data.update(overrides)
    return ProductFacts(**data)  # type: ignore[arg-type]


# ---- nạp YAML hỏng ----
@pytest.mark.parametrize(
    "content", ["", "# chỉ có chú thích\n", "cases: []\n", "cases: abc\n", "- a\n- b\n", "cases:\n"]
)
def test_queries_file_without_cases_is_a_clear_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "queries.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="cases"):
        load_cases(path)


@pytest.mark.parametrize("value", ["30000000", [1], None, {"a": 1}])
@pytest.mark.parametrize("op", ["lte", "gte"])
def test_numeric_constraint_with_a_non_number_is_rejected_when_loading(
    op: str, value: object
) -> None:
    """Trước khi sửa: TypeError giữa lượt eval, sau khi đã tốn lời gọi LLM."""
    with pytest.raises(ValidationError):
        Constraint.model_validate({"field": "min_price", "op": op, "value": value})


def test_unknown_field_in_a_constraint_is_only_found_when_scoring_a_product() -> None:
    bad = Constraint.model_validate({"field": "price", "op": "eq", "value": 1})
    with pytest.raises(ValueError, match="price"):
        satisfies(facts(), bad)


# ---- ca không thể chấm điểm ----
def test_case_that_crashed_is_never_counted_as_passed() -> None:
    c = case(expected={"constraints": [{"field": "min_price", "op": "lte", "value": 1}]})
    run = CaseRun(crashed="OperationalError: DB tắt")

    score = score_case(c, run)

    assert score.passed is False and score.products_checked == 0


@pytest.mark.xfail(
    strict=True,
    reason="BUG-M6-17: mọi ca crash nhưng chỉ số không đo được nên all_thresholds_met báo đạt",
)
def test_eval_where_every_case_crashed_does_not_meet_the_thresholds() -> None:
    c = case(expected={"constraints": [{"field": "min_price", "op": "lte", "value": 1}]})
    scores = [score_case(c, CaseRun(crashed="RuntimeError: x"))]

    assert all_thresholds_met(compute_metrics(scores)) is False


def test_missing_and_mixed_type_specs_never_satisfy_a_numeric_bound() -> None:
    odd = facts(specs={"gpu_rank": "40", "rgb": True, "nested": {"a": 1}})
    for field in ("spec.gpu_rank", "spec.rgb", "spec.nested", "spec.absent"):
        assert not satisfies(odd, Constraint(field=field, op="gte", value=0))


def test_in_and_contains_treat_a_scalar_and_a_list_alike() -> None:
    item = facts()
    assert satisfies(item, Constraint(field="spec.connection", op="contains", value="wired"))
    assert satisfies(item, Constraint(field="spec.connection", op="in", value=["bluetooth", "x"]))
    assert not satisfies(item, Constraint(field="spec.connection", op="contains", value=["usb"]))
    assert satisfies(
        item, Constraint(field="brand", op="in", value="asus")
    )  # không phân biệt hoa/thường


# ---- báo cáo ----
def test_report_with_no_scores_still_renders_every_section() -> None:
    text = render_report(
        [], compute_metrics([]), today=date(2026, 10, 21), provider="fake", model="m", partial=True
    )
    assert "Số câu: 0 (0 đạt toàn bộ)" in text and "chạy một phần" in text
    assert text.count("| – |") >= 5 and text.endswith("\n")


def test_report_keeps_one_row_per_case_even_when_the_query_has_newlines_and_pipes() -> None:
    c = case(query="dòng một\n| dòng hai\r\n\ttiếp", expected={"min_results": 1})
    run = CaseRun(final_text="trả lời\nnhiều dòng", latency_s=1.0)
    score = score_case(c, run)

    text = render_report(
        [score],
        compute_metrics([score]),
        today=date(2026, 10, 21),
        provider="p",
        model="m",
        partial=False,
    )

    rows = [line for line in text.splitlines() if line.startswith("| Q1 ")]
    assert len(rows) == 1 and "dòng một \\| dòng hai tiếp" in rows[0]
    assert "> trả lời nhiều dòng" in text


def test_hallucination_names_every_affected_case_once() -> None:
    cases = [case(id="A"), case(id="B"), case(id="C")]
    runs = [
        CaseRun(dropped_product_ids=[1, 2]),
        CaseRun(),
        CaseRun(error_code="AGENT_HALLUCINATION"),
    ]
    scores = [score_case(c, r) for c, r in zip(cases, runs, strict=True)]

    metric = next(m for m in compute_metrics(scores) if m.key == "hallucination")

    assert (metric.value, metric.detail, metric.ok) == (2.0, "A, C", False)
