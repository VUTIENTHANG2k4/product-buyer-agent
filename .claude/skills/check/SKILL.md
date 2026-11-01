---
name: check
description: Chạy cổng chất lượng (lint, type check, test backend và frontend) và sửa lỗi cho đến khi xanh. Dùng sau khi code xong một bước hoặc trước khi /review, /done.
disable-model-invocation: true
argument-hint: "[be|fe|all]"
allowed-tools: Bash(make *) Bash(uv run *) Bash(npm run *) Bash(npx tsc *) Bash(npx vitest *) Read Grep Glob
---

# /check — cổng chất lượng

Phạm vi: `$ARGUMENTS` (mặc định `all`).

1. Chạy lệnh:
   - `all`: `make check`
   - `be`: `make test-be` (gồm ruff, mypy, pytest)
   - `fe`: `make test-fe` (gồm eslint, tsc, vitest)
   - Trước khi có Makefile (trước T0.3): trong `backend/` chạy `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`; trong `frontend/` chạy `npm run lint && npx tsc --noEmit && npm run test -- --run`.
2. Nếu có lỗi:
   - Đọc thông báo lỗi đầy đủ, tìm nguyên nhân gốc. Sửa code, không sửa test để che lỗi.
   - Chỉ sửa test khi test sai so với tài liệu thiết kế; nói rõ lý do.
   - Không thêm `# type: ignore`, `noqa`, `@ts-ignore`, `skip` trừ khi có lý do kỹ thuật ghi ngay cạnh.
   - Chạy lại đến khi xanh. Sau 3 vòng vẫn đỏ ở cùng lỗi → dừng, tóm tắt lỗi và hỏi người dùng.
3. Báo cáo ngắn:
   ```
   /check: ✅ xanh | ❌ còn lỗi
   - Backend: ruff ✅, mypy ✅, pytest 142 passed, coverage 84%
   - Frontend: eslint ✅, tsc ✅, vitest 37 passed
   - Đã sửa: <danh sách ngắn>
   ```
