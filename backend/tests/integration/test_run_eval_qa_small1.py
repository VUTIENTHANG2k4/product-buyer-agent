"""QA small-1: mã thoát và báo cáo của `scripts.run_eval.main` khi một phần ca lỗi ngoài dự kiến."""

import os
from pathlib import Path

import pytest

from scripts import run_eval
from scripts.eval_core import CaseRun
from tests.service_support import make_settings


def configure(monkeypatch: pytest.MonkeyPatch, runs: list[CaseRun]) -> None:
    settings = make_settings(
        llm_provider="gemini",
        google_api_key="khoa-gia",
        test_database_url=os.environ["TEST_DATABASE_URL"],
    )

    async def fake_run_all(cases: list[object], *args: object, **kwargs: object) -> list[CaseRun]:
        assert len(cases) == len(runs)
        return runs

    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(run_eval, "run_all", fake_run_all)


def test_one_crashed_case_among_several_exits_below_threshold_and_names_it_in_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_engine: object
) -> None:
    configure(monkeypatch, [CaseRun(final_text="ok", latency_s=1.0), CaseRun(crashed="Boom: x")])

    code = run_eval.main(["--cases", "L01,L02", "--output-dir", str(tmp_path)])

    reports = list(tmp_path.iterdir())
    assert code == run_eval.EXIT_BELOW_THRESHOLD
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "Ca lỗi ngoài dự kiến" in text and "L02" in text and "Boom: x" in text


def test_a_single_requested_case_that_crashes_is_a_setup_failure_not_a_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_engine: object
) -> None:
    configure(monkeypatch, [CaseRun(crashed="OperationalError: DB tắt")])

    code = run_eval.main(["--cases", "L01", "--output-dir", str(tmp_path)])

    assert code == run_eval.EXIT_SETUP and list(tmp_path.iterdir()) == []


def test_cases_with_an_error_event_but_no_crash_still_write_a_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_engine: object
) -> None:
    configure(
        monkeypatch,
        [CaseRun(error_code="LLM_UNAVAILABLE"), CaseRun(error_code="LLM_UNAVAILABLE")],
    )

    code = run_eval.main(["--cases", "L01,L02", "--output-dir", str(tmp_path)])

    assert code in {run_eval.EXIT_OK, run_eval.EXIT_BELOW_THRESHOLD}
    assert len(list(tmp_path.iterdir())) == 1
