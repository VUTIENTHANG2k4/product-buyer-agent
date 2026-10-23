# 02. Phạm vi sản phẩm và nguồn dữ liệu

> Phiên bản 1.0 · 2026-10-16 · Dữ liệu robots.txt đọc ngày 2026-10-16
> Liên quan: [01 Yêu cầu](01-requirements.md) · [06 Thiết kế thu thập](06-scraping-design.md)

## 1. Ma trận trang × nhóm sản phẩm

Dựa trên menu trang chủ và kết quả tìm kiếm ngày 2026-10-16. "Cần xác minh" nghĩa là chưa thấy rõ, phải kiểm tra lại bằng Playwright MCP trong task khảo sát.

| Trang | Laptop | Chuột | Bàn phím | Tai nghe | Điện thoại (mở rộng) | Tầng 2 (tìm trực tiếp) |
| --- | --- | --- | --- | --- | --- | --- |
| GearVN | **Lõi** | **Lõi** | **Lõi** | **Lõi** | Không bán | Có |
| FPT Shop | **Lõi** | **Lõi** | **Lõi** | **Lõi** | Mở rộng | Có (`/tim-kiem?s=`, HTML dựng sẵn, T10.1; xem [sources/fptshop.md](sources/fptshop.md)) |
| An Phát Computer | **Lõi** | **Lõi** | **Lõi** | **Lõi** | Không bán | **Không** (robots chặn `/tim`) |
| Viettel Store | Mở rộng | Mở rộng | Không thấy | Mở rộng | Mở rộng | **Không** (kết quả tìm kiếm nạp bằng JS, [ADR-0010](adr/0010-tier2-sites-gearvn-fptshop.md)) |
| Nguyễn Kim | Mở rộng | Không thấy | Không thấy | Không thấy | Mở rộng | **Không** (Next.js, kết quả tìm kiếm nạp bằng JS, [ADR-0010](adr/0010-tier2-sites-gearvn-fptshop.md)) |
| Mock-shop (nội bộ) | Có | Có | Có | Có | – | Có (dev/test/demo) |

Quy tắc: một nhóm thuộc tầng 1 khi có **ít nhất 2 trang lõi** cung cấp, để so sánh giữa các trang có ý nghĩa. Với điện thoại (pha mở rộng X1), Viettel Store và Nguyễn Kim được nâng thành trang lõi của nhóm này, cùng FPT Shop.

Từ 2026-10-19 ([ADR-0008](adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)) Hoàng Hà Mobile và Laptop88 không còn là nguồn (lý do ở mục 4); FPT Shop và An Phát thay vào. Các ô "Cần xác minh" của hai trang mới được điền ở T4.1 và T4.3.

## 2. Kết quả robots.txt (đọc ngày 2026-10-16)

| Trang | Bot chung (`*`) | Đường dẫn bị chặn liên quan | Crawl-delay | Ghi chú |
| --- | --- | --- | --- | --- |
| GearVN | Cho phép `/` | `/gio-hang`, `/thanh-toan`, `/design-system`, `/tai-khoan`, `/api/` | Không khai báo | Không chặn trang tìm kiếm |
| FPT Shop | Cho phép `/` (đọc bản gốc 2026-10-19); không chặn `ClaudeBot`/`ChatGPT-User` | `/admin/`, `/cms/`, `/web/`, `/ajax/`, `/gio-hang/`, `/so-sanh-san-pham/`, `/dien-dan/`, `/tai-khoan/`, `/don-hang/`, `/dat-hang/`; hơn 40 mẫu tham số (`/*sort=`, `/*muc-gia=`, `/*hang-san-xuat=`, `/*utm_*=`…) và `/*t=` | Không khai báo | `Sitemap: /sitemap.xml`; danh mục phân trang bằng "Xem thêm" (API), nên thu thập qua sitemap |
| An Phát Computer | Hai nhóm `*` được gộp (đọc bản gốc 2026-10-19); không chặn `ClaudeBot`/`ChatGPT-User` nhưng chặn `OAI-SearchBot`, `CCBot`, `PerplexityBot`, `Google-Extended`, `Bytespider`, `Amazonbot`… | `/admin/`, `/ajax/`, `/cart`, `/cart/*`, `/tim` | 5 s | Tên miền chính `www.anphatpc.com.vn`; không chặn `?page=N` |
| Viettel Store | Cho phép | Chỉ thư mục kỹ thuật (`/DataFiles/`, `/bin/`, `/css/`, `/js/`, …) | Không khai báo | |
| Nguyễn Kim | Cho phép `/` | `/checkout`, `/account`, `/cart/`, `/orders/`, `/login`, `/register`, `/otp`, `/compare`, `/search-order`, `/maintenance` | Không khai báo | `/maintenance` thêm ở lần đọc lại 2026-10-17 (T0.4) |

