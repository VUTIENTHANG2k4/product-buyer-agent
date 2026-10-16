---
name: done
description: Đóng một task theo Definition of Done - đối chiếu tiêu chí, cập nhật backlog và PROGRESS, commit. Dùng khi task đã code xong và /check, /review đã xanh.
disable-model-invocation: true
argument-hint: "<task-id>"
allowed-tools: Read Edit Grep Glob Bash(make check) Bash(git status *) Bash(git status) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git log *)
---

# /done — đóng task $ARGUMENTS

Đối chiếu [Definition of Done](../../../docs/11-roadmap-backlog.md) (mục 2). Làm đúng thứ tự, dừng nếu một bước không đạt:

1. **Tiêu chí:** liệt kê từng mục "Xong khi" của $ARGUMENTS kèm bằng chứng (tên test, lệnh, đường dẫn ảnh). Mục nào chưa có bằng chứng → dừng, báo thiếu gì.
2. **Cổng chất lượng:** chạy `make check` (hoặc lệnh tương đương trước T0.3). Đỏ → dừng.
3. **Review:** xác nhận `/review` đã chạy cho trạng thái code hiện tại và không còn mục "Phải sửa".
4. **Tài liệu:** nếu hành vi/thiết kế khác tài liệu, đã cập nhật docs tương ứng (và `.env.example`, OpenAPI). Nếu đổi quyết định lớn → đã có ADR mới.
5. **Backlog:** đổi trạng thái $ARGUMENTS thành ✅ trong `docs/11-roadmap-backlog.md`. Nếu cả milestone xong → đánh ✅ milestone trong PROGRESS.
6. **PROGRESS.md:** cập nhật "Task đang làm" (–), "Task kế tiếp đề xuất", "Cập nhật lần cuối", kết quả đo mới (coverage, eval nếu có), ghi chú kỹ thuật **chỉ khi** phiên sau cần biết. Giữ file < 60 dòng.
7. **Commit:** `git add` các file của task, commit message:
   ```
   <type>(<ID>): <tóm tắt tiếng Anh, ≤ 72 ký tự>

   - <thay đổi chính 1>
   - <thay đổi chính 2>
   Refs: docs/11-roadmap-backlog.md#<ID>
   ```
   Không push, không merge (chờ người dùng).
8. **Báo cáo** 3–5 dòng: đã xong gì, bằng chứng chính, task kế tiếp đề xuất. Nếu vừa hết milestone: nhắc chạy subagent `qa-tester` và `/clear`.
