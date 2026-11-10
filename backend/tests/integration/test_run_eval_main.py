"""T6.13: mã thoát của `scripts.run_eval.main` khi mọi ca eval đều lỗi ngoài dự kiến."""

import os
from datetime import date
from pathlib import Path

import pytest

from scripts import run_eval
from scripts.eval_core import CaseRun
from tests.service_support import make_settings


async def _all_crash(cases: list[object], *args: object, **kwargs: object) -> list[CaseRun]:
    return [CaseRun(crashed="OperationalError: DB tắt") for _ in cases]


def _fine_runs(repeat_seen: list[int]) -> object:
    async def run_all(cases: list[object], *args: object, **kwargs: object) -> list[CaseRun]:
        repeat_seen.append(len(cases))
        return [CaseRun() for _ in cases]

    return run_all


@pytest.mark.parametrize(
    ("argv", "expected_name"),
    [
        ([], "eval-{today}.md"),
        (["--repeat", "2"], "eval-{today}-partial.md"),  # lặp câu: không ghi đè báo cáo đủ
        (["--cases", "L01"], "eval-{today}-partial.md"),
    ],
)
def test_report_is_partial_when_cases_are_selected_or_repeated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_engine: object,
    argv: list[str],
    expected_name: str,
) -> None:
    settings = make_settings(
        llm_provider="gemini",
        google_api_key="khoa-gia",
        test_database_url=os.environ["TEST_DATABASE_URL"],
    )
    seen: list[int] = []
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(run_eval, "run_all", _fine_runs(seen))

    run_eval.main([*argv, "--output-dir", str(tmp_path)])

    assert [p.name for p in tmp_path.iterdir()] == [expected_name.format(today=date.today())]
    expected_cases = 1 if "--cases" in argv else None
    if expected_cases is not None:
        assert seen == [expected_cases]
    elif "--repeat" in argv:
        assert seen[0] % 2 == 0 and seen[0] >= 2


def test_every_case_crashing_exits_with_the_setup_code_and_writes_no_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_engine: object
) -> None:
    settings = make_settings(
        llm_provider="gemini",
        google_api_key="khoa-gia",
        test_database_url=os.environ["TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(run_eval, "run_all", _all_crash)

    code = run_eval.main(["--cases", "L01", "--output-dir", str(tmp_path)])

    assert code == run_eval.EXIT_SETUP
    assert list(tmp_path.iterdir()) == []
