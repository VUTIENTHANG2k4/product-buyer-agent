# ADR-0006: Mock-shop cho phân trang/captcha giả lập và xử lý human-in-the-loop

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Đề bài yêu cầu xử lý phân trang và captcha (giả lập). Vượt captcha của trang thật là vi phạm cơ chế kiểm soát truy cập của họ và không ổn định. Cần cách trình diễn và test lặp lại được.

## Quyết định
- Xây mock-shop nội bộ (FastAPI, cổng 8100) với dữ liệu hư cấu, phân trang, robots.txt, captcha giả bật sau N request và các chế độ lỗi.
- Gặp challenge ở mock-shop: lượt chạy chuyển `NEEDS_HUMAN`; người dùng nhập đáp án trên giao diện quản trị; hệ thống tiếp tục.
- Gặp challenge ở trang thật: dừng, `BLOCKED`, tạm nghỉ 24 giờ. Không bao giờ tự giải.

## Hệ quả
- Test integration cho phân trang, captcha, retry, soft block chạy offline, tái lập được.
- Demo bảo vệ không phụ thuộc mạng hay việc trang thật đổi giao diện.
- Thêm một ứng dụng nhỏ cần bảo trì.

## Phương án đã cân nhắc
- Dùng dịch vụ giải captcha: vi phạm điều khoản, trái nguyên tắc dự án.
- Chỉ dùng fixture tĩnh: không minh họa được luồng tương tác captcha.
