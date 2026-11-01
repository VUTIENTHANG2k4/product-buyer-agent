---
name: agent-tool
description: Thêm hoặc sửa một tool của agent LangChain theo hợp đồng trong docs/05-agent-design.md, kèm test với ScriptedChatModel và cập nhật prompt/eval. Dùng cho T6.4, T6.5, T10.3 và mọi thay đổi tool.
argument-hint: "<tool_name>"
---

# Thêm / sửa tool của agent

Tài liệu gốc: `docs/05-agent-design.md` §3–§6. Tra Context7 cho cú pháp định nghĩa tool của phiên bản LangChain đang khóa trong `pyproject.toml`.

## Hợp đồng bắt buộc
- File `backend/app/agent/tools/<tool_name>.py`.
- Tham số là một Pydantic model có `Field(description=...)` tiếng Anh ngắn, rõ đơn vị (VND) và giới hạn (`ge`, `le`, `max_length`). Mô tả tool 1–3 câu: làm gì, khi nào dùng, khi nào **không** dùng.
- Thân tool chỉ gọi `app/services/*`. Không truy cập DB, HTTP hay file trực tiếp.
- Trả về `dict` nhỏ gọn (≤ 4.000 ký tự JSON): id, tên, giá, nguồn, `scraped_at`; không HTML thô, không mô tả dài.
- Văn bản từ web trong kết quả được cắt ngắn và không bao giờ được nối vào prompt hệ thống.
- Lỗi nghiệp vụ → trả `{"ok": false, "error": "<mã>", "message": "<ngắn>"}` để LLM xử lý; lỗi hệ thống → raise để executor ghi `error`.
- Tool **ghi** (thêm danh sách, tạo cảnh báo): mô tả nói rõ "chỉ dùng khi người dùng yêu cầu rõ ràng"; executor kiểm tra lại (guardrail).
- Đăng ký trong `app/agent/tools/__init__.py` (`ALL_TOOLS`).

## Test (`backend/tests/agent/`)
1. Unit tool: gọi trực tiếp với seed DB, khẳng định cấu trúc và giới hạn kích thước kết quả.
2. Kịch bản agent với `ScriptedChatModel`: LLM giả phát tool call → khẳng định sự kiện `tool_start`/`tool_end`, kết quả cuối, guardrail.
3. Ca biên: tham số không hợp lệ, không có kết quả, id không tồn tại.

## Sau khi thêm/sửa
- Cập nhật bảng tool ở `docs/05-agent-design.md` §3 nếu hợp đồng đổi.
- Cập nhật `prompts/executor.md` (khi nào dùng tool).
- Thêm câu vào `docs/eval/queries.yaml` với `tools_required`/`tools_forbidden`.
- Gợi ý người dùng chạy `/eval` cho các ca liên quan.
