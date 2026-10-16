---
name: review
description: Gọi subagent code-reviewer soát diff của task hiện tại theo tài liệu thiết kế và quy tắc dự án, rồi sửa các vấn đề bắt buộc.
disable-model-invocation: true
argument-hint: "[task-id]"
---

# /review — soát code task $ARGUMENTS

1. Xác định phạm vi diff: `git diff main...HEAD` cộng thay đổi chưa commit (`git diff`, `git status`). Trước khi có git: danh sách file đã tạo/sửa trong task.
2. Giao cho subagent **code-reviewer** với thông tin: ID task, mục "Xong khi", các mục tài liệu liên quan, danh sách file thay đổi. Yêu cầu nó trả về theo 3 mức: **Phải sửa**, **Nên sửa**, **Gợi ý**.
3. Sửa toàn bộ mục **Phải sửa**. Với **Nên sửa**: sửa nếu nhỏ (< 15 phút), còn lại ghi thành task mới trong backlog. **Gợi ý**: bỏ qua hoặc ghi chú.
4. Chạy lại `/check` sau khi sửa.
5. Báo cáo ngắn: số mục mỗi mức, đã sửa gì, việc ghi thành task mới (ID).
