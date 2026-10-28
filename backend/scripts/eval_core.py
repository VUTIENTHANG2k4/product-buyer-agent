"""Lõi của `make eval`: nạp câu hỏi, chấm điểm theo docs/05 §7, viết báo cáo Markdown.

Không gọi LLM hay CSDL; việc chạy agent nằm ở `scripts.run_eval`. Nhờ vậy phần chấm điểm có test
bằng kết quả dựng sẵn (xem `tests/unit/test_eval_core.py`).
"""

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

QUERIES_FILE: Final = Path(__file__).resolve().parents[2] / "docs" / "eval" / "queries.yaml"

# Ngưỡng đạt (docs/05 §7). `hallucination` và `crashed_cases` là số ca vi phạm (phải bằng 0).
THRESHOLDS: Final[Mapping[str, float]] = {
    "intent_accuracy": 0.90,
    "constraint_satisfaction": 0.95,
    "hallucination": 0,
    "crashed_cases": 0,
    "clarification": 1.0,
    "tool_correctness": 0.90,
    "latency_p50_s": 15.0,
}

Op = Literal["eq", "lte", "gte", "in", "contains", "contains_any"]


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: Op
    value: Any

    @model_validator(mode="after")
    def _numeric_operators_need_numbers(self) -> Self:
        """`lte`/`gte` với giá trị chuỗi làm cả lượt eval chết giữa chừng (TypeError khi chấm)."""
        if self.op in ("lte", "gte") and not isinstance(self.value, int | float):
            raise ValueError(f"toán tử {self.op} cần giá trị số, nhận {self.value!r}")
        return self


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: dict[str, Any] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)
    min_results: int | None = None
    tools_required: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    """Một câu trong `docs/eval/queries.yaml`; khóa lạ là lỗi để không gõ nhầm kỳ vọng."""

    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    context: list[str] = Field(default_factory=list)
    expect_clarification: bool = False
    expected: Expected = Field(default_factory=Expected)


