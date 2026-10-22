"""Xuất OpenAPI của API ra file JSON để sinh kiểu TypeScript (docs/07 §1, T7.5).

Chạy từ `backend/`: `uv run python -m scripts.dump_openapi [--out ../frontend/openapi.json]`
(`make gen-api` gọi lệnh này rồi `npm run gen:api`). Không cần CSDL, mạng hay `.env`: schema sinh
từ định nghĩa route, không từ dữ liệu.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.main import create_app

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    """OpenAPI hiện tại của app (cùng nội dung với `GET /api/openapi.json`)."""
    schema: dict[str, Any] = create_app().openapi()
    return schema


def render(schema: dict[str, Any]) -> str:
    """JSON ổn định (thụt 2, giữ tiếng Việt, kết thúc bằng xuống dòng) để diff gọn."""
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xuất OpenAPI ra file JSON.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="file đầu ra")
    args = parser.parse_args(argv)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(build_openapi()), encoding="utf-8", newline="\n")
    print(f"Wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
