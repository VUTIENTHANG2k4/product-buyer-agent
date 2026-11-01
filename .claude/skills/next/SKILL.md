---
name: next
description: Chọn milestone kế tiếp (hoặc milestone chỉ định), liệt kê các task làm được theo thứ tự phụ thuộc và tạo nhánh git cho cả milestone. Dùng khi bắt đầu một milestone mới.
disable-model-invocation: true
argument-hint: "[milestone-id tùy chọn, ví dụ M2]"
allowed-tools: Read Edit Grep Glob Bash(git status *) Bash(git status) Bash(git switch *) Bash(git checkout -b *) Bash(git branch *)
---

# /next — chọn milestone kế tiếp

Đối số (tùy chọn): $ARGUMENTS

1. Đọc `docs/PROGRESS.md` và `docs/11-roadmap-backlog.md`.
2. Nếu có đối số (ví dụ `M2`), chọn milestone đó. Nếu không, chọn milestone ⬜ đầu tiên mà mọi milestone phụ thuộc (sơ đồ mục 3 của backlog) đã ✅. Có milestone 🔄 đang dở thì ưu tiên tiếp tục.
3. Lập danh sách task của milestone:
   - Các task ⬜/🔄 của milestone, sắp theo thứ tự phụ thuộc (task nào cần task khác trong cùng milestone thì xếp sau).
   - Task có phụ thuộc ngoài milestone chưa xong → đánh dấu "bị chặn", không đưa vào lượt này.
   - Task phát sinh còn ⬜ ở milestone trước (ví dụ T1.6–T1.8) mà task trong lượt này cần → đưa vào đầu danh sách; task phát sinh không chặn → hỏi người dùng có gộp vào không.
   - Task cần người dùng quyết định (T0.4, T3.3, T4.5, duyệt giao diện) → nói rõ người dùng cần làm gì và ở bước nào.
4. `git status` có thay đổi chưa commit → báo và hỏi trước khi chuyển nhánh.
5. Tạo nhánh `milestone/<ID>-<slug-ngắn>` từ `main` (ví dụ `milestone/M2-scrape-infra`).
6. Đánh dấu milestone 🔄 trong PROGRESS.md, ghi danh sách task của lượt vào "Đang làm".
7. Trả lời ngắn gọn bằng tiếng Việt:
   - ID + tên milestone, tổng ước lượng
   - Bảng task theo thứ tự sẽ làm (ID, tên, ước lượng, ghi chú chặn/cần quyết định)
   - Mục tài liệu cần đọc (gộp, không trùng)
   - Gợi ý: "Vào Plan mode rồi chạy `/plan-task <ID milestone>`".

Không bắt đầu viết code trong skill này.
