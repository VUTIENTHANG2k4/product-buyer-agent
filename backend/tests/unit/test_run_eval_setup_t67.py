"""T6.7: `scripts.run_eval.main` trả mã thoát 2 khi thiết lập hỏng, không in traceback.

Không cần DB: engine chỉ được tạo (lazy), `upgrade_to_head` và `load_cases` được thay giả.
"""

from pathlib import Path

import pytest
from alembic.util.exc import CommandError
from sqlalchemy import Engine
from sqlalchemy.exc import ProgrammingError

from app.db import migrations
from scripts import eval_core, run_eval
from tests.db_support import upgrade_to_head as support_upgrade_to_head
from tests.service_support import make_settings

TEST_URL = "postgresql+psycopg://user:pw@127.0.0.1:5999/eval_test"


@pytest.fixture
def gemini_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(
        llm_provider="gemini", google_api_key="khoa-gia", test_database_url=TEST_URL
    )
    monkeypatch.setattr(run_eval, "get_settings", lambda: settings)


def test_run_eval_uses_the_migration_helper_from_app_not_from_tests() -> None:
    assert vars(run_eval)["upgrade_to_head"] is migrations.upgrade_to_head
    assert support_upgrade_to_head is migrations.upgrade_to_head


@pytest.mark.parametrize(
    "error",
    [CommandError("revision lạ"), ProgrammingError("SELECT 1", {}, Exception("quyền"))],
    ids=["alembic", "sqlalchemy"],
)
def test_a_failing_migration_exits_with_the_setup_code(
    gemini_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    def broken(engine: Engine) -> None:
        raise error

    monkeypatch.setattr(run_eval, "upgrade_to_head", broken)

    code = run_eval.main(["--cases", "L01", "--output-dir", str(tmp_path)])

    assert code == run_eval.EXIT_SETUP
    assert "Không nâng được DB test" in caplog.text
    assert list(tmp_path.iterdir()) == []


def test_a_broken_queries_file_exits_with_the_setup_code(
    gemini_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = tmp_path / "queries.yaml"
    broken.write_text("cases: [\n  - id: L01\n    query: 'chưa đóng", encoding="utf-8")
    monkeypatch.setattr(
        run_eval, "load_cases", lambda only=(): eval_core.load_cases(path=broken, only=only)
    )

    code = run_eval.main(["--output-dir", str(tmp_path / "out")])

    assert code == run_eval.EXIT_SETUP
    assert "Không chạy được" in caplog.text


def test_a_missing_queries_file_exits_with_the_setup_code(
    gemini_settings: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "khong-co.yaml"
    monkeypatch.setattr(
        run_eval, "load_cases", lambda only=(): eval_core.load_cases(path=missing, only=only)
    )

    assert run_eval.main(["--output-dir", str(tmp_path / "out")]) == run_eval.EXIT_SETUP
