"""PostToolUse hook cho Edit/Write: tự format file vừa sửa.

- backend/**/*.py  -> ruff format + ruff check --fix (nếu backend/pyproject.toml đã có)
- frontend/**/*.{ts,tsx,js,jsx,css,json} -> prettier (nếu frontend/node_modules đã có)
Bỏ qua lặng lẽ khi công cụ chưa được cài (trước milestone M0). Luôn thoát 0 để không chặn.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FE_EXT = {".ts", ".tsx", ".js", ".jsx", ".css", ".json"}


def run(cmd: list[str], cwd: Path) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    raw = data.get("tool_input", {}).get("file_path")
    if not raw:
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
    file = Path(raw).resolve()
    try:
        rel = file.relative_to(root)
    except ValueError:
        return 0
    if not rel.parts:
        return 0

    backend = root / "backend"
    frontend = root / "frontend"
    uv = shutil.which("uv")
    npx = shutil.which("npx")

    if rel.parts[0] == "backend" and file.suffix == ".py" and (backend / "pyproject.toml").exists() and uv:
        run([uv, "run", "ruff", "check", "--fix", "--quiet", str(file)], backend)
        run([uv, "run", "ruff", "format", str(file)], backend)
    elif rel.parts[0] == "frontend" and file.suffix in FE_EXT and (frontend / "node_modules").exists() and npx:
        run([npx, "--no-install", "prettier", "--write", "--log-level", "silent", str(file)], frontend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
