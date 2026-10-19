"""Ranh giới module: `app/scrapers` không import `app.db` hay `app.services` (trừ pipeline.py).

Quy tắc ở docs/03 §4 và .claude/rules/backend.md; ngoại lệ duy nhất là `pipeline.py`, chỗ nối
scraper → normalize → repository.
"""

import ast
from pathlib import Path

import pytest

SCRAPERS_DIR = Path(__file__).resolve().parents[2] / "app" / "scrapers"
FORBIDDEN = ("app.db", "app.services")
FILES = sorted(p for p in SCRAPERS_DIR.rglob("*.py") if p.name != "pipeline.py")


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            modules.update(
                f"{node.module}.{alias.name}" for alias in node.names
            )  # from app import db
    return modules


def test_scrapers_package_files_were_found() -> None:
    assert SCRAPERS_DIR / "base.py" in FILES


def test_import_scanner_sees_every_import_form(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import app.db\nfrom app import services\nfrom app.db.models import X\n")
    assert {"app.db", "app.services", "app.db.models"} <= _imported_modules(sample)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SCRAPERS_DIR)))
def test_scraper_modules_do_not_import_db_or_services(path: Path) -> None:
    offending = {
        m
        for m in _imported_modules(path)
        if any(m == f or m.startswith(f"{f}.") for f in FORBIDDEN)
    }
    assert offending == set()
