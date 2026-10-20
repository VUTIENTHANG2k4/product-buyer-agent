# Tiến độ dự án

> Claude Code cập nhật file này ở bước `/done` của mỗi milestone (`/done <task>` chỉ sửa dòng "Đang làm"). Giữ **dưới 60 dòng**: chỉ trạng thái hiện tại, không ghi nhật ký dài (lịch sử đã có trong git log).
> Backlog đầy đủ: [11-roadmap-backlog.md](11-roadmap-backlog.md)

## Trạng thái
- Đang làm: M5 trên nhánh `milestone/M5-normalize-match` — T5.1 ✅, đang làm T5.2 (T5.3 hoãn sang M6 vì cần T6.1; T4.6 không gộp)
- Task kế tiếp đề xuất: `/plan-task M5` trong Plan mode. Người dùng nhớ đặt lại `SCRAPER_OFFLINE_ONLY=true` trong `.env`.
- Cập nhật lần cuối: 2026-10-20 — M4 đã merge vào main; bắt đầu M5

## Milestone
| Milestone | Trạng thái | Ghi chú |
| --- | --- | --- |
| M0 Nền tảng | ✅ | Đã qua `qa-tester` 2 lần; T0.9 đã xong (trong M2) |
| M1 Dữ liệu | ✅ | Đã qua `qa-tester`; T1.6–T1.8 xong (T1.7, T1.8 ở M3b) |
| M2 Hạ tầng thu thập | ✅ | Qua `code-reviewer` + `qa-tester`; T2.7 xong ở M3b, còn T2.8 (cùng T7.4) |
| M3 GearVN | ✅ | Qua `code-reviewer` + `qa-tester`; chạy thật 4 nhóm `PAGES=1` 80/80 mục parse đúng. M3b (T1.7, T1.8, T3.4, T2.7) qua `code-reviewer`, **bỏ qua `qa-tester`** theo quyết định của người dùng |
| M4 FPT Shop + An Phát (thay Hoàng Hà + Laptop88) | ✅ | Qua `code-reviewer` + `qa-tester`; chạy thật 8 lượt `PAGES=1` (194 offer, 100% parse). Backlog: T4.6 (seed/test), T4.7, T4.8 |
| M5 Chuẩn hóa & ghép | 🔄 | Nhánh `milestone/M5-normalize-match` |
| M6 Agent | ⬜ | |
| M7 API | ⬜ | |
| M8 Frontend | ⬜ | Có thêm T8.9, T8.10 (từ QA M0) |
| M9 Theo dõi giá | ⬜ | |
| M10 Tầng 2 | ⬜ | |
| M11 Hoàn thiện | ⬜ | |

## Bị chặn / cần người dùng quyết định
- Không có (nguồn đã đổi sang FPT Shop + An Phát, người dùng đã duyệt T0.4 ngày 2026-10-19; [ADR-0008](adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)).

## Kết quả đo mới nhất
| Chỉ số | Giá trị | Ngày |
| --- | --- | --- |
| Coverage backend | 99,47% (3043 pass + 7 xfail đã biết, ngưỡng 80% trong `make test-be`, ~2 phút) | 2026-10-20 |
| Test frontend (Vitest) | 244 pass + 4 expected-fail đã biết (chưa đo coverage) | 2026-10-17 |
| Eval intent accuracy | – | |
| Eval constraint satisfaction | – | |
| Eval hallucination | – | |

