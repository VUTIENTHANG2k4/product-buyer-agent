# ADR-0003: Thu thập trước theo lịch, agent trả lời từ cơ sở dữ liệu

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Các nguồn yêu cầu độ trễ 5–10 giây mỗi request. Một nhóm có thể vài trăm sản phẩm, cần nhiều trang danh sách và đôi khi trang chi tiết. Scrape trực tiếp khi người dùng hỏi sẽ mất hàng chục phút, dễ bị chặn và không lặp lại được khi test.

## Quyết định
- Tầng 1: worker thu thập theo lịch vào DB; agent chỉ truy vấn DB qua tool.
- Tầng 2: được phép tìm trực tiếp khi người dùng hỏi, giới hạn số kết quả, tuần tự, có cache 6 giờ.
- Mọi câu trả lời hiển thị thời điểm thu thập giá.

## Hệ quả
- Trả lời nhanh (giây), kết quả tái lập được trong test/eval.
- Giá có thể cũ đến vài giờ; giảm bằng lịch làm mới riêng cho sản phẩm đang theo dõi và nhãn "dữ liệu cũ".
- Cần thêm worker, scheduler, bảng ScrapeRun.

## Phương án đã cân nhắc
- Scrape theo yêu cầu cho mọi câu hỏi: đơn giản về kiến trúc nhưng chậm và vi phạm tinh thần lịch sự với nguồn.
