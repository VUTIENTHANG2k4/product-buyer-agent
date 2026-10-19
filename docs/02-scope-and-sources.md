# 02. Phạm vi sản phẩm và nguồn dữ liệu

> Phiên bản 1.0 · 2026-10-16 · Dữ liệu robots.txt đọc ngày 2026-10-16
> Liên quan: [01 Yêu cầu](01-requirements.md) · [06 Thiết kế thu thập](06-scraping-design.md)

## 1. Ma trận trang × nhóm sản phẩm

Dựa trên menu trang chủ và kết quả tìm kiếm ngày 2026-10-16. "Cần xác minh" nghĩa là chưa thấy rõ, phải kiểm tra lại bằng Playwright MCP trong task khảo sát.

| Trang | Laptop | Chuột | Bàn phím | Tai nghe | Điện thoại (mở rộng) | Tầng 2 (tìm trực tiếp) |
| --- | --- | --- | --- | --- | --- | --- |
| GearVN | **Lõi** | **Lõi** | **Lõi** | **Lõi** | Không bán | Có |
| Hoàng Hà Mobile | **Lõi** | Cần xác minh | Cần xác minh | Cần xác minh | Mở rộng | **Không** (robots chặn `/tim-kiem`) |
| Laptop88 | **Lõi** | **Lõi** | **Lõi** | **Lõi** | Không bán | **Không** (xem mục 3) |
| Viettel Store | Mở rộng | Mở rộng | Không thấy | Mở rộng | Mở rộng | Có |
| Nguyễn Kim | Mở rộng | Không thấy | Không thấy | Không thấy | Mở rộng | Có |
| Mock-shop (nội bộ) | Có | Có | Có | Có | – | Có (dev/test/demo) |

Quy tắc: một nhóm thuộc tầng 1 khi có **ít nhất 2 trang lõi** cung cấp, để so sánh giữa các trang có ý nghĩa. Với điện thoại (pha mở rộng X1), Viettel Store và Nguyễn Kim được nâng thành trang lõi của nhóm này, cùng Hoàng Hà.

## 2. Kết quả robots.txt (đọc ngày 2026-10-16)

| Trang | Bot chung (`*`) | Đường dẫn bị chặn liên quan | Crawl-delay | Ghi chú |
| --- | --- | --- | --- | --- |
| GearVN | Cho phép `/` | `/gio-hang`, `/thanh-toan`, `/design-system`, `/tai-khoan`, `/api/` | Không khai báo | Không chặn trang tìm kiếm |
| Hoàng Hà Mobile | Cho phép `/` | `/*filters=`, `/tim-kiem`, `/tin-tuc/search`, `/so-sanh/`, `/Ajax/`, `/account/`, `/gio-hang/` | Không khai báo | Không dùng bộ lọc và tìm kiếm của trang |
| Laptop88 | Cho phép `/` | `/*?specMap=`, `/*?filter=` | 2 s (bot chung); 10 s (bot tìm kiếm AI) | Chặn hoàn toàn `ClaudeBot`, `GPTBot`, `ChatGPT-User`, `CCBot`, `Bytespider` |
| Viettel Store | Cho phép | Chỉ thư mục kỹ thuật (`/DataFiles/`, `/bin/`, `/css/`, `/js/`, …) | Không khai báo | |
| Nguyễn Kim | Cho phép `/` | `/checkout`, `/account`, `/cart/`, `/orders/`, `/login`, `/register`, `/otp`, `/compare`, `/search-order`, `/maintenance` | Không khai báo | `/maintenance` thêm ở lần đọc lại 2026-10-17 (T0.4) |

Nguồn: `https://<domain>/robots.txt` của từng trang. **robots.txt có thể thay đổi**, vì vậy hệ thống luôn đọc lại lúc chạy (cache 24 giờ), không dựa vào bảng này.

## 3. Chính sách tuân thủ (bắt buộc trong code)