## Ghi chú kỹ thuật cần nhớ (ngắn)
- 2026-10-16: đổi CSDL sang PostgreSQL 17 qua Docker Compose, test trên Postgres thật ([ADR-0007](adr/0007-postgresql.md) thay ADR-0002). Cần `make db-up`.
- 2026-10-17 (T0.3): trên Windows cài make bằng `winget install ezwinports.make` (make của MSYS2 làm mất biến môi trường nên `docker compose` lỗi). Thông báo tiếng Việt trong Makefile dùng `$(error)`/`$(info)`, không dùng `echo` (hỏng dấu). Target của task sau báo "Chưa khả dụng"; tên cờ script (`--site --category --pages --fixture --cases`) là giả định, T1.5/T2.6/T6.6 chỉnh Makefile nếu khác. CI chưa có job e2e (T8.8). `.prettierrc` đặt `endOfLine: auto` vì working copy CRLF. `make dev` bị kill cưỡng bức trên Windows để lại worker uvicorn mồ côi giữ cổng 8000: dừng bằng Ctrl-C. Dev server Vite đang chạy sẽ làm `npm ci` (`make setup`) lỗi EPERM: tắt trước. `npm ci` báo 7 lỗ hổng high (chưa có task).
- 2026-10-16 (T0.1): `GET /api/health` trả HTTP 200 + `status: "degraded"`, `db: "error"` khi DB lỗi. Kiểm tra DB nằm ở `services/health_service.py` (api không được import db). `DATABASE_URL`/`TEST_DATABASE_URL` là `SecretStr`.
- Test chặn socket nhưng libpq (psycopg) không đi qua Python socket nên không bị chặn; test đụng DB lỗi phải dùng engine giả (dùng URL thật sẽ treo ~2 phút trên Windows).
- Việc nhỏ chưa có task (làm khi tiện): `app/logging.py`, `app/worker.py`, CORS origin vào `config.py`, engine theo lifespan + session theo request (T1.x). Từ review T0.7: trần trên cho timeout/delay (UA chứa ký tự điều khiển đã dồn vào T2.1), miền của `MOCK_SHOP_DELAY_SECONDS ≥ 0` và `MOCK_SHOP_CAPTCHA_AFTER ≥ 1`. `Settings()` giờ lỗi khi giá trị ngoài miền (xem chú thích trong `.env.example`).
- 2026-10-16 (T0.2): frontend dùng npm, Vite 8, React Router 8 (`RouterProvider` từ `react-router/dom`), Tailwind v4 (token trong `src/styles/globals.css`, không có `tailwind.config.ts`), TS 6 (không đặt `baseUrl`, chỉ `paths`), shadcn preset `vega`. Lệnh trong `frontend/`: `npm run lint|typecheck|test|format:check|build` (T0.3 gom vào `make check`; `npx tsc --noEmit` cũng phải xanh). Test dùng MSW và đỏ nếu request chưa có handler. Chế độ tối theo hệ điều hành, chưa có nút đổi (T8.1). Hook dự án chặn `rm -rf` và chuỗi đọc file `.env` trong lệnh Bash.
- 2026-10-17 (T0.5): kiểu `vitest/globals` + jest-dom chỉ có trong `tsconfig.test.json` (app loại `*.test.*`, `src/test`, `src/mocks`); `tsc -b` mới là lệnh kiểm kiểu thật (`npx tsc --noEmit` ở gốc không kiểm file nào vì `"files": []`). `strictPort` làm `make dev` lỗi khi cổng 5173 bận. `overrides` của `eslint-plugin-jsx-a11y` trong `package.json` có vì plugin chưa khai báo peer ESLint 10 (đã kiểm rule chạy thật). Mỗi route khai báo `handle.title`. `e2e/` nằm trong `tsconfig.node.json` (không có DOM lib; xem T8.8).
- 2026-10-17 (T0.8): lỗi nghiệp vụ ném lớp con của `AppError` (`app/domain/errors.py`, khớp bảng 07 §2; có test đối chiếu docs); không ném `HTTPException`. `FastAPI(responses=error_responses(422, 500))` ở `main.py` giữ schema lỗi chuẩn cho mọi route; router chỉ thêm 404/409... qua `error_responses(...)`. `UnhandledErrorMiddleware` phải thêm trước `CORSMiddleware`. Lỗi 422 có `details.errors[{in, field, message, type}]` (không có `input`). Fixture `disable_network` (T0.6) chặn cả asyncio Proactor lẫn DNS; lỗi chặn từ `httpx.AsyncClient` đến tay test dưới dạng `ExceptionGroup` (anyio), dùng `expect_blocked()` trong `test_network_guard_edge.py`. Hook ruff xoá import chưa dùng ngay sau mỗi lần sửa: thêm import cùng lần sửa với đoạn dùng nó.
- 2026-10-17 (T1.1): DTO chặt hơn docs cũ (đã ghi ở 04 §6): số nguyên strict (không nhận bool/chuỗi/float), `SpecFilter.value` phải khớp `op`, URL chỉ là `HttpUrl` (bỏ utm/userinfo/fragment là `clean_url` của T2.5, lưu DB bằng `str(url)`). `extra="forbid"` cho `QueryIntent` hoãn sang T6.3 (cần kiểm Gemini). Backend vẫn còn 12 xfail của QA M0 lần hai, gỡ ở T0.9 và T2.1.
- Máy dev có PostgreSQL khác ở cổng 5432 (5433, 5434 cũng bận): đặt `POSTGRES_PORT=5435` và cổng tương ứng trong `DATABASE_URL`/`TEST_DATABASE_URL` của `.env`.
- 2026-10-17 (T1.3): `LaptopSpecs.gpu_rank` là `computed_field` chỉ đọc (tính từ `gpu_model`, có trong `model_dump()` để lọc JSONB; đầu vào `gpu_rank` bị bỏ qua). Specs dùng `extra="ignore"`, số nguyên strict và > 0 (riêng `gpu_vram_gb` cho 0). `SPEC_MODELS`/`REQUIRED_FIELDS` là `MappingProxyType`; quy ước "None hoặc list rỗng = thiếu" chưa có hàm dùng chung (`missing_required_fields` để T5.1). GPU chưa có trong bảng §5.6 (GTX, RX, Ti/Super mới, Arc rời, MX) chuẩn hóa được tên nhưng `gpu_rank = null`.
- 2026-10-17 (T1.2): chạy `alembic` từ `backend/` (`make migrate`). Test DB cần `make db-up`; conftest lấy `TEST_DATABASE_URL` từ env rồi `.env`, đổi host `localhost` → `127.0.0.1` (trên Windows `localhost` thử IPv6 trước và treo 3 s mỗi kết nối mới; nên đặt 127.0.0.1 trong `.env`, `.env.example` đã đổi) và chỉ chạy khi tên DB kết thúc `_test`. Dùng `db_session` (rollback bằng savepoint; test lỗi ràng buộc bọc `session.begin_nested()`) và `tests/factories.py`. Enum là VARCHAR + CHECK: thêm giá trị enum phải viết migration tay (test so CHECK với enum sẽ đỏ nếu quên). JSONB không theo dõi sửa tại chỗ: gán lại cả dict. `offer.price` NOT NULL, `product.brand` NOT NULL (chi tiết docs/04 §3).
- 2026-10-17 (T1.4): repository đồng bộ, nhận `Session`, chỉ `flush` (không commit), thời gian truyền qua `now`; chi tiết ở docs/04 §3. Test repository ở `backend/tests/integration/repositories/` (tên file `test_repo_*.py` để không trùng basename). Dùng `session.exec`; truy vấn nhiều cột dùng `sqlalchemy.select` + `session.execute`. Cột `xmax` trong `upsert` là thủ thuật PostgreSQL để biết dòng mới (đã kiểm trên PG 17).
- 2026-10-17 (T1.5): script trong `backend/scripts/` chạy bằng `python -m scripts.<tên>` từ `backend/` (chạy `python scripts/x.py` không import được `app`); Makefile `eval` còn gọi kiểu cũ (T6.6 sửa). `make seed FIXTURE=dev|eval|e2e [RESET=1]`: `--reset` xóa sạch DB nên bắt buộc `--yes`. Dữ liệu ở `backend/tests/fixtures/seed/*.json` (tên "Mock", URL `.example`), sinh một lần rồi sửa tay; mỗi profile mô tả ở docs/09 §3. `make check` giờ chạy mypy cả `scripts/`. Test `test_seed_data.py` giữ một transaction suốt module: đừng gộp test seed khác vào cùng module.
- 2026-10-17 (QA M1): 26 `xfail(strict=True)` mới trong `*_m1.py` (8 lỗi → T1.6–T1.8; 3 ca cần quyết định thiết kế dồn vào T6.2); XPASS báo đỏ, khi đó gỡ dấu xfail. Rủi ro chưa xử lý: seed rất "sạch" (T6.6 nên thêm vài sản phẩm thiếu specs/hết hàng cố ý).
- 2026-10-19 (M2): mọi request qua `Fetcher` (`scrapers/http/`, robots.txt tự phân tích hỗ trợ `*`/`$`, `post_form` chỉ mock-shop); `MOCK_SHOP_URL` chỉ nhận localhost. Pipeline ở `scrapers/pipeline.py`, gọi qua `ScrapeService` (hook `on_price_changes` cho M9); `resolve_product_interim` tạm thay matcher đến T5.2. `make scrape SITE=mockshop CAT=laptop` cần `make db-up`, `make migrate`, `make mock-shop`; lượt mockshop tắt các offer `mockshop` cùng nhóm không còn trong mock-shop (kể cả dữ liệu `make seed`). Fixture mock-shop sinh bằng `python -m scripts.save_mockshop_fixtures` (có test báo lệch). selectolax 1.0.0 chỉ có `selectolax.lexbor`.
- 2026-10-19 (công cụ): công cụ Write/Edit giải mã chuỗi `\uXXXX` trong nội dung (regex có `\u00a0` thành ký tự thật): kiểm lại bằng `grep` sau khi ghi. Heredoc lồng nhau trong Bash dễ lỗi nháy: dùng Write cho file dài. Console Windows/pipe là cp1252: script in tiếng Việt phải đổi stdout sang UTF-8 (`scripts.scrape.configure_console`).
- 2026-10-19 (M3): `GearVNScraper` đọc thẻ `a.product-card` theo `data-slot`, chi tiết theo JSON-LD `additionalProperty`; `raw_specs` của danh sách để rỗng nên pipeline tải chi tiết (20/lượt; 13/80 sản phẩm GearVN không có thông số có nhãn). `PAGES=1` luôn cho `PARTIAL`; lượt đầy đủ nhóm chuột cũng `PARTIAL` (thẻ ngừng kinh doanh tính là lỗi). Chi tiết `docs/sources/gearvn.md` mục 7.
- 2026-10-19 (M3b): robots.txt 403/429/challenge CDN → `RobotsBlocked` → lượt `BLOCKED` + nghỉ 24 giờ (429 không chờ `Retry-After`). Fetcher đọc thân theo luồng, từ chối > 5 MB sau giải nén (`ResponseTooLarge`). `clean_url` giữ mã hóa query gốc, sắp tham số, viết hoa hex: offer có query có thể đổi khóa so với trước. `ListingPage.pagination_loop` báo vòng lặp phân trang. `MockShopLocation` cho phép import registry mà không cần đủ env. Hạng GPU thêm RTX 3070/3070 Ti/3080 (ước lượng); chuỗi GPU > 500 ký tự → `None`. Chưa có QA biên cho Fetcher streaming và `clean_url`: nghi lỗi thì thử hai chỗ này trước.
- 2026-10-19 (M4): FPT Shop duyệt qua sitemap (danh mục chỉ ~25 sản phẩm tĩnh), mỗi "trang" là lô 20 sản phẩm, JSON-LD `Product`; lỗi tải rời rạc bị bỏ qua, 3 lỗi liên tiếp mới dừng; 404/410 đếm vào `ListingPage.gone` (không cấm tắt offer). An Phát: trang nào cũng có form đăng ký chứa chữ captcha nên `AnPhatScraper.detect_challenge` loại đúng tên form đó (5xx không loại); `scripts.fetch_page` dùng detector của scraper. `detect_challenge` bỏ thân `<script>` nội tuyến (quét tuyến tính). Seed/test còn dùng hoangha/laptop88 (T4.6).
