# Tiến độ dự án

> Claude Code cập nhật file này ở bước `/done` của mỗi task. Giữ **dưới 60 dòng**: chỉ trạng thái hiện tại, không ghi nhật ký dài (lịch sử đã có trong git log).
> Backlog đầy đủ: [11-roadmap-backlog.md](11-roadmap-backlog.md)

## Trạng thái
- Sprint hiện tại: 1 (M0 Nền tảng · M1 Dữ liệu)
- Task đang làm: –
- Task kế tiếp đề xuất: T0.1 Scaffold backend (T0.2 và T0.4 làm song song được)
- Cập nhật lần cuối: 2026-10-16 — khởi tạo bộ tài liệu đặc tả

## Milestone
| Milestone | Trạng thái | Ghi chú |
| --- | --- | --- |
| M0 Nền tảng | ⬜ | |
| M1 Dữ liệu | ⬜ | |
| M2 Hạ tầng thu thập | ⬜ | |
| M3 GearVN | ⬜ | Cần T0.4 được người dùng duyệt |
| M4 Hoàng Hà + Laptop88 | ⬜ | |
| M5 Chuẩn hóa & ghép | ⬜ | |
| M6 Agent | ⬜ | |
| M7 API | ⬜ | |
| M8 Frontend | ⬜ | |
| M9 Theo dõi giá | ⬜ | |
| M10 Tầng 2 | ⬜ | |
| M11 Hoàn thiện | ⬜ | |

## Bị chặn / cần người dùng quyết định
- [ ] T0.4: người dùng đọc và duyệt kết luận điều khoản sử dụng của 5 nguồn trước khi chạy scraper thật.

## Kết quả đo mới nhất
| Chỉ số | Giá trị | Ngày |
| --- | --- | --- |
| Coverage backend | – | |
| Eval intent accuracy | – | |
| Eval constraint satisfaction | – | |
| Eval hallucination | – | |

## Ghi chú kỹ thuật cần nhớ (ngắn)
- (Thêm khi phát hiện điều mà phiên sau cần biết, ví dụ "GearVN cần Playwright cho trang danh sách".)
- 2026-10-16: đổi CSDL sang PostgreSQL 17 qua Docker Compose, test trên Postgres thật ([ADR-0007](adr/0007-postgresql.md) thay ADR-0002). Cần `make db-up` (trước T0.3: `docker compose up -d db`).
