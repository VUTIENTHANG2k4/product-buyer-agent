"""QA lượt việc nhỏ 7 (T6.7): mã thoát 2 của `run_eval.main` khi thiết lập hỏng, `min_results` và
`normalize_specs(allow_incomplete=)` ở các biên mà test T6.7 chưa phủ.

Test đỏ do lỗi ứng dụng giữ bằng `xfail(strict=True)` mã `BUG-S7-n`.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from app.domain.enums import Category
from scripts import eval_core, run_eval
from scripts.eval_core import CaseRun, EvalCase, ProductFacts, load_cases, score_case
from scripts.seed import SeedDataError, normalize_specs
from tests.service_support import make_settings

REAL_QUERIES = Path(__file__).resolve().parents[3] / "docs" / "eval" / "queries.yaml"
TEST_URL = "postgresql+psycopg://user:pw@127.0.0.1:5999/eval_test"


@pytest.fixture
def gemini_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(
        llm_provider="gemini", google_api_key="khoa-gia", test_database_url=TEST_URL
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)


def point_queries_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        run_eval, "load_cases", lambda only=(): eval_core.load_cases(path=path, only=only)
    )


# ---------------------------------------------------------------- mã thoát 2: queries.yaml hỏng
@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"- 1\n- 2\n",
        b"cases: []\n",
        b"cases: not-a-list\n",
        b"cases:\n  - id: X1\n",  # thiếu query
        b"cases:\n  - {id: X1, query: a}\n  - {id: X1, query: b}\n",  # trùng id
        b"cases:\n  - {id: X1, query: a, expected: {min_result: 1}}\n",  # khóa lạ (gõ nhầm)
        b"cases:\n  - {id: X1, query: a, expected: {constraints: [{field: min_price, op: lte, "
        b"value: 'rat re'}]}}\n",  # lte với chuỗi
        b"cases:\n  - {id: X1, query: a, expected: {constraints: [{field: min_price, op: ltx, "
        b"value: 1}]}}\n",  # toán tử lạ
        b"cases:\n  - {id: X1, query: \xff\xfe}\n",  # không phải UTF-8
        b"\tcases: [\n",  # tab thụt dòng: YAML lỗi
    ],
    ids=[
        "empty",
        "top-level-list",
        "no-cases",
        "cases-not-list",
        "missing-query",
        "duplicate-id",
        "unknown-key",
        "string-for-lte",
        "unknown-operator",
        "not-utf8",
        "tab-indent",
    ],
)
def test_a_malformed_queries_file_exits_with_the_setup_code_and_writes_no_report(
    gemini_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    content: bytes,
) -> None:
    queries = tmp_path / "queries.yaml"
    queries.write_bytes(content)
    point_queries_at(monkeypatch, queries)
    out = tmp_path / "out"

    code = run_eval.main(["--output-dir", str(out)])

    assert code == run_eval.EXIT_SETUP
    assert "Không chạy được" in caplog.text
    assert not out.exists()


def test_an_unknown_case_id_exits_with_the_setup_code(
    gemini_settings: None, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = run_eval.main(["--cases", "L01,ZZ99", "--output-dir", str(tmp_path / "out")])

    assert code == run_eval.EXIT_SETUP
    assert "ZZ99" in caplog.text


def test_a_missing_api_key_exits_with_the_setup_code_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(llm_provider="gemini", google_api_key="", test_database_url=TEST_URL)
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)

    def forbidden(_settings: object) -> Engine:
        raise AssertionError("không được mở DB khi thiếu khóa API")

    monkeypatch.setattr(run_eval, "_test_engine", forbidden)

    assert run_eval.main(["--output-dir", str(tmp_path)]) == run_eval.EXIT_SETUP
    assert "GOOGLE_API_KEY" in caplog.text


def test_the_fake_llm_provider_is_refused_with_the_setup_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings(llm_provider="fake", test_database_url=TEST_URL)
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)

    assert run_eval.main(["--output-dir", str(tmp_path)]) == run_eval.EXIT_SETUP


def test_a_database_not_named_test_is_refused_with_the_setup_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(
        llm_provider="gemini",
        google_api_key="khoa-gia",
        test_database_url="postgresql+psycopg://user:pw@127.0.0.1:5999/product_scraper",
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)

    assert run_eval.main(["--output-dir", str(tmp_path)]) == run_eval.EXIT_SETUP
    assert "_test" in caplog.text


@pytest.mark.parametrize(
    "url",
    ["không-phải-url", "postgresql+psycopg://", "postgresql+psycopg://u:p@127.0.0.1:abc/x_test"],
)
def test_an_unusable_test_database_url_exits_with_the_setup_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    settings = make_settings(
        llm_provider="gemini", google_api_key="khoa-gia", test_database_url=url
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)

    assert run_eval.main(["--output-dir", str(tmp_path)]) == run_eval.EXIT_SETUP


def test_a_failing_seed_exits_with_the_setup_code_and_rolls_back(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(
        llm_provider="gemini",
        google_api_key="khoa-gia",
        test_database_url=os.environ["TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise SeedDataError("laptops.json: sai khung")

    monkeypatch.setattr(run_eval, "seed_database", broken)

    code = run_eval.main(["--cases", "L01", "--output-dir", str(tmp_path / "out")])

    assert code == run_eval.EXIT_SETUP
    assert "laptops.json" in caplog.text
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- min_results của queries.yaml
def real_cases() -> list[EvalCase]:
    return load_cases(path=REAL_QUERIES)


def product_facts(index: int) -> ProductFacts:
    return ProductFacts(
        product_id=index, brand="ASUS", min_price=20_000_000, sites=frozenset({"gearvn"}), specs={}
    )


def test_every_real_case_with_constraints_declares_a_non_negative_integer_min_results() -> None:
    constrained = [case for case in real_cases() if case.expected.constraints]

    assert constrained
    assert [case.id for case in constrained if case.expected.min_results is None] == []
    assert [case.id for case in constrained if (case.expected.min_results or 0) < 0] == []


def test_a_constrained_case_with_min_results_fails_on_an_empty_table() -> None:
    case = next(c for c in real_cases() if c.expected.constraints and c.expected.min_results)

    score = score_case(case, CaseRun(products=[]))

    assert score.min_results_ok is False
    assert score.passed is False


def test_min_results_zero_passes_on_an_empty_table_but_not_on_a_non_matching_one() -> None:
    case = EvalCase.model_validate(
        {
            "id": "Z1",
            "query": "q",
            "expected": {
                "constraints": [{"field": "brand", "op": "eq", "value": "Nope"}],
                "min_results": 0,
            },
        }
    )

    assert score_case(case, CaseRun(products=[])).min_results_ok is True
    assert score_case(case, CaseRun(products=[product_facts(1)])).passed is False


def test_a_constrained_case_without_min_results_still_passes_on_an_empty_table() -> None:
    """Lỗ hổng cũ: chỉ test dữ liệu seed (không phải bộ chấm) giữ `min_results` bắt buộc."""
    case = EvalCase.model_validate(
        {
            "id": "Z2",
            "query": "q",
            "expected": {"constraints": [{"field": "brand", "op": "eq", "value": "ASUS"}]},
        }
    )

    assert score_case(case, CaseRun(products=[])).passed is True


# ---------------------------------------------------------------- normalize_specs(allow_incomplete)
@pytest.mark.parametrize(
    ("category", "raw"),
    [
        (Category.keyboard, {"hot_swap": False}),
        (Category.mouse, {"rgb": False}),
        (Category.headset, {"anc": False}),
        (Category.headset, {"has_mic": False, "anc": False}),
        (Category.mouse, {"connection": [], "rgb": False}),
        (Category.keyboard, {"switch_name": "Red"}),
        (Category.laptop, {"is_gaming": False}),
    ],
)
def test_an_incomplete_spec_whose_only_value_is_false_is_a_real_value_not_empty(
    category: Category, raw: dict[str, Any]
) -> None:
    specs = normalize_specs(category, raw, allow_incomplete=True)

    assert specs == {key: value for key, value in raw.items() if value is not None}


@pytest.mark.parametrize(
    ("category", "raw"),
    [
        (Category.mouse, {}),
        (Category.mouse, {"connection": []}),
        (Category.keyboard, {"connection": []}),
        (Category.laptop, {}),
    ],
)
def test_an_incomplete_spec_with_no_value_at_all_is_still_rejected_as_empty(
    category: Category, raw: dict[str, Any]
) -> None:
    with pytest.raises(SeedDataError, match="rỗng"):
        normalize_specs(category, raw, allow_incomplete=True)


def test_without_the_flag_a_spec_with_only_optional_values_is_still_rejected() -> None:
    with pytest.raises(SeedDataError, match="thiếu trường bắt buộc"):
        normalize_specs(Category.keyboard, {"hot_swap": True})


@pytest.mark.parametrize(
    ("category", "raw"),
    [
        (Category.mouse, {"connection": ["wired"]}),
        (Category.keyboard, {"connection": ["wired"], "switch_type": "mechanical"}),
        (Category.headset, {"form": "over_ear", "connection": ["bluetooth"]}),
    ],
)
def test_the_incomplete_flag_rejects_complete_specs_in_every_category(
    category: Category, raw: dict[str, Any]
) -> None:
    with pytest.raises(SeedDataError, match="đã đủ trường bắt buộc"):
        normalize_specs(category, raw, allow_incomplete=True)
