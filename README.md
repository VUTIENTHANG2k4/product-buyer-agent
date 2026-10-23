# Product Scraper & Buyer Agent

Đồ án: **Ứng dụng Agentic AI trong Thương mại điện tử.** Một AI agent nhận yêu cầu mua sắm đồ công nghệ bằng tiếng Việt (ví dụ "laptop gaming dưới 30 triệu, RTX 4060 trở lên"), tự lập kế hoạch, lấy dữ liệu đã thu thập từ GearVN, FPT Shop, An Phát, trả bảng so sánh có nguồn, hỗ trợ danh sách mua và cảnh báo giảm giá.

> Trạng thái: M0–M11 hoàn tất; còn một số mục backlog (T11.5: giảm độ trễ trả lời). Tiến độ chi tiết: [docs/PROGRESS.md](docs/PROGRESS.md).

## Chức năng
- **Hỏi bằng tiếng Việt**: agent lập kế hoạch, hiện tiến trình (SSE), trả bảng so sánh dựng từ cơ sở dữ liệu (không từ số do LLM viết); hỏi lại khi câu quá mơ hồ.
- **Tầng 1** (đầy đủ: lọc theo thông số, so sánh giữa trang, lịch sử giá): laptop, chuột, bàn phím, tai nghe.
- **Tầng 2** (cơ bản: tên, giá, link, nhãn "chưa chuẩn hóa"): nhóm khác, tìm trực tiếp trên GearVN và FPT Shop (cache 6 giờ). Khi chạy offline chỉ tìm trên mock-shop.
- **Danh sách mua** và **cảnh báo giảm giá** (email/Telegram), worker làm mới giá theo lịch.
- **Trang quản trị** `/admin`: nguồn dữ liệu, lượt thu thập, xử lý captcha giả lập (human-in-the-loop).
- **Mock-shop** nội bộ minh họa phân trang và captcha giả lập.

Stack: Python 3.11+ / FastAPI / LangChain + Gemini / PostgreSQL 17 · React / Vite / TypeScript / Tailwind / shadcn/ui. Kiến trúc: [docs/03-architecture.md](docs/03-architecture.md). Mục lục tài liệu: [docs/README.md](docs/README.md).

## Chạy thử

