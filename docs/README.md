# Tài liệu dự án — Product Scraper & Buyer Agent

## Thứ tự đọc

| # | Tài liệu | Trả lời câu hỏi | Ai đọc khi nào |
| --- | --- | --- | --- |
| 01 | [Phân tích yêu cầu](01-requirements.md) | Làm gì, cho ai, thế nào là đạt | Đầu dự án; khi viết tiêu chí task |
| 02 | [Phạm vi & nguồn dữ liệu](02-scope-and-sources.md) | Trang nào, nhóm nào, quy tắc tuân thủ | Trước mọi việc liên quan scraping |
| 03 | [Kiến trúc](03-architecture.md) | Các thành phần và cách chúng nói chuyện | Trước khi tạo module mới |
| 04 | [Dữ liệu](04-data-model.md) | Bảng, enum, khung thông số, chuẩn hóa | M1, M5, khi đổi schema |
| 05 | [Agent](05-agent-design.md) | Planner, tool, prompt, guardrail, eval | M6, M10 |
| 06 | [Thu thập](06-scraping-design.md) | BaseScraper, fetcher, mock-shop, fixture | M2–M4, M10 |
| 07 | [API](07-api-spec.md) | Endpoint, schema, lỗi, SSE | M7, M8 |
| 08 | [UI/UX](08-ui-ux.md) | Màn hình, trạng thái, token | M8 |
| 09 | [Kiểm thử](09-testing-strategy.md) | Test gì, bằng gì, ngưỡng nào | Mọi task |
| 10 | [Triển khai](10-deployment.md) | Chạy, CI, Docker, demo | M0, M9, M11 |
| 11 | [Lộ trình & backlog](11-roadmap-backlog.md) | Việc cần làm, thứ tự, Definition of Done | Mỗi lần chọn task |
| – | [PROGRESS](PROGRESS.md) | Đang ở đâu | Đầu mỗi phiên |
| – | [ADR](adr/README.md) | Vì sao chọn như vậy | Khi muốn đổi quyết định |
| – | [Eval](eval/queries.yaml) | Bộ câu hỏi đánh giá agent | M6, M11 |
| – | [Nguồn](sources/_template.md) · [gearvn](sources/gearvn.md) · [fptshop](sources/fptshop.md) · [anphat](sources/anphat.md) · [hoangha](sources/hoangha.md) và [laptop88](sources/laptop88.md) (không dùng, ADR-0008) · [viettelstore](sources/viettelstore.md) · [nguyenkim](sources/nguyenkim.md) | Kết quả khảo sát từng trang (mục 1–2 do T0.4) | M3, M4, M10 |
| – | [Ảnh UI](ui/README.md) | Phác thảo / ảnh tham khảo | M8 |

## Truy vết yêu cầu → thiết kế → task

| Yêu cầu | Thiết kế | Task |
| --- | --- | --- |
| US-01/02/03 Hỏi, xem kế hoạch, bảng so sánh | 05 §1–6, 07 §3.2, 08 §3.2 | T6.3–T6.5, T7.2, T8.2–T8.3 |
| US-04 So sánh chi tiết | 05 §3 (`compare_products`), 08 §3.3 | T6.4, T7.1, T8.3 |
| US-05 Lịch sử giá | 04 `price_history`, 08 §3.4 | T1.4, T7.1, T8.4 |
| US-06 Danh sách mua | 04, 07 §3.4, 08 §3.5 | T6.2, T7.3, T8.5 |
| US-07 Cảnh báo giá | 04, 07 §3.5, 08 §3.6 | T6.2, T9.1–T9.3, T8.6 |
| US-08 Tầng 2 | ADR-0005, 05 §3, 03 §5.3 | T10.1–T10.3 |
| US-09/10 Quản trị, HITL | 06 §4–5, 07 §3.6, 08 §3.7, ADR-0006 | T2.3, T2.6, T7.4, T8.7 |
| US-11 Hỏi lại | 05 §4 | T6.3, T6.5 |
| US-12 Dùng tốt trên điện thoại | 08 §6 | T8.1–T8.7 (ảnh chụp 375 px) |
| G5 Lịch sự với nguồn | 02 §3, 06 §3 | T0.4, T2.1 |
