# Tiến độ dự án

> Claude Code cập nhật file này ở bước `/done` của mỗi task. Giữ **dưới 60 dòng**: chỉ trạng thái hiện tại, không ghi nhật ký dài (lịch sử đã có trong git log).
> Backlog đầy đủ: [11-roadmap-backlog.md](11-roadmap-backlog.md)

## Trạng thái
- Sprint hiện tại: 1 (M0 Nền tảng · M1 Dữ liệu)
- Task đang làm: –
- Task kế tiếp đề xuất: T0.3 Makefile, git, CI (đủ phụ thuộc: T0.1 + T0.2). T0.4 cần người dùng đọc/duyệt điều khoản; T0.5 làm khi tiện, trước T8.1
- Cập nhật lần cuối: 2026-10-16 — xong T0.2 Scaffold frontend

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
| Coverage backend | 98% (14 test) | 2026-10-16 |
| Test frontend (Vitest) | 23 pass (chưa đo coverage) | 2026-10-16 |
| Eval intent accuracy | – | |
| Eval constraint satisfaction | – | |
| Eval hallucination | – | |

## Ghi chú kỹ thuật cần nhớ (ngắn)
- (Thêm khi phát hiện điều mà phiên sau cần biết, ví dụ "GearVN cần Playwright cho trang danh sách".)
- 2026-10-16: đổi CSDL sang PostgreSQL 17 qua Docker Compose, test trên Postgres thật ([ADR-0007](adr/0007-postgresql.md) thay ADR-0002). Cần `make db-up` (trước T0.3: `docker compose up -d db`).
- 2026-10-16 (T0.1): `GET /api/health` trả HTTP 200 + `status: "degraded"`, `db: "error"` khi DB lỗi. Kiểm tra DB nằm ở `services/health_service.py` (api không được import db). `DATABASE_URL`/`TEST_DATABASE_URL` là `SecretStr`.
- Test chặn socket nhưng libpq (psycopg) không đi qua Python socket nên không bị chặn; test đụng DB lỗi phải dùng engine giả (dùng URL thật sẽ treo ~2 phút trên Windows).
- Việc nhỏ chưa có task (làm khi tiện): `app/logging.py`, `app/worker.py`, CORS origin vào `config.py`, engine theo lifespan + session theo request (T1.x), coverage trong `make check` (T0.3), chặn DNS trong fixture mạng.
- 2026-10-16 (T0.2): frontend dùng npm, Vite 8, React Router 8 (`RouterProvider` từ `react-router/dom`), Tailwind v4 (token trong `src/styles/globals.css`, không có `tailwind.config.ts`), TS 6 (không đặt `baseUrl`, chỉ `paths`), shadcn preset `vega`. Lệnh trong `frontend/`: `npm run lint|typecheck|test|format:check|build` (T0.3 gom vào `make check`; `npx tsc --noEmit` cũng phải xanh). Test dùng MSW và đỏ nếu request chưa có handler. Chế độ tối theo hệ điều hành, chưa có nút đổi (T8.1). Hook dự án chặn `rm -rf` và chuỗi đọc file `.env` trong lệnh Bash.
- Máy dev đang có PostgreSQL khác ở cổng 5432 từ chối mật khẩu `buyer`: kiểm tra trước `make db-up` ở T0.3.
