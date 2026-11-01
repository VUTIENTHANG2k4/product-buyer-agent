---
name: plan-task
description: Lập một kế hoạch triển khai cho cả milestone (mọi task trong lượt) trước khi code. Dùng trong Plan mode sau /next.
disable-model-invocation: true
argument-hint: "<milestone-id>"
allowed-tools: Read Grep Glob
---

# /plan-task — kế hoạch cho milestone $ARGUMENTS

Mục tiêu: **một** kế hoạch cho cả milestone, để người dùng duyệt một lần trước khi code. Không viết code ở bước này.

## Các bước
1. Đọc mục milestone $ARGUMENTS trong `docs/11-roadmap-backlog.md`, mô tả từng task trong lượt (danh sách từ `/next`) và **mọi mục tài liệu các task tham chiếu**.
2. Đọc code hiện có liên quan (Glob/Grep) để tái sử dụng hàm, model, fixture sẵn có. Không đề xuất viết lại cái đã có.
3. Nếu task dùng thư viện bên ngoài mà chưa chắc API (LangChain, shadcn/ui, APScheduler, Alembic…), tra Context7 và ghi phiên bản.
4. Viết kế hoạch theo mẫu dưới: phần chung ngắn, mỗi task ~10–20 dòng. Tổng tối đa ~150 dòng; milestone lớn (M8) thì gom task giống nhau.
5. Liệt kê câu hỏi cho người dùng nếu yêu cầu chưa rõ hoặc mâu thuẫn với tài liệu. Không tự đoán ở điểm có ảnh hưởng lớn. Gom mọi câu hỏi lên đầu để người dùng trả lời một lần.

## Mẫu kế hoạch
```
## Kế hoạch $ARGUMENTS — <tên milestone>
Mục tiêu: <1–2 câu, kết quả trình diễn được>
Thứ tự: T2.1 → T2.3 → T2.4 → T2.5 → T2.6

### Câu hỏi cho người dùng
- ... (hoặc "không")

### Rủi ro & giả định chung
- ...

### T2.1 — <tên>
- File: tạo <đường dẫn> — <vai trò>; sửa <đường dẫn> — <thay đổi>
- Bước: 1. <bước> → test: <hành vi khẳng định> ...
- Test: unit / integration / fixture cần
- "Xong khi" → bằng chứng: <tiêu chí> → <test / lệnh / ảnh chụp>
- Docs cần cập nhật: ... (hoặc "không")

### T2.3 — ...
```

Kết thúc bằng việc trình kế hoạch để người dùng duyệt (ExitPlanMode). Duyệt xong thì làm lần lượt các task, không cần duyệt lại từng task, trừ khi phát hiện điều làm kế hoạch sai đáng kể.
