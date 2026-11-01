---
name: review
description: Gọi subagent code-reviewer soát toàn bộ diff của milestone hiện tại theo tài liệu thiết kế và quy tắc dự án, rồi sửa các vấn đề bắt buộc.
disable-model-invocation: true
argument-hint: "[milestone-id]"
---

# /review — soát code milestone $ARGUMENTS

1. Xác định phạm vi diff: `git diff main...HEAD` cộng thay đổi chưa commit (`git diff`, `git status`); `git log main..HEAD --oneline` để biết commit nào thuộc task nào.
2. Giao cho subagent **code-reviewer** với thông tin: ID milestone, danh sách task kèm mục "Xong khi" của từng task, các mục tài liệu liên quan, danh sách file thay đổi. Diff lớn (> ~3000 dòng) thì chia theo nhóm task, mỗi nhóm một lần gọi. Yêu cầu trả về theo 3 mức: **Phải sửa**, **Nên sửa**, **Gợi ý**, mỗi mục ghi task liên quan.
3. Sửa toàn bộ mục **Phải sửa**. Với **Nên sửa**: sửa nếu nhỏ (< 15 phút), còn lại ghi thành task mới trong backlog. **Gợi ý**: bỏ qua hoặc ghi chú.
4. Commit phần sửa: `fix(<ID milestone>): address review findings`.
5. Chạy lại `/check` sau khi sửa.
6. Báo cáo ngắn: số mục mỗi mức, đã sửa gì, việc ghi thành task mới (ID). Bước kế tiếp: subagent `qa-tester` rồi `/done <ID milestone>`.
