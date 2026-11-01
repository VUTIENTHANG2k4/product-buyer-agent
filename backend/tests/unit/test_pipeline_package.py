"""Gói `app.scrapers.pipeline` (T11.8): API công khai giữ nguyên, các module không phình lại."""

from pathlib import Path

import pytest

import app.scrapers.pipeline as pipeline

PACKAGE_DIR = Path(pipeline.__file__).parent
MAX_LINES = 500


def test_public_names_used_outside_the_package_are_exported() -> None:
    used_elsewhere = {
        "BLOCK_COOLDOWN",
        "CANCELLED_BY_USER",
        "NEEDS_HUMAN_STALE_AFTER",
        "RUNNING_STALE_AFTER",
        "PipelineResult",
        "Resolution",
        "ScrapePipeline",
        "SessionFactory",
        "StartedRun",
        "find_existing_offer",
        "make_resolver",
        "resolve_product",
    }
    assert used_elsewhere <= set(pipeline.__all__)
    assert all(hasattr(pipeline, name) for name in pipeline.__all__)


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_pipeline_modules_stay_below_the_line_limit(path: Path) -> None:
    assert len(path.read_text(encoding="utf-8").splitlines()) <= MAX_LINES
