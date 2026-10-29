"""Ranh giới lớp của `app/` (docs/03 §4, .claude/rules/backend.md), kiểm bằng cách quét import.

Mỗi file thuộc một lớp; lớp chỉ được import chính nó, `domain`, `config`, gốc `app` (`__version__`)
và các lớp liệt kê trong `ALLOWED`; ngoại lệ có thật ghi theo tên file trong `FILE_EXCEPTIONS`
(kèm lý do, khớp docs/03 §4). Thêm thư mục mới dưới `app/` mà chưa khai báo lớp thì test đỏ.
Import nằm trong hàm hay trong `if TYPE_CHECKING:` cũng tính; `importlib.import_module` thì không
(`app/` không dùng).
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
    # nơi duy nhất trong scrapers nối scraper → normalize → repository (gói `scrapers/pipeline/`)
    "scrapers.pipeline": frozenset({"scrapers", "normalize", "db"}),
    "services": frozenset({"db", "normalize", "scrapers", "scrapers.pipeline"}),
    # agent chỉ gọi tool; truy cập khác là ngoại lệ theo file (FILE_EXCEPTIONS)
    "agent": frozenset({"agent.tools"}),
    "agent.tools": frozenset({"services"}),
    "api": frozenset({"agent", "services"}),
    "main": frozenset({"api"}),
    # nơi dựng lịch chạy: bộ điền thông số (agent), registry trang (scrapers), scrape_service
    "worker": frozenset({"agent", "services", "scrapers", "scrapers.pipeline"}),
}

# file → lớp được import thêm ngoài quy tắc của lớp nó (docs/03 §4, "Ngoại lệ theo file")
FILE_EXCEPTIONS: dict[str, frozenset[str]] = {
    # bảng kết quả dựng từ DB (`CatalogService.rows`, guardrail), lưu hội thoại/lượt
    # (`ConversationService`), kiểu `LiveSearchService` tiêm cho tool tầng 2
    "agent/runner.py": frozenset({"services"}),
    # đổi `ConversationSnapshot` (đọc qua service) thành ngữ cảnh cho LLM
    "agent/memory.py": frozenset({"services"}),
    # hàm thuần của normalize: bỏ dấu (`text.fold`), bảng hạng GPU, giao diện `LlmSpecsFiller`
    "agent/fake_llm.py": frozenset({"normalize"}),
    "agent/guardrail.py": frozenset({"normalize"}),
    "agent/intent.py": frozenset({"normalize"}),
    "agent/planner.py": frozenset({"normalize"}),
    "agent/spec_filler.py": frozenset({"normalize"}),
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
    if parts[1:3] == ["scrapers", "pipeline"]:
        return "scrapers.pipeline"
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
    extra = FILE_EXCEPTIONS.get(path.relative_to(APP_DIR).as_posix(), frozenset())
    allowed = ALWAYS | own | ALLOWED[layer] | extra
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
        "import app.api as api\n"
        "if TYPE_CHECKING:\n    from app.worker import main\n"
        "def f():\n    from app.agent import runner\n"
    )
    assert {
        "app.db",
        "app.services",
        "app.db.models",
        "app.api",
        "app.worker",
        "app.agent",
    } <= imported_modules(sample)


def test_relative_imports_are_rejected_by_the_scanner(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from . import models\n")
    with pytest.raises(AssertionError, match="tương đối"):
        imported_modules(sample)


@pytest.mark.parametrize(
    ("module", "layer"),
    [
        ("app", "app"),
        ("app.__version__", "app"),
        ("app.db.models", "db"),
        ("app.agent.tools.base", "agent.tools"),
        ("app.agent.runner", "agent"),
        ("app.scrapers.pipeline", "scrapers.pipeline"),
        ("app.scrapers.pipeline.state", "scrapers.pipeline"),
        ("app.scrapers.registry", "scrapers"),
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


def test_a_scraper_reaching_db_through_the_pipeline_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sites = tmp_path / "scrapers" / "sites"
    sites.mkdir(parents=True)
    bad = sites / "bad.py"
    bad.write_text("from app.scrapers.pipeline import ScrapePipeline\n")
    monkeypatch.setattr(f"{__name__}.APP_DIR", tmp_path)

    assert violations(bad) == {
        "app.scrapers.pipeline (lớp scrapers.pipeline)",
        "app.scrapers.pipeline.ScrapePipeline (lớp scrapers.pipeline)",
    }


def test_an_agent_module_without_an_exception_may_not_call_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    bad = agent / "planner.py"  # chỉ có ngoại lệ normalize
    bad.write_text("from app.services.scrape_service import ScrapeService\n")
    monkeypatch.setattr(f"{__name__}.APP_DIR", tmp_path)

    assert violations(bad) == {
        "app.services.scrape_service (lớp services)",
        "app.services.scrape_service.ScrapeService (lớp services)",
    }


@pytest.mark.parametrize("name", sorted(FILE_EXCEPTIONS))
def test_every_file_exception_is_still_needed(name: str) -> None:
    path = APP_DIR / name
    assert path in FILES
    layer = layer_of_file(path)
    used = {layer_of_module(m) for m in imported_modules(path)}
    for extra in FILE_EXCEPTIONS[name]:
        assert extra not in ALLOWED[layer], f"{name}: {extra} đã được phép ở mức lớp"
        assert extra in used, f"{name}: ngoại lệ {extra} không còn dùng, xóa khỏi danh sách"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(APP_DIR).as_posix())
def test_module_imports_respect_layer_boundaries(path: Path) -> None:
    assert violations(path) == set()