Nguồn: `https://<domain>/robots.txt` của từng trang. **robots.txt có thể thay đổi**, vì vậy hệ thống luôn đọc lại lúc chạy (cache 24 giờ), không dựa vào bảng này.

## 3. Chính sách tuân thủ (bắt buộc trong code)

1. **Kiểm tra robots.txt trước mọi request** bằng `urllib.robotparser` với User-Agent của hệ thống. URL bị chặn thì bỏ qua và ghi log, không thử cách khác.
2. **User-Agent trung thực**: `ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: <email>)`. Không giả trình duyệt, không giả Googlebot.
3. **Độ trễ mỗi domain** = max(`SCRAPER_MIN_DELAY_SECONDS` = 5 s, Crawl-delay trong robots.txt, `min_delay` cấu hình riêng của trang). Một request đồng thời mỗi domain. (Mock-shop nội bộ dùng `MOCK_SHOP_DELAY_SECONDS` riêng.)
4. **Trang chặn agent AI trong robots.txt** (`ClaudeBot`, `ChatGPT-User`…) **không dùng cho tìm kiếm trực tiếp theo yêu cầu người dùng (tầng 2)**, chỉ thu thập định kỳ theo lịch, chậm (giống bot chỉ mục) và với độ trễ không thấp hơn giá trị trang khai báo cho bot AI. Khi khảo sát trang như vậy **không** dùng Playwright MCP hay WebFetch (công cụ của trợ lý AI); fixture lấy qua bot của dự án hoặc người dùng tự lưu trang ([06 §8](06-scraping-design.md#8-fixtures)). Hiện không còn trang nguồn nào thuộc diện này (Laptop88, trang duy nhất trước đây, đã bị loại ở [ADR-0008](adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)); quy tắc giữ lại cho trang thêm sau. Mọi trang mới vẫn phải qua T0.4 (điều khoản) trước khi chạy thật.
5. **Không dùng URL có tham số lọc/sắp xếp/tìm kiếm bị chặn.** Duyệt trang danh mục thuần (và tham số phân trang nếu được phép), lọc ở phía hệ thống.
6. **Không đăng nhập, không chạm giỏ hàng/thanh toán, không thu thập dữ liệu cá nhân** (tên người đánh giá, số điện thoại…). Chỉ lấy: tên, giá, loại giá, tình trạng hàng, thông số, ảnh đại diện (URL), điểm đánh giá tổng hợp, link.
7. **Gặp captcha, mã 403, hoặc 429 vẫn lặp lại sau khi đã chờ `Retry-After` trên trang thật** (định nghĩa chi tiết ở [06 §4](06-scraping-design.md#4-phát-hiện-challenge-và-chặn)): dừng lượt chạy, đánh dấu `BLOCKED`, tăng thời gian chờ cho domain đó (24 giờ), báo trên trang quản trị. Không tự giải captcha. Riêng robots.txt trả 403, 429 hoặc trang challenge của CDN thì coi là bị chặn ngay (không chờ `Retry-After`), xem [06 §3](06-scraping-design.md#3-fetcher).
8. **Giới hạn khối lượng**: `SCRAPER_MAX_LISTING_PAGES` trang danh sách mỗi lượt; chỉ mở trang chi tiết khi danh sách thiếu thông số bắt buộc.
9. **Chế độ offline mặc định** (`SCRAPER_OFFLINE_ONLY=true`): khi phát triển chỉ chạy mock-shop và fixture. Bật truy cập thật là quyết định có chủ ý.

## 4. Trang không dùng và lý do

| Trang | Lý do |
| --- | --- |
| Shopee | Chống bot nhiều lớp, cần đăng nhập; điều khoản cảnh báo việc vượt rào cản truy cập. API chính thức là Affiliate (cần đăng ký, chưa xác minh cho Việt Nam). |
| Tiki | Chặn công cụ đọc robots.txt khi khảo sát; không có API công khai cho tìm kiếm sản phẩm. |
| Lazada | Sàn TMĐT, khả năng chống bot chưa đánh giá; ngoài phạm vi nhóm sản phẩm lõi. |
| Hoàng Hà Mobile | Loại ngày 2026-10-19 ([ADR-0008](adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)). Quy chế cấm khai thác mục đích thương mại khi không có văn bản cho phép nên cần xác nhận từ giảng viên; người dùng chọn không chờ. robots.txt chặn `/*filters=`, `/tim-kiem`, `/Ajax/`… Khảo sát cũ: [sources/hoangha.md](sources/hoangha.md). |
| Laptop88 | Loại ngày 2026-10-19 (ADR-0008). robots.txt chặn `ClaudeBot`, `GPTBot`, `ChatGPT-User`, `CCBot`, `Bytespider` (bot chung 2 s, bot tìm kiếm AI 10 s) và `/*?specMap=`, `/*?filter=`; chưa tìm được trang quy chế/điều khoản riêng. Khảo sát cũ: [sources/laptop88.md](sources/laptop88.md). |
| CellphoneS | robots.txt chặn mọi URL có `?`, kể cả phân trang (khảo sát sơ bộ 2026-10-19). |
| HACOM | Chặn trang chi tiết và `ClaudeBot` (khảo sát sơ bộ 2026-10-19). |
| Phong Vũ, Thành Nhân, XGear, Sendo | Không cho truy cập tự động khi khảo sát (2026-10-16). Phong Vũ là phương án dự phòng cho M4: điều khoản chỉ cấm dùng thương mại, chưa biết có cần JavaScript. |
| Thế Giới Di Động, Memoryzone, Di Động Việt | Chặn tìm kiếm/bộ lọc hoặc có độ trễ cao; để dành nếu cần mở rộng. |

## 5. URL danh mục đã biết (cần xác minh trong task khảo sát)

| Trang | Nhóm | URL đã thấy |
| --- | --- | --- |
| GearVN | Laptop / Chuột / Bàn phím / Tai nghe | Đã xác minh ở T3.1 (2026-10-19): `https://gearvn.com/collections/laptop`, `/collections/chuot-may-tinh`, `/collections/ban-phim-may-tinh`, `/collections/tai-nghe-may-tinh` (danh mục tổng; bộ sưu tập theo dòng GPU là tập con nên không dùng). Chi tiết: [sources/gearvn.md](sources/gearvn.md) |
| FPT Shop | Laptop / Chuột / Bàn phím / Tai nghe | Không dùng URL danh mục: lấy URL sản phẩm từ `https://fptshop.com.vn/products/sitemap-may-tinh-xach-tay.xml` và `sitemap-phu-kien*.xml` (T4.1). Chi tiết: [sources/fptshop.md](sources/fptshop.md) |
| An Phát Computer | Laptop / Chuột / Bàn phím / Tai nghe | `https://www.anphatpc.com.vn/may-tinh-xach-tay-laptop.html`, `/chuot-may-tinh_dm1291.html`, `/ban-phim-may-tinh_dm1027.html`, `/tai-nghe_dm1180.html`, phân trang `?page=N` (T4.3). Chi tiết: [sources/anphat.md](sources/anphat.md) |
| Viettel Store | Chuột / Tai nghe | `https://viettelstore.vn/phu-kien/chuot-pkid010005001.html`, `https://viettelstore.vn/phu-kien/tai-nghe-pkid010005005.html` |
| Nguyễn Kim | Laptop / Điện thoại | `https://www.nguyenkim.com/laptop.c`, `https://www.nguyenkim.com/dien-thoai.c` |

Kết quả khảo sát từng trang ghi vào `docs/sources/<site>.md` (mẫu: [docs/sources/_template.md](sources/_template.md)).

## 6. Rủi ro

| Rủi ro | Khả năng | Ảnh hưởng | Giảm thiểu |
| --- | --- | --- | --- |
| Trang đổi giao diện làm hỏng parser | Cao | Trung bình | Fixture + test; cảnh báo khi tỷ lệ parse thành công < 80%; ưu tiên dữ liệu JSON nhúng (JSON-LD) hơn selector CSS |
| Bị chặn IP | Trung bình | Cao | Độ trễ lớn, khối lượng nhỏ, chế độ offline mặc định, mock-shop để demo |
| Điều khoản cấm thu thập tự động | Chưa rõ | Cao | Task T0.4 đọc điều khoản trước khi chạy thật; loại trang vi phạm |
| Thông số không đồng nhất giữa trang | Cao | Trung bình | Bộ trích xuất theo luật + LLM dự phòng + test vàng |
| Giá hiển thị khác loại (thành viên, flash sale) | Cao | Trung bình | Trường `price_type`; so sánh bằng `effective_price` ([04 §4](04-data-model.md#4-enum)) |
| Chi phí/giới hạn LLM | Thấp | Trung bình | Gemini Flash, cache, `AGENT_MAX_STEPS` |
