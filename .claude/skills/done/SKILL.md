---
name: done
description: Đóng một task trong lượt milestone (commit task) hoặc đóng cả milestone theo Definition of Done. Dùng "/done T2.1" sau khi xong một task, "/done M2" sau khi /check, /review và qa-tester đã xong.
disable-model-invocation: true
argument-hint: "<task-id | milestone-id>"
allowed-tools: Read Edit Grep Glob Bash(make check) Bash(make test-be) Bash(make test-fe) Bash(git status *) Bash(git status) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git log *)
---

# /done — đóng $ARGUMENTS

Đối số là ID task (`T2.1`) → làm phần A. Là ID milestone (`M2`) → làm phần B.

## A. Đóng một task trong lượt (nhẹ, không review)
1. **Tiêu chí:** liệt kê từng mục "Xong khi" của task kèm bằng chứng (tên test, lệnh, đường dẫn ảnh). Mục nào chưa có bằng chứng → dừng, báo thiếu gì.
2. **Test liên quan xanh:** chạy test của phần vừa sửa (`make test-be` hoặc `make test-fe`, hoặc pytest/vitest theo file). Chưa cần `make check` đầy đủ.
3. **Tài liệu:** hành vi khác thiết kế → đã cập nhật docs (và `.env.example`, OpenAPI) ngay trong task này.
4. **Backlog:** đổi trạng thái task thành ✅ trong `docs/11-roadmap-backlog.md`. Không sửa PROGRESS trừ dòng "Đang làm".
5. **Commit:** `git add` các file của task, message:
   ```
   <type>(<ID>): <tóm tắt tiếng Anh, ≤ 72 ký tự>

   - <thay đổi chính 1>
   - <thay đổi chính 2>
   Refs: docs/11-roadmap-backlog.md#<ID>
   ```
6. Báo 1–2 dòng rồi chuyển sang task kế tiếp trong kế hoạch.

## B. Đóng milestone (Definition of Done, mục 2 của backlog)
Làm đúng thứ tự, dừng nếu một bước không đạt:
1. **Task:** mọi task trong lượt đã ✅ (phần A). Task bị chặn/hoãn → ghi lý do trong PROGRESS.
2. **Cổng chất lượng:** chạy `make check`. Đỏ → dừng.
3. **Review:** `/review` đã chạy cho trạng thái code hiện tại, không còn mục "Phải sửa".
4. **QA:** subagent `qa-tester` đã chạy cho milestone; bug tìm thấy đã ghi thành task mới (giữ bằng `xfail(strict=True)`/`it.fails`) hoặc đã sửa kèm test.
5. **Tài liệu:** sơ đồ/kiến trúc trong docs khớp thực tế; đổi quyết định lớn → có ADR mới.
6. **PROGRESS.md:** đánh ✅ milestone, "Đang làm" (–), "Kế tiếp đề xuất", "Cập nhật lần cuối", kết quả đo mới (coverage, eval nếu có), ghi chú kỹ thuật **chỉ khi** phiên sau cần biết. Giữ file < 60 dòng.
7. **Commit:** `docs(<ID milestone>): close milestone` cho phần PROGRESS/backlog còn lại. Không push, không merge (chờ người dùng).
8. **Báo cáo** 3–6 dòng: đã xong task nào, bằng chứng chính, bug QA, milestone kế tiếp. Nhắc người dùng merge nhánh rồi `/clear`.
