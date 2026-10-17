# Tiến độ dự án

> Claude Code cập nhật file này ở bước `/done` của mỗi task. Giữ **dưới 60 dòng**: chỉ trạng thái hiện tại, không ghi nhật ký dài (lịch sử đã có trong git log).
> Backlog đầy đủ: [11-roadmap-backlog.md](11-roadmap-backlog.md)

## Trạng thái
- Sprint hiện tại: 1 (M0 Nền tảng · M1 Dữ liệu)
- Task đang làm: –
- Task kế tiếp đề xuất: T0.6 (chặn mạng thật trên Windows + DNS; bắt buộc trước T2.1). Sau đó T0.7, T0.8 (bắt buộc trước M7) hoặc T1.1 Enum + DTO miền. T3.1 (GearVN) làm được sau M1–M2
- Cập nhật lần cuối: 2026-10-17 — xong T0.5 và `qa-tester` M0 (merge vào `main`; test QA ở nhánh `qa/M0`); QA tìm 6 lỗi → T0.6–T0.8, T8.9, T8.10

## Milestone
| Milestone | Trạng thái | Ghi chú |
| --- | --- | --- |
| M0 Nền tảng | 🔄 | T0.1–T0.5 ✅; còn T0.6–T0.8 (phát sinh từ QA M0) |
| M1 Dữ liệu | ⬜ | |
| M2 Hạ tầng thu thập | ⬜ | |
| M3 GearVN | ⬜ | T0.4 đã duyệt: GearVN được dùng |
| M4 Hoàng Hà + Laptop88 | ⬜ | |
| M5 Chuẩn hóa & ghép | ⬜ | |
| M6 Agent | ⬜ | |
| M7 API | ⬜ | |
| M8 Frontend | ⬜ | Có thêm T8.9, T8.10 (từ QA M0) |
| M9 Theo dõi giá | ⬜ | |
| M10 Tầng 2 | ⬜ | |
| M11 Hoàn thiện | ⬜ | |

## Bị chặn / cần người dùng quyết định
- [ ] Hỏi giảng viên (từ T0.4): Hoàng Hà và Laptop88 đang "Cần hỏi giảng viên" (xem `docs/sources/`). T4.1 chờ Hoàng Hà; T4.3/T4.4 chờ Laptop88 (người dùng chưa kiểm tra footer laptop88.vn có trang quy chế/điều khoản riêng không). M3 (GearVN) không bị chặn.

## Kết quả đo mới nhất
| Chỉ số | Giá trị | Ngày |
| --- | --- | --- |
| Coverage backend | 100% (85 pass + 15 xfail đã biết, ngưỡng 80% trong `make test-be`) | 2026-10-17 |
| Test frontend (Vitest) | 244 pass + 4 expected-fail đã biết (chưa đo coverage) | 2026-10-17 |
| Eval intent accuracy | – | |
| Eval constraint satisfaction | – | |
| Eval hallucination | – | |

## Ghi chú kỹ thuật cần nhớ (ngắn)
- (Thêm khi phát hiện điều mà phiên sau cần biết, ví dụ "GearVN cần Playwright cho trang danh sách".)
- 2026-10-16: đổi CSDL sang PostgreSQL 17 qua Docker Compose, test trên Postgres thật ([ADR-0007](adr/0007-postgresql.md) thay ADR-0002). Cần `make db-up`.
- 2026-10-17 (T0.3): trên Windows cài make bằng `winget install ezwinports.make` (make của MSYS2 làm mất biến môi trường nên `docker compose` lỗi). Thông báo tiếng Việt trong Makefile dùng `$(error)`/`$(info)`, không dùng `echo` (hỏng dấu). Target của task sau báo "Chưa khả dụng"; tên cờ script (`--site --category --pages --fixture --cases`) là giả định, T1.5/T2.6/T6.6 chỉnh Makefile nếu khác. CI chưa có job e2e (T8.8). `.prettierrc` đặt `endOfLine: auto` vì working copy CRLF. `make dev` bị kill cưỡng bức trên Windows để lại worker uvicorn mồ côi giữ cổng 8000: dừng bằng Ctrl-C. Dev server Vite đang chạy sẽ làm `npm ci` (`make setup`) lỗi EPERM: tắt trước. `npm ci` báo 7 lỗ hổng high (chưa có task).
- 2026-10-16 (T0.1): `GET /api/health` trả HTTP 200 + `status: "degraded"`, `db: "error"` khi DB lỗi. Kiểm tra DB nằm ở `services/health_service.py` (api không được import db). `DATABASE_URL`/`TEST_DATABASE_URL` là `SecretStr`.
- Test chặn socket nhưng libpq (psycopg) không đi qua Python socket nên không bị chặn; test đụng DB lỗi phải dùng engine giả (dùng URL thật sẽ treo ~2 phút trên Windows).
- Việc nhỏ chưa có task (làm khi tiện): `app/logging.py`, `app/worker.py`, CORS origin vào `config.py`, engine theo lifespan + session theo request (T1.x), chặn DNS trong fixture mạng.
- 2026-10-16 (T0.2): frontend dùng npm, Vite 8, React Router 8 (`RouterProvider` từ `react-router/dom`), Tailwind v4 (token trong `src/styles/globals.css`, không có `tailwind.config.ts`), TS 6 (không đặt `baseUrl`, chỉ `paths`), shadcn preset `vega`. Lệnh trong `frontend/`: `npm run lint|typecheck|test|format:check|build` (T0.3 gom vào `make check`; `npx tsc --noEmit` cũng phải xanh). Test dùng MSW và đỏ nếu request chưa có handler. Chế độ tối theo hệ điều hành, chưa có nút đổi (T8.1). Hook dự án chặn `rm -rf` và chuỗi đọc file `.env` trong lệnh Bash.
- 2026-10-17 (T0.5): kiểu `vitest/globals` + jest-dom chỉ có trong `tsconfig.test.json` (app loại `*.test.*`, `src/test`, `src/mocks`); `tsc -b` mới là lệnh kiểm kiểu thật (`npx tsc --noEmit` ở gốc không kiểm file nào vì `"files": []`). `strictPort` làm `make dev` lỗi khi cổng 5173 bận. `overrides` của `eslint-plugin-jsx-a11y` trong `package.json` có vì plugin chưa khai báo peer ESLint 10 (đã kiểm rule chạy thật). Mỗi route khai báo `handle.title`. `e2e/` nằm trong `tsconfig.node.json` (không có DOM lib; xem T8.8).
- 2026-10-17 (QA M0): lỗi đã biết được giữ bằng `xfail(strict=True)` (backend) và `it.fails` (Vitest) để `make check` vẫn xanh; sửa xong lỗi thì test báo XPASS/đỏ, phải gỡ dấu (xem "Xong khi" của T0.6–T0.8, T8.9, T8.10). Trên Windows, fixture chặn mạng chưa chặn asyncio/httpx async và DNS (T0.6): trước khi có T0.6 đừng viết test mới gọi `httpx.AsyncClient` tới địa chỉ thật.
- Máy dev có PostgreSQL khác ở cổng 5432 (5433, 5434 cũng bận): đặt `POSTGRES_PORT=5435` và cổng tương ứng trong `DATABASE_URL`/`TEST_DATABASE_URL` của `.env`.