1. **Kiểm tra robots.txt trước mọi request** bằng `urllib.robotparser` với User-Agent của hệ thống. URL bị chặn thì bỏ qua và ghi log, không thử cách khác.
2. **User-Agent trung thực**: `ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: <email>)`. Không giả trình duyệt, không giả Googlebot.
3. **Độ trễ mỗi domain** = max(`SCRAPER_MIN_DELAY_SECONDS` = 5 s, Crawl-delay trong robots.txt, `min_delay` cấu hình riêng của trang). Một request đồng thời mỗi domain. (Mock-shop nội bộ dùng `MOCK_SHOP_DELAY_SECONDS` riêng.)
4. **Laptop88 dùng 10 s** và **không dùng cho tìm kiếm trực tiếp theo yêu cầu người dùng (tầng 2)**. Lý do: trang này chặn rõ các agent AI truy cập thay người dùng (`ChatGPT-User`) và cho bot tìm kiếm AI 10 s. Ta chỉ thu thập định kỳ theo lịch, chậm, giống bot chỉ mục. Khi khảo sát, **không** dùng Playwright MCP hay WebFetch (công cụ của trợ lý AI) với Laptop88; fixture lấy qua bot của dự án hoặc người dùng tự lưu trang ([06 §8](06-scraping-design.md#8-fixtures)). Đây là cách hiểu thận trọng; nếu điều khoản sử dụng (task T0.4) cấm thì loại Laptop88 khỏi danh sách nguồn.
5. **Không dùng URL có tham số lọc/sắp xếp/tìm kiếm bị chặn.** Duyệt trang danh mục thuần (và tham số phân trang nếu được phép), lọc ở phía hệ thống.
6. **Không đăng nhập, không chạm giỏ hàng/thanh toán, không thu thập dữ liệu cá nhân** (tên người đánh giá, số điện thoại…). Chỉ lấy: tên, giá, loại giá, tình trạng hàng, thông số, ảnh đại diện (URL), điểm đánh giá tổng hợp, link.
7. **Gặp captcha, mã 403, hoặc 429 vẫn lặp lại sau khi đã chờ `Retry-After` trên trang thật** (định nghĩa chi tiết ở [06 §4](06-scraping-design.md#4-phát-hiện-challenge-và-chặn)): dừng lượt chạy, đánh dấu `BLOCKED`, tăng thời gian chờ cho domain đó (24 giờ), báo trên trang quản trị. Không tự giải captcha.
8. **Giới hạn khối lượng**: `SCRAPER_MAX_LISTING_PAGES` trang danh sách mỗi lượt; chỉ mở trang chi tiết khi danh sách thiếu thông số bắt buộc.
9. **Chế độ offline mặc định** (`SCRAPER_OFFLINE_ONLY=true`): khi phát triển chỉ chạy mock-shop và fixture. Bật truy cập thật là quyết định có chủ ý.

## 4. Trang không dùng và lý do

| Trang | Lý do |
| --- | --- |
| Shopee | Chống bot nhiều lớp, cần đăng nhập; điều khoản cảnh báo việc vượt rào cản truy cập. API chính thức là Affiliate (cần đăng ký, chưa xác minh cho Việt Nam). |
| Tiki | Chặn công cụ đọc robots.txt khi khảo sát; không có API công khai cho tìm kiếm sản phẩm. |
| Lazada | Sàn TMĐT, khả năng chống bot chưa đánh giá; ngoài phạm vi nhóm sản phẩm lõi. |
| Phong Vũ, Thành Nhân, XGear, Sendo | Không cho truy cập tự động khi khảo sát. |
| FPT Shop, CellphoneS, HACOM, An Phát, Thế Giới Di Động, Memoryzone, Di Động Việt | Chặn tìm kiếm/bộ lọc hoặc có độ trễ cao; để dành nếu cần mở rộng. |

## 5. URL danh mục đã biết (cần xác minh trong task khảo sát)

| Trang | Nhóm | URL đã thấy |
| --- | --- | --- |
| GearVN | Laptop / Chuột / Bàn phím / Tai nghe | Đã xác minh ở T3.1 (2026-10-19): `https://gearvn.com/collections/laptop`, `/collections/chuot-may-tinh`, `/collections/ban-phim-may-tinh`, `/collections/tai-nghe-may-tinh` (danh mục tổng; bộ sưu tập theo dòng GPU là tập con nên không dùng). Chi tiết: [sources/gearvn.md](sources/gearvn.md) |
| Hoàng Hà Mobile | Laptop gaming | `https://hoanghamobile.com/laptop/laptop-gaming` |
| Viettel Store | Chuột / Tai nghe | `https://viettelstore.vn/phu-kien/chuot-pkid010005001.html`, `https://viettelstore.vn/phu-kien/tai-nghe-pkid010005005.html` |
| Nguyễn Kim | Laptop / Điện thoại | `https://www.nguyenkim.com/laptop.c`, `https://www.nguyenkim.com/dien-thoai.c` |
| Laptop88 | Tất cả | Chưa xác định, khảo sát trong T4.3 |

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