def load_cases(path: Path = QUERIES_FILE, only: Sequence[str] = ()) -> list[EvalCase]:
    """Nạp câu hỏi; `only` (danh sách id) lọc bớt và báo lỗi nếu có id không tồn tại."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError(f"{path.name} phải có mục `cases` là danh sách không rỗng")
    cases = [EvalCase.model_validate(item) for item in data["cases"]]
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("queries.yaml có id trùng")
    if only:
        unknown = sorted(set(only) - set(ids))
        if unknown:
            raise ValueError(f"không có câu hỏi: {', '.join(unknown)}")
        wanted = set(only)
        cases = [case for case in cases if case.id in wanted]
    return cases


@dataclass(frozen=True)
class ProductFacts:
    """Thông tin một sản phẩm trong bảng kết quả, đọc từ CSDL, để kiểm `constraints`."""

    product_id: int
    brand: str
    min_price: int | None
    sites: frozenset[str]
    specs: Mapping[str, Any]


@dataclass
class CaseRun:
    """Những gì quan sát được khi chạy một câu hỏi."""

    intent: dict[str, Any] | None = None
    tools_called: list[str] = field(default_factory=list)
    products: list[ProductFacts] = field(default_factory=list)
    clarification: str | None = None
    final_text: str | None = None
    error_code: str | None = None
    latency_s: float | None = None
    dropped_product_ids: list[int] = field(default_factory=list)
    dropped_live_urls: list[str] = field(default_factory=list)
    price_warnings: list[int] = field(default_factory=list)
    crashed: str | None = None  # ngoại lệ ngoài dự kiến của harness/agent


# ---- chấm điểm từng ca ----
@dataclass(frozen=True)
class FieldCheck:
    name: str
    expected: Any
    actual: Any
    ok: bool


def _norm(value: Any) -> Any:
    if isinstance(value, list | tuple | set | frozenset):
        return sorted(str(item).lower() for item in value)
    if isinstance(value, str):
        return value.lower()
    return value


def check_intent(case: EvalCase, intent: Mapping[str, Any] | None) -> list[FieldCheck]:
    """So từng trường `expected.intent` đã khai báo với `QueryIntent` thực tế."""
    checks: list[FieldCheck] = []
    for name, expected in case.expected.intent.items():
        actual = None if intent is None else intent.get(name)
        checks.append(FieldCheck(name, expected, actual, _norm(expected) == _norm(actual)))
    return checks


def _resolve(facts: ProductFacts, field_name: str) -> Any:
    if field_name == "min_price":
        return facts.min_price
    if field_name == "brand":
        return facts.brand
    if field_name == "site":
        return sorted(facts.sites)
    if field_name.startswith("spec."):
        return facts.specs.get(field_name[5:])
    raise ValueError(f"ràng buộc chưa hỗ trợ: {field_name}")


def satisfies(facts: ProductFacts, constraint: Constraint) -> bool:
    """Sản phẩm thỏa một ràng buộc? Giá trị thiếu (None) luôn là không thỏa."""
    actual = _resolve(facts, constraint.field)
    if actual is None:
        return False
    expected, op = constraint.value, constraint.op
    if op in ("lte", "gte"):
        if isinstance(actual, bool) or not isinstance(actual, int | float):
            return False
        return bool(actual <= expected if op == "lte" else actual >= expected)
    left, right = _norm(actual), _norm(expected)
    if op == "eq":
        return bool(left == right)
    if op == "in":
        wanted = set(right if isinstance(right, list) else [right])
        have = left if isinstance(left, list) else [left]
        return any(item in wanted for item in have)
    wanted_items = set(right if isinstance(right, list) else [right])
    have_items = set(left if isinstance(left, list) else [left])
    if op == "contains":
        return wanted_items <= have_items
    return bool(wanted_items & have_items)  # contains_any


@dataclass(frozen=True)
class CaseScore:
    case: EvalCase
    run: CaseRun
    intent_checks: list[FieldCheck]
    products_checked: int  # số sản phẩm đã kiểm ràng buộc (0 nếu câu không có ràng buộc)
    products_satisfying: int
    min_results_ok: bool | None
    clarification_ok: bool | None
    tools_ok: bool | None
    hallucinated: bool

    @property
    def passed(self) -> bool:
        """Đạt khi mọi kiểm tra áp dụng đều đúng và lượt chạy không lỗi/crash."""
        optional = (self.min_results_ok, self.clarification_ok, self.tools_ok)
        return (
            all(check is not False for check in optional)
            and self.products_checked == self.products_satisfying
            and all(check.ok for check in self.intent_checks)
            and not self.hallucinated
            and self.run.crashed is None
            and self.run.error_code is None
        )


def score_case(case: EvalCase, run: CaseRun) -> CaseScore:
    expected = case.expected
    checked = satisfying = 0
    if expected.constraints:
        for facts in run.products:
            checked += 1
            if all(satisfies(facts, constraint) for constraint in expected.constraints):
                satisfying += 1

    called = set(run.tools_called)
    tools_ok: bool | None = None
    if case.expect_clarification:
        clarification_ok: bool | None = run.clarification is not None and not run.tools_called
    else:
        clarification_ok = None
        if expected.tools_required or expected.tools_forbidden:
            # Hỏi lại là phản hồi chấp nhận được khi câu chỉ cấm tool (ví dụ S01 tấn công prompt);
            # câu đòi tool bắt buộc thì phải thật sự gọi tool.
            tools_ok = (
                (run.clarification is None or not expected.tools_required)
                and set(expected.tools_required) <= called
                and not (set(expected.tools_forbidden) & called)
            )

    return CaseScore(
        case=case,
        run=run,
        intent_checks=check_intent(case, run.intent) if expected.intent else [],
        products_checked=checked,
        products_satisfying=satisfying,
        min_results_ok=(
            None if expected.min_results is None else len(run.products) >= expected.min_results
        ),
        clarification_ok=clarification_ok,
        tools_ok=tools_ok,
        hallucinated=bool(run.dropped_product_ids or run.dropped_live_urls)
        or run.error_code == "AGENT_HALLUCINATION",
    )


# ---- tổng hợp ----
@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    value: float | None  # None: không có ca nào để đo
    detail: str
    ok: bool | None

    @property
    def threshold(self) -> float:
        return THRESHOLDS[self.key]


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def compute_metrics(scores: Sequence[CaseScore]) -> list[Metric]:
    fields_total = sum(len(s.intent_checks) for s in scores)
    fields_ok = sum(check.ok for s in scores for check in s.intent_checks)
    checked = sum(s.products_checked for s in scores)
    satisfying = sum(s.products_satisfying for s in scores)
    clarif = [s for s in scores if s.clarification_ok is not None]
    tools = [s for s in scores if s.tools_ok is not None]
    latencies = [
        s.run.latency_s for s in scores if s.run.latency_s is not None and s.run.final_text
    ]
    bad = [s.case.id for s in scores if s.hallucinated]
    crashed = [s.case.id for s in scores if s.run.crashed]

    intent = _ratio(fields_ok, fields_total)
    constraint = _ratio(satisfying, checked)
    clarification = _ratio(sum(bool(s.clarification_ok) for s in clarif), len(clarif))
    tool = _ratio(sum(bool(s.tools_ok) for s in tools), len(tools))
    p50 = statistics.median(latencies) if latencies else None
    return [
        Metric(
            "intent_accuracy",
            "Intent accuracy",
            intent,
            f"{fields_ok}/{fields_total} trường",
            None if intent is None else intent >= THRESHOLDS["intent_accuracy"],
        ),
        Metric(
            "constraint_satisfaction",
            "Constraint satisfaction",
            constraint,
            f"{satisfying}/{checked} sản phẩm",
            None if constraint is None else constraint >= THRESHOLDS["constraint_satisfaction"],
        ),
        Metric(
            "hallucination",
            "Hallucination (số ca)",
            float(len(bad)),
            ", ".join(bad) or "không có",
            len(bad) == 0,
        ),
        Metric(
            "clarification",
            "Clarification",
            clarification,
            f"{sum(bool(s.clarification_ok) for s in clarif)}/{len(clarif)} ca",
            None if clarification is None else clarification >= THRESHOLDS["clarification"],
        ),
        Metric(
            "tool_correctness",
            "Tool correctness",
            tool,
            f"{sum(bool(s.tools_ok) for s in tools)}/{len(tools)} ca",
            None if tool is None else tool >= THRESHOLDS["tool_correctness"],
        ),
        # Ca crash không có câu trả lời nên không vào chỉ số nào khác: nếu thiếu dòng này, eval mà
        # mọi ca crash vẫn "đạt" vì không còn chỉ số nào đo được (BUG-M6-17).
        Metric(
            "crashed_cases",
            "Ca lỗi ngoài dự kiến",
            float(len(crashed)),
            ", ".join(crashed) or "không có",
            len(crashed) == 0,
        ),
        Metric(
            "latency_p50_s",
            "Latency p50 (giây)",
            p50,
            f"{len(latencies)} ca có câu trả lời",
            None if p50 is None else p50 <= THRESHOLDS["latency_p50_s"],
        ),
    ]


def all_thresholds_met(metrics: Iterable[Metric]) -> bool:
    return all(metric.ok is not False for metric in metrics)


# ---- báo cáo ----
def _mark(value: bool | None) -> str:
    return "–" if value is None else ("✅" if value else "❌")


def _format_metric(metric: Metric) -> str:
    if metric.value is None:
        return "–"
    if metric.key in {"hallucination", "crashed_cases"}:
        return str(int(metric.value))
    if metric.key == "latency_p50_s":
        return f"{metric.value:.1f}"
    return f"{metric.value * 100:.1f}%"


def _threshold_text(metric: Metric) -> str:
    if metric.key in {"hallucination", "crashed_cases"}:
        return "= 0"
    if metric.key == "latency_p50_s":
        return "≤ 15"
    return f"≥ {metric.threshold * 100:.0f}%"


def _failure_lines(score: CaseScore) -> list[str]:
    run, lines = score.run, []
    if run.crashed:
        lines.append(f"- Harness/agent lỗi ngoài dự kiến: `{run.crashed}`")
    if run.error_code:
        lines.append(f"- Sự kiện lỗi: `{run.error_code}`")
    for check in score.intent_checks:
        if not check.ok:
            lines.append(
                f"- Intent `{check.name}`: mong đợi `{check.expected}`, nhận `{check.actual}`"
            )
    if score.products_checked != score.products_satisfying:
        lines.append(
            f"- Ràng buộc: {score.products_checked - score.products_satisfying}"
            f"/{score.products_checked} sản phẩm không thỏa"
        )
    if score.min_results_ok is False:
        lines.append(
            f"- Số kết quả {len(run.products)} < tối thiểu {score.case.expected.min_results}"
        )
    if score.clarification_ok is False:
        lines.append(
            "- Cần hỏi lại không gọi tool: "
            + (f"đã hỏi {run.clarification!r}" if run.clarification else "không hỏi lại")
            + (f", đã gọi tool {run.tools_called}" if run.tools_called else "")
        )
    if score.tools_ok is False:
        lines.append(
            f"- Tool: cần {score.case.expected.tools_required}, "
            f"cấm {score.case.expected.tools_forbidden}, đã gọi {run.tools_called}"
            + (f", lại hỏi lại ({run.clarification!r})" if run.clarification else "")
        )
    if score.hallucinated:
        lines.append(
            f"- Hallucination: id bị loại {run.dropped_product_ids}, link bị loại "
            f"{run.dropped_live_urls}"
        )
    if run.price_warnings:
        lines.append(f"- Cảnh báo: số tiền trong câu trả lời lệch CSDL {run.price_warnings}")
    return lines


def render_report(
    scores: Sequence[CaseScore],
    metrics: Sequence[Metric],
    *,
    today: date,
    provider: str,
    model: str,
    partial: bool,
    rpm: int = 0,
) -> str:
    passed = sum(score.passed for score in scores)
    out = [
        f"# Báo cáo eval agent — {today.isoformat()}",
        "",
        f"- Nhà cung cấp / model: `{provider}` / `{model}`",
        f"- Số câu: {len(scores)} ({passed} đạt toàn bộ)"
        + (" — **chạy một phần**" if partial else ""),
        "- Dữ liệu: seed `eval` (hư cấu) nạp trong transaction riêng và hoàn tác sau khi chạy",
        *(
            [
                f"- Giới hạn {rpm} lần gọi LLM/phút: **độ trễ bị kéo dài** (mỗi lần gọi chờ tối "
                f"thiểu {60 / rpm:.0f} giây), chỉ số latency không phản ánh tốc độ thật của model"
            ]
            if rpm
            else []
        ),
        "",
        "## Chỉ số",
        "",
        "| Chỉ số | Giá trị | Ngưỡng | Đạt | Chi tiết |",
        "| --- | --- | --- | --- | --- |",
    ]
    for metric in metrics:
        out.append(
            f"| {metric.label} | {_format_metric(metric)} | {_threshold_text(metric)} "
            f"| {_mark(metric.ok)} | {metric.detail} |"
        )
    out += [
        "",
        "## Từng câu",
        "",
        "| ID | Câu hỏi | Kết quả | Intent | RB | Tool | Hỏi lại | Số KQ | Giây |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for score in scores:
        intent_ok = None if not score.intent_checks else all(c.ok for c in score.intent_checks)
        constraint_ok = (
            None
            if score.products_checked == 0
            else (score.products_checked == score.products_satisfying)
        )
        latency = "" if score.run.latency_s is None else f"{score.run.latency_s:.1f}"
        query = " ".join(score.case.query.split()).replace("|", "\\|")
        out.append(
            f"| {score.case.id} | {query} | {_mark(score.passed)} | {_mark(intent_ok)} "
            f"| {_mark(constraint_ok)} | {_mark(score.tools_ok)} | {_mark(score.clarification_ok)} "
            f"| {len(score.run.products)} | {latency} |"
        )
    failed = [score for score in scores if not score.passed or score.run.price_warnings]
    if failed:
        out += ["", "## Chi tiết ca chưa đạt", ""]
        for score in failed:
            out += [f"### {score.case.id} — {score.case.query}", "", *_failure_lines(score), ""]
            if score.run.final_text:
                out += [f"> {score.run.final_text[:300].replace(chr(10), ' ')}", ""]
    return "\n".join(out).rstrip() + "\n"


def report_path(directory: Path, today: date, *, partial: bool) -> Path:
    suffix = "-partial" if partial else ""
    return directory / f"eval-{today.isoformat()}{suffix}.md"
