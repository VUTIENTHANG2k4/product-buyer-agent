"""PreToolUse hook cho Edit/Write: bảo vệ file không được sửa tự động.

- .env* (trừ .env.example): chứa bí mật.
- docs/adr/*: ADR đã chấp nhận là bất biến; muốn đổi quyết định thì tạo ADR mới thay thế.
Thoát mã 2 để chặn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePath


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    raw = str(data.get("tool_input", {}).get("file_path", ""))
    if not raw:
        return 0
    path = PurePath(raw.replace("\\", "/"))
    name = path.name
    parts = path.parts

    if name.startswith(".env") and name != ".env.example":
        print("[protect_files] Không sửa file .env. Cập nhật .env.example và báo người dùng tự điền.", file=sys.stderr)
        return 2

    tool = data.get("tool_name", "")
    is_adr = "adr" in parts and "docs" in parts and name[:4].isdigit()
    overwrites_existing = tool == "Write" and Path(raw).exists()
    if is_adr and (tool == "Edit" or overwrites_existing):
        print(
            "[protect_files] ADR đã chấp nhận không sửa trực tiếp. Tạo ADR mới (số tiếp theo) với trạng thái 'Thay thế ADR-XXXX'.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
