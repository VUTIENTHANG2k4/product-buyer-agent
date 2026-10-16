"""PreToolUse hook cho Bash: chặn lệnh nguy hiểm hoặc vi phạm quy tắc dự án.

Nhận JSON từ stdin (tool_input.command). Thoát mã 2 để chặn; stderr được gửi lại cho Claude.
Chỉ dùng thư viện chuẩn để chạy được trước khi có môi trường dự án.
"""

from __future__ import annotations

import json
import re
import sys

BLOCKED: list[tuple[str, str]] = [
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b|\brm\s+-[a-zA-Z]*f[a-zA-Z]*r\b", "Không dùng rm -rf. Xóa từng file cụ thể hoặc hỏi người dùng."),
    (r"\bgit\s+push\b.*(--force|-f\b)", "Không force push."),
    (r"\bgit\s+reset\s+--hard\b", "Không reset --hard; dùng git stash hoặc hỏi người dùng."),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "Không git clean -f."),
    (r"(cat|less|more|head|tail|type)\s+[^|;&]*\.env(\s|$)", "Không đọc file .env (chứa bí mật). Dùng .env.example."),
    (r"\b(pip|pip3)\s+install\b", "Dự án dùng uv: dùng `uv add <gói>` trong backend/."),
    (r"\bplaywright\s+install\b", "Không tải trình duyệt Playwright tự động; hỏi người dùng nếu thật sự cần."),
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = str(data.get("tool_input", {}).get("command", ""))
    for pattern, reason in BLOCKED:
        if re.search(pattern, command):
            print(f"[guard_bash] Bị chặn: {reason}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
