# Product Scraper & Buyer Agent

Đồ án: **Ứng dụng Agentic AI trong Thương mại điện tử.** Một AI agent nhận yêu cầu mua sắm đồ công nghệ bằng tiếng Việt (ví dụ "laptop gaming dưới 30 triệu, RTX 4060 trở lên"), tự lập kế hoạch, lấy dữ liệu thu thập từ GearVN, Hoàng Hà Mobile, Laptop88, trả bảng so sánh có nguồn, hỗ trợ danh sách mua và cảnh báo giảm giá.

> Trạng thái: **bộ khung đặc tả** — chưa có code ứng dụng. Code được xây dần theo backlog bằng Claude Code, bắt đầu từ task T0.1.

## Phạm vi đã chốt
- **Tầng 1** (đầy đủ: lọc theo thông số, so sánh giữa trang, lịch sử giá): laptop, chuột, bàn phím, tai nghe.
- **Tầng 2** (cơ bản: tên, giá, link): mọi nhóm khác, tìm trực tiếp trên GearVN, Viettel Store, Nguyễn Kim (mock-shop khi chạy offline).
- **Mock-shop** nội bộ để minh họa phân trang và captcha giả lập (xử lý bằng human-in-the-loop).
- Stack: Python/FastAPI/LangChain + Gemini/PostgreSQL · React/Vite/TypeScript/Tailwind/shadcn/ui.

Chi tiết: [docs/README.md](docs/README.md).

## Bắt đầu với Claude Code

### 1. Chuẩn bị máy
- Python 3.11+ và [uv](https://docs.astral.sh/uv/) (hook của dự án chạy bằng `uv`, nên `uv` phải có trong PATH).
- Node.js 20 LTS+, npm, Git. Windows: dùng Git Bash hoặc WSL2 để chạy `make`; cài GNU make bằng `winget install ezwinports.make` (bản make của MSYS2 làm mất biến môi trường nên `docker compose` không chạy được).
- **Docker Desktop** (bắt buộc): PostgreSQL 17 chạy bằng Docker Compose cho cả dev và test ([ADR-0007](docs/adr/0007-postgresql.md)).
- Claude Code (CLI hoặc extension VS Code).
- API key Gemini (Google AI Studio) cho `make eval` và chạy thật. Test không cần key.
- (Tùy chọn) API key Context7 để Claude tra tài liệu thư viện mới nhất. Claude Code đọc key này từ **biến môi trường shell**, không từ `.env`: chạy `export CONTEXT7_API_KEY=...` (PowerShell: `$env:CONTEXT7_API_KEY="..."`) trước khi mở `claude`.

### 2. Khởi tạo
```bash
cd product-buyer-agent
git init && git add . && git commit -m "chore: project specification skeleton"
cp .env.example .env        # điền GOOGLE_API_KEY, ALERT_DEFAULT_EMAIL, SCRAPER_USER_AGENT (email liên hệ), đổi POSTGRES_PASSWORD…
export CONTEXT7_API_KEY=... # tùy chọn, cho MCP Context7
claude                      # mở Claude Code tại thư mục gốc
```
Bật PostgreSQL bằng `make db-up` trước khi chạy `make dev` / `make check` (`make setup` tự gọi `db-up`). `make help` liệt kê mọi lệnh; lệnh thuộc task chưa làm sẽ báo "Chưa khả dụng". Nếu cổng 5432 đã bị chiếm, đặt `POSTGRES_PORT` khác (ví dụ 5435) và sửa cổng trong `DATABASE_URL` / `TEST_DATABASE_URL` trong `.env` cho khớp.

Lần đầu mở, Claude Code hỏi cho phép MCP server trong `.mcp.json` (Playwright, Context7): chọn đồng ý.

### 3. Làm task đầu tiên
```
/next
```
Claude chọn T0.1, tóm tắt yêu cầu. Sau đó vào Plan mode (Shift+Tab) và:
```
/plan-task T0.1
```
Duyệt kế hoạch → Claude code + test → `/check` → `/review` → `/done T0.1`. Lặp lại với `/next`.

Sau mỗi milestone: nhờ Claude gọi subagent `qa-tester`, rồi gõ `/clear` để bắt đầu phiên gọn.

## Bộ công cụ cho Claude Code

| Thành phần | Vị trí | Vai trò |
| --- | --- | --- |
| Bộ nhớ dự án | `CLAUDE.md` | Tổng quan, lệnh, quy trình, quy tắc bắt buộc; tự nạp `docs/PROGRESS.md` |
| Quy tắc theo thư mục (thay cho CLAUDE.md con) | `.claude/rules/*.md` | Tự nạp khi Claude làm việc với file backend, frontend, scraping, test |
| Skill quy trình | `.claude/skills/{next,plan-task,check,review,done,eval}` | Gọi bằng `/tên` |
| Skill kiến thức | `.claude/skills/{add-scraper,add-category,agent-tool,ui-screen,write-tests}` | Claude tự dùng khi làm việc tương ứng |
| Subagent | `.claude/agents/{code-reviewer,qa-tester}.md` | Review diff; viết test biên cuối milestone |
| Hook | `.claude/hooks/*.py` + `.claude/settings.json` | Chặn lệnh nguy hiểm, bảo vệ `.env` và ADR, tự format sau khi sửa file |
| Quyền | `.claude/settings.json` | Cho phép sẵn lệnh test/lint/git cục bộ; hỏi trước khi push/curl; cấm force push, `rm -rf`, đọc `.env` |
| MCP | `.mcp.json` | Playwright (khảo sát trang, chụp UI), Context7 (tài liệu thư viện) |

## Cấu trúc
```
CLAUDE.md                bộ nhớ dự án
.claude/                 settings, hooks, rules, skills, agents
.mcp.json                MCP servers
.env.example             biến môi trường
docker-compose.yml       PostgreSQL (từ T0.3), toàn bộ ứng dụng (từ T9.4; `make demo-up`)
docs/                    01–11 đặc tả, ADR, eval, nguồn, ảnh UI, PROGRESS
backend/, frontend/      (tạo ở M0)
```

## Tùy chỉnh giao diện theo ý bạn
Đặt phác thảo/ảnh tham khảo vào `docs/ui/` (tên file theo màn hình), sửa bảng token ở `docs/08-ui-ux.md` §5, rồi giao việc bằng skill `ui-screen`.

## Tuân thủ
Dự án chỉ thu thập dữ liệu sản phẩm công khai, tôn trọng robots.txt, độ trễ ≥ 5 giây mỗi trang (Laptop88 10 giây), User-Agent trung thực, không đăng nhập, không đặt hàng hộ, không vượt captcha thật. Mặc định chạy offline (mock-shop + fixture). Điều khoản sử dụng của từng trang phải được đọc và duyệt ở task T0.4 trước khi chạy với trang thật. Xem [docs/02-scope-and-sources.md](docs/02-scope-and-sources.md).
