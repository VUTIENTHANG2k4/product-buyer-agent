---
name: plan-task
description: Lập kế hoạch triển khai chi tiết cho một task trong backlog trước khi code. Dùng trong Plan mode sau /next.
disable-model-invocation: true
argument-hint: "<task-id>"
allowed-tools: Read Grep Glob
---

# /plan-task — kế hoạch cho task $ARGUMENTS

Mục tiêu: một kế hoạch ngắn, cụ thể, để người dùng duyệt trước khi code. Không viết code ở bước này.

## Các bước
1. Đọc mô tả task $ARGUMENTS trong `docs/11-roadmap-backlog.md` và **mọi mục tài liệu task tham chiếu**.
2. Đọc code hiện có liên quan (Glob/Grep) để tái sử dụng hàm, model, fixture sẵn có. Không đề xuất viết lại cái đã có.
3. Nếu task dùng thư viện bên ngoài mà chưa chắc API (LangChain, shadcn/ui, APScheduler, Alembic…), tra Context7 và ghi phiên bản.
4. Viết kế hoạch theo mẫu dưới, tối đa ~60 dòng.
5. Liệt kê câu hỏi cho người dùng nếu yêu cầu chưa rõ hoặc mâu thuẫn với tài liệu. Không tự đoán ở điểm có ảnh hưởng lớn.

## Mẫu kế hoạch
```
## Kế hoạch $ARGUMENTS — <tên task>
Mục tiêu: <1 câu>

### File
- Tạo: <đường dẫn> — <vai trò>
- Sửa: <đường dẫn> — <thay đổi>

### Các bước (mỗi bước kết thúc bằng test xanh)
1. <bước> → test: <tên test / hành vi khẳng định>
2. ...

### Test
- Unit: ...
- Integration: ...
- Dữ liệu/fixture cần: ...

### Ánh xạ "Xong khi" → bằng chứng
- <tiêu chí> → <test / lệnh / ảnh chụp>

### Rủi ro & giả định
- ...

### Tài liệu cần cập nhật
- ... (hoặc "không")

### Câu hỏi cho người dùng
- ... (hoặc "không")
```

Kết thúc bằng việc trình kế hoạch để người dùng duyệt (ExitPlanMode).
