---
name: add-scraper
description: Quy trình khảo sát một trang bán lẻ và viết scraper mới (hoặc sửa parser khi trang đổi giao diện) theo BaseScraper, có fixture và test, tuân thủ robots.txt. Dùng cho các task khảo sát/viết scraper (T2.4, T3.x, T4.x, T10.1) và khi cảnh báo chất lượng parse.
argument-hint: "<site_key> [category ...]"
---

# Thêm / sửa scraper cho một trang

Tài liệu gốc: `docs/06-scraping-design.md`, `docs/02-scope-and-sources.md` §3, quy tắc `.claude/rules/scraping.md`.

## Pha A — Khảo sát (không viết code)
1. Mở `docs/sources/<site_key>.md` (tạo từ `_template.md` nếu chưa có). Mục 1–2 phải đã điền ở T0.4; nếu kết luận điều khoản là "Không dùng" → dừng.
2. Kiểm tra robots.txt của trang **có chặn agent AI** (`ClaudeBot`, `Claude-User`, `ChatGPT-User`…) không. Nếu có (từng là Laptop88, đã bị loại ở ADR-0008): **không dùng Playwright MCP hay WebFetch** với trang đó; chỉ lấy trang qua `scripts/fetch_page.py` (bot của dự án) hoặc nhờ người dùng tự lưu trang từ trình duyệt của họ.
3. **Hỏi người dùng đồng ý** rồi lưu trang bằng `uv run python scripts/fetch_page.py --site <s> --url <url> --out tests/fixtures/<s>/<tên>.html --allow-online` (đi qua Fetcher: robots, độ trễ, User-Agent trung thực). Lưu cả `robots.txt` vào fixture. Danh sách tối thiểu ở `docs/06-scraping-design.md` §8.
4. Phân tích các file đã lưu (đọc file cục bộ, không tải lại):
   - URL danh mục và cách phân trang (tham số `page` có bị robots chặn không?).
   - Có JSON-LD `Product`/`ItemList`? JSON nhúng? Sản phẩm có trong HTML tĩnh không (nếu không → cần `requires_js=True`; khi đó có thể dùng Playwright MCP để quan sát, **chỉ với trang không chặn agent AI**).
   - Selector/đường dẫn JSON cho: tên, giá, giá gốc, nhãn loại giá, link, ảnh, còn hàng, đánh giá, thông số rút gọn.
   - Trang chi tiết: bảng thông số, JSON-LD (`mpn`, `sku`, `brand`).
   - Mọi kiểu hiển thị giá và ánh xạ sang `PriceType`.
   - Rút gọn fixture < 500 KB, xóa dữ liệu cá nhân nếu có.
5. Điền mục 1 (robots đọc lại) và mục 3–7 của `docs/sources/<site_key>.md`. Số request khảo sát giữ ở mức tối thiểu (vài trang), cách nhau ≥ độ trễ của trang.

## Pha B — Viết scraper
1. Tạo `backend/app/scrapers/sites/<site_key>.py`:
   ```python
   class <Name>Scraper(BaseScraper):
       config = SiteConfig(
           key=SiteKey.<KEY>,
           base_url="https://…",
           min_delay_s=5.0,                # hoặc Crawl-delay / giá trị khảo sát nếu lớn hơn
           requires_js=False,              # theo kết quả khảo sát
           supports_live_search=…,         # theo docs/02 §1
           categories={Category.LAPTOP: "https://…", …},
       )
       def listing_url(self, category: Category, page: int) -> str: ...
       def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage: ...
       def parse_detail(self, html: str, url: str) -> ProductDetail: ...
   ```
2. Đăng ký trong `backend/app/scrapers/registry.py`.
3. Parser là hàm thuần. Thứ tự: JSON-LD → JSON nhúng → selector. Dùng helper chung `normalize.price.parse_price`, `normalize.url.clean_url`.
4. Không tạo URL có tham số bị chặn. Không gọi endpoint `/api/`, `/Ajax/` của trang.

## Pha C — Test
`backend/tests/unit/scrapers/test_<site_key>.py`:
- Mỗi fixture danh sách: số item đúng, item đầu đầy đủ trường, `has_next` đúng, URL tuyệt đối và đã làm sạch, mọi giá là `int > 0` hoặc `None`.
- Trang cuối: `has_next is False`.
- Từng loại giá → `PriceType` đúng (tham số hóa).
- Chi tiết: `raw_specs` có các khóa chính, `model_code_hint` nếu trang có.
- `listing_url` không chứa tham số bị robots.txt chặn (test bằng `RobotsCache` với robots.txt đã lưu vào fixture).
- Coverage module ≥ 90%.

## Pha D — Chạy thật (chỉ khi task yêu cầu, ví dụ T3.3/T4.5)
- Hỏi người dùng xác nhận và để **người dùng** đổi `SCRAPER_OFFLINE_ONLY=false`.
- `make scrape SITE=<site_key> CAT=<category> PAGES=1` cho từng nhóm; kiểm tra `ScrapeRun` và tỷ lệ parse.
- Ghi kết quả vào `docs/sources/<site_key>.md` mục 7. Nhắc người dùng đổi lại `SCRAPER_OFFLINE_ONLY=true`.

## Khi trang đổi giao diện
1. Lưu fixture mới (giữ fixture cũ đổi tên `*_v1.html` nếu còn hữu ích).
2. Viết test thất bại trên fixture mới trước, rồi sửa parser.
3. Cập nhật mục 4 trong `docs/sources/<site_key>.md`.
