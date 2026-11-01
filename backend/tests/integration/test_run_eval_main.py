"""T6.13: mã thoát của `scripts.run_eval.main` khi mọi ca eval đều lỗi ngoài dự kiến."""

import os
from pathlib import Path

import pytest

from scripts import run_eval
from scripts.eval_core import CaseRun
from tests.service_support import make_settings


async def _all_crash(cases: list[object], *args: object, **kwargs: object) -> list[CaseRun]:
    return [CaseRun(crashed="OperationalError: DB tắt") for _ in cases]


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