### Yêu cầu máy
- Python 3.11+ và [uv](https://docs.astral.sh/uv/); Node.js 20 LTS+ và npm; Git.
- **Docker Desktop** (bắt buộc): PostgreSQL 17 chạy bằng Docker Compose cho dev, test và demo ([ADR-0007](docs/adr/0007-postgresql.md)).
- Windows: dùng Git Bash hoặc WSL2 để chạy `make`; cài GNU make bằng `winget install ezwinports.make` (bản make của MSYS2 làm mất biến môi trường nên `docker compose` không chạy được).
- API key Gemini (Google AI Studio) cho `make eval` và hỏi agent bằng LLM thật. Test không cần key.

### Phát triển
```bash
cp .env.example .env     # điền GOOGLE_API_KEY, ALERT_DEFAULT_EMAIL, SCRAPER_USER_AGENT (email liên hệ), POSTGRES_PASSWORD…
make setup               # bật DB, cài phụ thuộc, migrate, seed dev
make dev                 # API :8000, frontend :5173, mock-shop :8100
```
Nếu cổng 5432 đã bị chiếm, đặt `POSTGRES_PORT` khác (ví dụ 5435) và sửa cổng trong `DATABASE_URL` / `TEST_DATABASE_URL` / `E2E_DATABASE_URL` cho khớp.

### Demo trong Docker (không cần cài Python/Node)
```bash
make demo-up             # db, api (tự migrate), worker, mock-shop, web
make demo-seed           # nạp dữ liệu hư cấu (lần đầu)
# giao diện http://localhost:8080 · API http://localhost:8000/api/docs
make db-down             # dừng tất cả, giữ dữ liệu
```
Kịch bản trình diễn: [docs/10-deployment.md](docs/10-deployment.md#7-kịch-bản-demo-bảo-vệ).

### Lệnh thường dùng
| Lệnh | Việc |
| --- | --- |
| `make check` | Cổng chất lượng: ruff, mypy, pytest, eslint, tsc, vitest |
| `make e2e` | Playwright E2E (LLM giả; cần cổng 5173/8010/8100 trống) |
| `make eval` | Đánh giá agent với LLM thật (cần `GOOGLE_API_KEY`), báo cáo ở `reports/` |
| `make scrape SITE=mockshop CAT=laptop` | Một lượt thu thập |
| `make seed FIXTURE=dev\|eval\|e2e` | Nạp dữ liệu hư cấu |
| `make worker` | Bộ lập lịch (cần `SCHEDULER_ENABLED=true`) |
| `make gen-api` | Sinh kiểu TypeScript từ OpenAPI |
| `make help` | Liệt kê mọi lệnh |

## Chất lượng đã đo
| Chỉ số | Giá trị |
| --- | --- |
| Backend | 6578 test pass (+ 55 `xfail` đã biết), coverage 99,11% |
| Frontend | 1067 test Vitest, 10 test E2E Playwright |
| Eval agent (31 câu, `gemini-3.5-flash-lite`, 2026-10-23) | intent ≥ 96%, ràng buộc ≥ 98%, 0 hallucination, hỏi lại 100%; latency p50 26–31 s (chưa đạt mục tiêu 15 s, do thời gian trả lời của Gemini) |

Chi tiết và cách đo: [docs/PROGRESS.md](docs/PROGRESS.md), [docs/05-agent-design.md](docs/05-agent-design.md#7-đánh-giá-agent-eval).

## Cấu trúc
```
CLAUDE.md                bộ nhớ dự án cho Claude Code
.claude/                 settings, hooks, rules, skills, agents
.mcp.json                MCP servers (Playwright, Context7)
.env.example             biến môi trường
docker-compose.yml       db (dev/test) và cả hệ thống (demo)
backend/                 FastAPI, agent, scrapers, normalize, services, db, mock_shop, scripts, tests
frontend/                React + Vite, Playwright e2e
docs/                    01–11 đặc tả, ADR, eval, nguồn, ảnh UI, PROGRESS
reports/                 báo cáo eval (không đưa vào git)
```
Sơ đồ chi tiết: [docs/03-architecture.md](docs/03-architecture.md#6-cấu-trúc-thư-mục-theo-code-sau-m10).

## Làm việc với Claude Code
Dự án được xây theo milestone bằng Claude Code. Quy trình và quy tắc bắt buộc nằm ở [CLAUDE.md](CLAUDE.md); backlog ở [docs/11-roadmap-backlog.md](docs/11-roadmap-backlog.md).

| Thành phần | Vị trí | Vai trò |
| --- | --- | --- |
| Bộ nhớ dự án | `CLAUDE.md` | Tổng quan, lệnh, quy trình, quy tắc; tự nạp `docs/PROGRESS.md` |
| Quy tắc theo thư mục | `.claude/rules/*.md` | Tự nạp khi làm với file backend, frontend, scraping, test |
| Skill quy trình | `.claude/skills/{next,plan-task,check,review,done,eval}` | Gọi bằng `/tên` |
| Skill kiến thức | `.claude/skills/{add-scraper,add-category,agent-tool,ui-screen,write-tests}` | Claude tự dùng khi phù hợp |
| Subagent | `.claude/agents/{code-reviewer,qa-tester}.md` | Review diff; viết test biên cuối milestone |
| Hook / quyền | `.claude/hooks/*.py`, `.claude/settings.json` | Chặn lệnh nguy hiểm, bảo vệ `.env` và ADR, tự format |
| MCP | `.mcp.json` | Playwright (khảo sát trang, chụp UI), Context7 (tài liệu thư viện) |

Claude Code đọc `CONTEXT7_API_KEY` từ **biến môi trường shell**, không từ `.env`. Vòng lặp mỗi milestone: `/next` → Plan mode → `/plan-task` → code + test → `/check` → `/review` → `qa-tester` → `/done`.

## Tuân thủ
Dự án chỉ thu thập dữ liệu sản phẩm công khai, tôn trọng robots.txt, độ trễ ≥ 5 giây mỗi domain (lớn hơn nếu robots.txt có `Crawl-delay`), User-Agent trung thực, không đăng nhập, không đặt hàng hộ, không vượt captcha thật. Mặc định chạy offline (`SCRAPER_OFFLINE_ONLY=true`: mock-shop + fixture); chạy với trang thật chỉ khi người dùng tự bật. Điều khoản sử dụng của từng trang đã được đọc và duyệt ở T0.4 (xem [docs/sources/](docs/sources/)). Chi tiết: [docs/02-scope-and-sources.md](docs/02-scope-and-sources.md).
