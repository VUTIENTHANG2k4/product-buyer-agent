---
name: next
description: Chọn task kế tiếp trong backlog có đủ phụ thuộc, tóm tắt yêu cầu và tạo nhánh git. Dùng khi bắt đầu một task mới.
disable-model-invocation: true
argument-hint: "[task-id tùy chọn]"
allowed-tools: Read Edit Grep Glob Bash(git status *) Bash(git status) Bash(git switch *) Bash(git checkout -b *) Bash(git branch *)
---

# /next — chọn task kế tiếp

Đối số (tùy chọn): $ARGUMENTS

1. Đọc `docs/PROGRESS.md` và `docs/11-roadmap-backlog.md`.
2. Nếu có đối số là ID task (ví dụ `T2.6`), chọn task đó. Nếu không, chọn task ⬜ đầu tiên theo thứ tự milestone mà **mọi phụ thuộc đã ✅**. Có task 🔄 đang dở thì ưu tiên tiếp tục task đó.
3. Kiểm tra trước khi nhận:
   - Có phụ thuộc chưa xong → báo task nào chặn, đề xuất task khác làm được.
   - Task cần người dùng quyết định (T0.4, T3.3, T4.5, duyệt giao diện) → nói rõ người dùng cần làm gì.
   - `git status` có thay đổi chưa commit → báo và hỏi trước khi chuyển nhánh.
4. Tạo nhánh `task/<ID>-<slug-ngắn>` từ `main` (nếu repo git đã có; trước T0.3 bỏ qua bước này).
5. Đánh dấu task 🔄 trong bảng backlog và cập nhật "Task đang làm" trong PROGRESS.md.
6. Trả lời ngắn gọn bằng tiếng Việt:
   - ID + tên task, ước lượng
   - Mục tiêu một câu
   - Danh sách "Xong khi"
   - Mục tài liệu cần đọc (đường dẫn + mục)
   - Gợi ý: "Vào Plan mode rồi chạy `/plan-task <ID>`".

Không bắt đầu viết code trong skill này.
