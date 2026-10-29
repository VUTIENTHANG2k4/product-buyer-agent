"""Ranh giới lớp của `app/` (docs/03 §4, .claude/rules/backend.md), kiểm bằng cách quét import.

Mỗi file thuộc một lớp; lớp chỉ được import chính nó, `domain`, `config`, gốc `app` (`__version__`)
và các lớp liệt kê trong `ALLOWED`. Thêm thư mục mới dưới `app/` mà chưa khai báo lớp thì test đỏ.
Import nằm trong hàm hay trong `if TYPE_CHECKING:` cũng tính.
"""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"
ALWAYS = frozenset({"app", "domain", "config"})

# lớp → các lớp khác được import (ngoài ALWAYS và chính nó)
ALLOWED: dict[str, frozenset[str]] = {
    "app": frozenset(),
    "config": frozenset(),
    "domain": frozenset(),
    "db": frozenset(),
    "normalize": frozenset(),
    "mock_shop": frozenset(),
    "scrapers": frozenset({"normalize"}),
    # nơi duy nhất trong scrapers nối scraper → normalize → repository
    "scrapers.pipeline": frozenset({"scrapers", "normalize", "db"}),
    "services": frozenset({"db", "normalize", "scrapers"}),
    # agent dùng hàm thuần của normalize (fold, hạng GPU) và services cho bộ nhớ hội thoại
    "agent": frozenset({"agent.tools", "services", "normalize"}),
    "agent.tools": frozenset({"services"}),
    "api": frozenset({"agent", "services"}),
    "main": frozenset({"api"}),
    # nơi dựng lịch chạy: bộ điền thông số (agent), registry trang (scrapers), scrape_service
    "worker": frozenset({"agent", "services", "scrapers"}),
}
FILES = sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def layer_of_file(path: Path) -> str:
    parts = path.relative_to(APP_DIR).with_suffix("").parts
    if parts == ("__init__",):
        return "app"
    if parts[:2] == ("agent", "tools"):
        return "agent.tools"
    if parts[:2] == ("scrapers", "pipeline"):
        return "scrapers.pipeline"
    return parts[0]


def layer_of_module(module: str) -> str | None:
    """Lớp của module `app.*` được import; None nếu không thuộc `app`."""
    parts = module.split(".")
    if parts[0] != "app":
        return None
    if len(parts) == 1 or parts[1] == "__version__":
        return "app"
    if parts[1:3] == ["agent", "tools"]:
        return "agent.tools"
    return parts[1]


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path}: import tương đối chưa được bộ quét hỗ trợ"
            if node.module is not None:
                modules.add(node.module)
                modules.update(
                    f"{node.module}.{alias.name}" for alias in node.names
                )  # from app import db
    return modules


def violations(path: Path) -> set[str]:
    layer = layer_of_file(path)
    own = {layer, layer.split(".")[0]}
    allowed = ALWAYS | own | ALLOWED[layer]
    return {
        f"{module} (lớp {target})"
        for module in imported_modules(path)
        if (target := layer_of_module(module)) is not None and target not in allowed
    }


def test_app_files_were_found() -> None:
    assert APP_DIR / "scrapers" / "base.py" in FILES
    assert APP_DIR / "agent" / "tools" / "base.py" in FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(APP_DIR).as_posix())
def test_every_app_file_belongs_to_a_declared_layer(path: Path) -> None:
    assert layer_of_file(path) in ALLOWED


def test_import_scanner_sees_every_import_form(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import app.db\nfrom app import services\nfrom app.db.models import X\n"
        "def f():\n    from app.agent import runner\n"
    )
    assert {"app.db", "app.services", "app.db.models", "app.agent"} <= imported_modules(sample)


@pytest.mark.parametrize(
    ("module", "layer"),
    [
        ("app", "app"),
        ("app.__version__", "app"),
        ("app.db.models", "db"),
        ("app.agent.tools.base", "agent.tools"),
        ("app.agent.runner", "agent"),
        ("app.scrapers.pipeline", "scrapers"),
        ("sqlmodel", None),
    ],
)
def test_layer_of_module_maps_imports_to_layers(module: str, layer: str | None) -> None:
    assert layer_of_module(module) == layer


def test_a_tool_importing_db_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = tmp_path / "agent" / "tools"
    tools.mkdir(parents=True)
    bad = tools / "bad.py"
    bad.write_text("from app.db.models import Offer\nfrom app.services import catalog_service\n")
    monkeypatch.setattr(f"{__name__}.APP_DIR", tmp_path)

    assert violations(bad) == {"app.db.models (lớp db)", "app.db.models.Offer (lớp db)"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(APP_DIR).as_posix())
def test_module_imports_respect_layer_boundaries(path: Path) -> None:
    assert violations(path) == set()
