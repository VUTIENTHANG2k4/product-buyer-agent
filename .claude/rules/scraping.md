---
paths:
  - "backend/app/scrapers/**"
  - "backend/app/mock_shop/**"
  - "backend/app/normalize/**"
  - "backend/tests/fixtures/**"
  - "backend/scripts/scrape.py"
  - "docs/sources/**"
---

# Quy tắc thu thập dữ liệu

Nguồn: `docs/02-scope-and-sources.md` §3 và `docs/06-scraping-design.md`. Các quy tắc sau là bắt buộc, không có ngoại lệ:

1. Mọi request đi qua `Fetcher` (robots.txt, độ trễ domain, retry, offline mode). Scraper không tự tạo `httpx.Client`.
2. Độ trễ = max(`SCRAPER_MIN_DELAY_SECONDS`, Crawl-delay, `SiteConfig.min_delay_s`). Không giảm `min_delay_s` của trang thật dưới giá trị trong tài liệu (`docs/sources/<site>.md` và `Crawl-delay` của robots.txt, ví dụ An Phát = 5 s).
3. User-Agent lấy từ cấu hình. Không đặt header giả trình duyệt, không cookie đăng nhập.
4. Không tạo URL chứa tham số mà robots.txt của trang chặn (ví dụ GearVN: `/api/`; mục Disallow của từng trang ghi trong `docs/sources/<site>.md`). Lọc ở phía hệ thống.
5. Ưu tiên parse JSON-LD → JSON nhúng → selector CSS. Ghi rõ lựa chọn trong `docs/sources/<site>.md`.
6. `parse_listing`, `parse_detail`, `parse_search` là hàm thuần (không I/O, không đọc đồng hồ). Mỗi hàm có test trên fixture.
7. Giá bị che hoặc không đọc được → `None`, không đoán. Ánh xạ loại giá sang `PriceType` có test cho từng loại.
8. Không lưu dữ liệu cá nhân (tên người đánh giá, số điện thoại, email).
9. Captcha/chặn trên trang thật → `BLOCKED`. Không viết code giải captcha, không đổi IP/User-Agent để né. Chỉ mock-shop có luồng nhập đáp án.
10. Không đổi `SCRAPER_OFFLINE_ONLY` trong `.env`. Lệnh chạy trang thật chỉ thực hiện khi task yêu cầu và người dùng xác nhận.
11. Fixture: < 500 KB, bỏ script quảng cáo, đặt tên theo `docs/06-scraping-design.md` §8. Lấy trang thật bằng `scripts/fetch_page.py` (qua Fetcher) sau khi người dùng đồng ý.
12. Không dùng Playwright MCP hay WebFetch với trang có robots.txt chặn agent AI (`ClaudeBot`, `Claude-User`, `ChatGPT-User`…; hiện chưa có nguồn nào như vậy sau ADR-0008). Với các trang khác, Playwright MCP chỉ để quan sát vài trang, không tải hàng loạt.
13. Pipeline không gọi `app/services`; đánh giá cảnh báo do `services/scrape_service.py` làm sau khi pipeline trả về.
