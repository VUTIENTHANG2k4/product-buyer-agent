---
paths:
  - "backend/tests/**"
  - "frontend/src/**/*.test.ts"
  - "frontend/src/**/*.test.tsx"
  - "frontend/e2e/**"
  - "docs/eval/**"
---

# Quy tắc viết test

- Tên test mô tả hành vi: `test_parse_listing_returns_none_price_when_masked`.
- Mỗi test khẳng định kết quả cụ thể (giá trị, số lượng, trạng thái), không chỉ "không lỗi".
- Dùng factory (`tests/factories.py`) và fixture dùng chung trong `conftest.py`; không lặp dữ liệu dài trong test.
- Không gọi mạng: `respx` cho HTTP, mock-shop qua ASGI transport, `ScriptedChatModel` cho LLM, `time-machine` cho thời gian. Test cần mạng thật phải có `@pytest.mark.live`.
- Không `sleep` thật trong test; độ trễ scraper đặt 0 qua cấu hình test và kiểm tra bằng đồng hồ giả.
- Tham số hóa (`pytest.mark.parametrize`) cho các ca chuẩn hóa/giá/thông số.
- Golden test (`tests/unit/golden/*.yaml`) chỉ thêm ca, không sửa kỳ vọng cũ trừ khi kỳ vọng sai; ghi lý do trong commit.
- Không sửa `docs/eval/queries.yaml` để làm eval đạt; chỉ thêm câu hoặc sửa câu có kỳ vọng sai rõ ràng (ghi lý do).
- Test frontend truy vấn theo vai trò/nhãn (`getByRole`, `getByLabelText`), không theo class CSS.
