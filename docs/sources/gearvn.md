# Nguồn: GearVN (`gearvn`)

> Khảo sát ngày: 2026-10-17 (mục 1–2), 2026-10-19 (mục 3–7) · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T0.4 (mục 1–2), T3.1 (mục 3–7)

## 1. robots.txt
- Ngày đọc: 2026-10-17 (`https://gearvn.com/robots.txt`). Giống bảng [02 §2](../02-scope-and-sources.md#2-kết-quả-robotstxt-đọc-ngày-2026-10-16), không có thay đổi.
- Quy tắc áp dụng cho `*`: `Allow: /`; `Disallow: /gio-hang`, `/thanh-toan`, `/design-system`, `/tai-khoan`, `/api/`. Có `Sitemap: https://gearvn.com/sitemap.xml`.
- Crawl-delay: không khai báo.
- Độ trễ cấu hình (`min_delay`): 5 s (mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link:
  - Điều khoản dịch vụ: https://gearvn.com/pages/dieu-khoan-dich-vu
  - Chính sách bảo mật: https://gearvn.com/pages/chinh-sach-bao-mat
  - Không thấy trang "quy chế hoạt động" riêng trong footer; đã thử `/pages/quy-che-hoat-dong` (404).
- Có điều khoản về thu thập tự động không? **Không tìm thấy.**
  - Điều khoản dịch vụ chỉ có 3 mục: 1. Giới thiệu (gồm quyền đổi điều khoản không cần báo trước), 2. Hướng dẫn sử dụng website (độ tuổi, năng lực hành vi, từ chối quảng cáo qua email), 3. Thanh toán. Không có đoạn nào về bot, crawler, scraping, sao chép nội dung hay sở hữu trí tuệ.
  - Chính sách bảo mật chỉ nói về thu thập và sử dụng thông tin cá nhân của khách hàng.
- Kết luận (đã duyệt ở T0.4, ghi trong PROGRESS): **Được dùng**, theo 02 §3 (robots.txt, độ trễ, không chạm `/api/`, giỏ hàng, thanh toán).
- Ghi chú về cách đọc: công cụ đọc trang trả về tóm tắt và trích ngắn, không phải toàn văn. Kết luận "không tìm thấy" dựa trên danh sách mục và nội dung công cụ trả về; người dùng nên mở 2 link trên đối chiếu nhanh.

## 3. Danh mục theo nhóm
Khảo sát 2026-10-19 (T3.1): URL lấy từ menu trang chủ; các trang đã lưu ở mục 6.

| Nhóm | URL danh mục | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| laptop | `https://gearvn.com/collections/laptop` | `?page=N` (20 thẻ/trang) | 210 (11 trang) |
| mouse | `https://gearvn.com/collections/chuot-may-tinh` | `?page=N` | 159 (8 trang) |
| keyboard | `https://gearvn.com/collections/ban-phim-may-tinh` | `?page=N` | 522 (27 trang) |
| headset | `https://gearvn.com/collections/tai-nghe-may-tinh` | `?page=N` | 205 (11 trang) |

- `/collections/laptop` là danh mục laptop tổng (cả gaming lẫn văn phòng), nên `Category.laptop` gồm cả hai; các bộ sưu tập theo dòng GPU ở [02 §5](../02-scope-and-sources.md#5-url-danh-mục-đã-biết-cần-xác-minh-trong-task-khảo-sát) là tập con, không dùng. Chuột và "Lót chuột" cùng nằm trong `chuot-may-tinh` (menu ghi "Chuột + Lót chuột"): tên sản phẩm là cách phân biệt, việc lọc để sau.
- Con số ước tính lấy từ dòng "N kết quả" của trang 1 (không phải lời hứa của trang). `robots.txt` không chặn `?page=` nên URL phân trang là hợp lệ (có test).
- `requires_js`: **False**. Trang dựng sẵn ở máy chủ: thẻ sản phẩm nằm trong HTML tĩnh, không cần Playwright, không cần gọi `/api/`.

## 4. Cấu trúc dữ liệu
Thứ tự ưu tiên 06 §6 chỉ áp dụng được một phần: trang danh sách **không có** JSON-LD sản phẩm, nên danh sách parse bằng selector, còn chi tiết dùng JSON-LD.

**Trang danh sách** (`/collections/<slug>?page=N`, cũng là cấu trúc của trang tìm kiếm):
- JSON-LD chỉ có `CollectionPage` (khoảng giá `AggregateOffer`) và `BreadcrumbList`; không có `ItemList`/`Product`.
- Mỗi sản phẩm là một thẻ `a.product-card[href="/products/<slug>"]` (20 thẻ/trang). Trong thẻ (nên chọn theo thuộc tính `data-slot` thay vì lớp Tailwind, vì lớp là chuỗi tiện ích dài và dễ đổi):
  - tên: thẻ `p` trong `[data-slot=product-card-content]`; ảnh: `img[src]` (CDN `cdn.hstatic.net`);
  - thông số rút gọn: `[data-slot=product-specs]` gồm các `span` con, mỗi chip có một biểu tượng SVG và giá trị trong `span.truncate`. **Chip không có nhãn** (ví dụ `Intel® UHD Graphics`, `15.6 inch`, `Core 5`, `512 GB`, `IPS`), số chip và thứ tự khác nhau giữa sản phẩm;
  - giá: xem mục 5; khuyến mãi quà tặng: `[data-slot=product-promotion]` (chỉ là văn bản, không phải giá);
  - không có điểm đánh giá, số lượt đánh giá, mã sản phẩm hay tình trạng kho trên thẻ.
- Phân trang: `<link rel="next" href="…?page=N+1">` và `<link rel="prev">` ở `<head>` (scraper chỉ trả `next_url` khi cùng đường dẫn với trang hiện tại; nếu trỏ ra ngoài danh mục thì `has_next` vẫn đúng nhưng `next_url` rỗng và `crawl_category` tự dựng `?page=N+1`); trang cuối (mouse `?page=8`, 19 thẻ) chỉ có `rel="prev"` → `has_next = False`. `canonical` của trang N chứa `?page=N`.
- Trang tìm kiếm `/search?q=<từ khóa>` (robots.txt cho phép, trang `noindex`): cùng thẻ `a.product-card`, 20 thẻ, không có `rel=next` (chưa kiểm tra phân trang của tìm kiếm; tầng 2 chỉ cần trang đầu).

**Trang chi tiết** (`/products/<slug>`):
- JSON-LD `Product`: `name`, `brand.name`, `category`, `image[]`, `sku` (mã nội bộ của GearVN, ví dụ `LAP-ACER-ASPIRE-LITE-AL15-53P-56QH`; **không có `mpn`**), `offers.price` (giá bán, số nguyên VND), `offers.priceSpecification` với `priceType = StrikethroughPrice` (giá gốc, chỉ có khi đang giảm), `offers.availability` (`https://schema.org/InStock`…).
- `additionalProperty[]`: danh sách `{name, value}` **có nhãn** (ví dụ `Card đồ họa`, `Dung lượng RAM`, `Dung lượng SSD`, `Tấm nền`; chuột: `Cảm biến (Sensor)`, `Độ phân giải (DPI)`, `Trọng lượng`). Các chip của thẻ danh sách là phần đầu của danh sách này (cùng giá trị) nhưng thẻ không cho biết nhãn.
- Không có `<table>` thông số, không có `aggregateRating`: chưa có điểm đánh giá để lấy.
- Trang có thêm khoảng 9 thẻ `a.product-card` "sản phẩm liên quan": parser chi tiết không được đọc chúng.

## 5. Loại giá hiển thị
Kết quả đếm trên 6 trang đã lưu có thẻ sản phẩm (4 trang 1 + trang cuối chuột + trang tìm kiếm, tổng 119 thẻ):

| Kiểu hiển thị trên thẻ | Số thẻ | `price` | `list_price` | `price_type` | Ghi chú |
| --- | --- | --- | --- | --- | --- |
| Một giá | 13 | giá đó | `None` | `regular` | |
| Giá gốc gạch ngang + nhãn `-N%` + giá bán | 88 | giá bán (số sau) | giá gốc (số trước) | `sale` | Nhãn `-N%` (hoặc "Giảm N%" ở góc ảnh) là giảm giá công khai, không phải giá thành viên. |
| `Liên hệ tư vấn` (`[data-slot=product-discontinued-price]`) | 18 | `None` | `None` | `unknown` | Sản phẩm ngừng kinh doanh: 18/19 thẻ của trang cuối chuột. Không đoán giá. |
| Không thấy kiểu khác | – | – | – | – | Không có giá thành viên, flash sale hay giá bị che bằng dấu `***` trong các trang đã lưu. |

- Quy tắc đọc giá của scraper (không đoán): đúng một giá → `regular`; đúng hai giá với giá đầu lớn hơn giá sau → `sale`; mọi bố cục khác (hai giá bằng nhau hoặc giá gốc thấp hơn, từ ba giá trở lên) → `price = None`, kèm log `WARNING`. Chưa gặp bố cục nào như vậy trên trang thật.
- Các văn bản "Mua kèm giá ưu đãi: PRE-ORDER GIẢM NGAY 300.000Đ" và "Tặng …" trong `[data-slot=product-promotion]` là khuyến mãi kèm theo, **không** được đọc thành giá (viết hoa `Đ`, nằm trong khối khuyến mãi).
- Chi tiết: `offers.price` là giá bán; `StrikethroughPrice` là giá gốc.
- Tình trạng kho: thẻ danh sách không có (→ `StockStatus.unknown`); chi tiết có `availability`. Thẻ "Liên hệ tư vấn" chưa có dấu hiệu kho riêng.

## 6. Fixtures đã lưu
Lưu ngày 2026-10-19 bằng bot dự án qua Fetcher (robots.txt, độ trễ ≥ 5 s, User-Agent trung thực; một tiến trình cho cả lượt) trong `backend/tests/fixtures/gearvn/`. Đã bỏ `<script>` (trừ JSON-LD), `<style>`, nội dung SVG và ảnh `data:` để dưới 500 KB; DOM còn nguyên. Còn lại thông tin liên hệ của doanh nghiệp ở chân trang và JSON-LD `Organization` (email `cskh@gearvn.com`, mã số thuế); không có dữ liệu cá nhân (test `test_gearvn_fixtures.py` kiểm).

| File | Nội dung |
| --- | --- |
| `robots.txt` | Bản gốc, 168 ký tự |
| `listing_laptop_p1.html`, `listing_mouse_p1.html`, `listing_keyboard_p1.html`, `listing_headset_p1.html` | Trang 1 của 4 nhóm (20 thẻ, có `rel=next`) |
| `listing_mouse_p8.html` | Trang cuối: 19 thẻ, chỉ `rel=prev`, 18 thẻ "Liên hệ tư vấn" |
| `detail_laptop-acer-aspire-lite-15-al15-53p-56qh.html` | Laptop đang giảm 20% (có `StrikethroughPrice`) |
| `detail_chuot-gaming-khong-day-logitech-pro-x3-superstrike-lightspeed-black.html` | Chuột đang giảm 16%, có khuyến mãi PRE-ORDER |
| `search_chuot_razer.html` | `/search?q=chuot+razer` (20 thẻ) |

Trang chủ (2 MB) chỉ dùng để tìm URL danh mục, không lưu. Chưa có fixture cho trang danh sách giữa chừng (có cả `rel=prev` và `rel=next`); T3.2 dựng trường hợp này từ trang 1 và trang cuối khi cần.

## 7. Vấn đề và lưu ý
- **Thông số trên thẻ không có nhãn.** `ListingItem.raw_specs` là `nhãn → giá trị`, nên thẻ chỉ đưa được các giá trị không nhãn. Pipeline (06 §7, T2.6) chỉ tải trang chi tiết cho thẻ có `raw_specs` rỗng, tối đa 20 trang mỗi lượt. **Đã chọn ở T3.2:** `raw_specs` của thẻ danh sách để rỗng (không nhét giá trị không nhãn) nên pipeline tải trang chi tiết và lấy thông số có nhãn từ JSON-LD `additionalProperty`; tên sản phẩm của laptop đã chứa CPU/RAM/SSD/màn hình/hệ điều hành cho bộ trích xuất theo luật ở M5. Hệ quả: một lượt có tối đa 20 trang chi tiết (mỗi trang ≥ 5 s) nên phần lớn sản phẩm của lượt đầy đủ chưa có thông số có nhãn; xem lại giới hạn này (hoặc đọc chip trên thẻ) ở T5.1/T5.2.
- Không có `mpn`: `model_code_hint` chỉ lấy `mpn` nếu trang có (hiện luôn `None`). `sku` của GearVN là mã nội bộ nên không dùng làm mã hãng; mã trong tên (ví dụ `AL15-53P-56QH`) để bộ trích xuất ở M5 xử lý. `site_sku` của `ListingItem` cũng `None` vì thẻ không có mã.
- Không có đánh giá sao: `rating`, `rating_count` luôn `None`.
- Trang cuối nhóm chuột gồm hầu hết sản phẩm ngừng kinh doanh (không giá): mỗi thẻ này tính vào `items_failed` (giá không đọc được) nên một lượt chạy **đầy đủ** nhóm chuột có thể kết thúc `PARTIAL` do tỷ lệ lỗi > 20% dù parse đúng; pipeline coi các mục "hết giá" là an toàn (không chặn việc tắt offer). Cân nhắc tách "không giá" khỏi "lỗi" ở pipeline khi chạy đầy đủ (M9).
- Chuẩn hóa ở scraper: tiêu đề gộp khoảng trắng (giữ dấu cách giữa thẻ inline); nhãn và giá trị `additionalProperty` về NFC và bỏ ký tự NUL; `src` ảnh hỏng chỉ làm `image_url=None`; thẻ phải trỏ tới `/products/<slug>`; JSON-LD trong `@graph` được đọc, JSON-LD lồng quá sâu bị bỏ qua. Tiêu đề chưa NFC hay lọc ký tự điều khiển: để M5.
- `robots.txt` không chặn agent AI, nhưng khảo sát chỉ dùng bot dự án (khoảng 10 trang, 2026-10-19). Không gọi `/api/`.
- Số lượng: bàn phím 27 trang; với độ trễ 5–6 s một lượt đầy đủ mất vài phút (xem `SCRAPER_MAX_LISTING_PAGES`).
- Tình trạng kho: thẻ danh sách luôn `StockStatus.unknown` (kể cả "Liên hệ tư vấn"); `availability` của trang chi tiết được đọc từ T9.3 (`ProductDetail.stock_status`) và chỉ dùng khi làm mới giá offer đang theo dõi; lượt đầy đủ vẫn giữ tồn kho đã biết thay vì ghi đè bằng `unknown`.
- 503 kèm trang chờ Cloudflare (`cf-mitigated: challenge`…) được Fetcher trả ngay và coi là challenge → `BLOCKED` và nghỉ 24 giờ (T2.7c); chưa gặp trên GearVN, chỉ có test với phản hồi giả.
- **Kết quả chạy thật (T3.3, 2026-10-19)**, `make scrape SITE=gearvn CAT=<nhóm> PAGES=1`, bot dự án, `SCRAPER_OFFLINE_ONLY=false` do người dùng tự đặt (đã nhắc đặt lại `true`):

  | Nhóm | Trạng thái | Trang | Mục đọc được | Lỗi | Offer | Có thông số có nhãn |
  | --- | --- | --- | --- | --- | --- | --- |
  | laptop | PARTIAL (giới hạn trang) | 1 | 20 | 0 | 20 | 19 |
  | mouse | PARTIAL (giới hạn trang) | 1 | 20 | 0 | 20 | 18 |
  | keyboard | PARTIAL (giới hạn trang) | 1 | 20 | 0 | 20 | 14 |
  | headset | PARTIAL (giới hạn trang) | 1 | 20 | 0 | 20 | 16 |

  - Tỷ lệ parse 80/80 = 100% (ngưỡng ≥ 90%); không `FAILED`, `BLOCKED`, captcha, 403 hay 429. `PARTIAL` chỉ vì `PAGES=1` mà còn trang sau (đã chốt với người dùng là chấp nhận).
  - 80 offer có URL duy nhất, không có giá ≤ 0: 70 `sale` (giá gốc + giá bán) và 10 `regular`. Chưa lượt nào gặp thẻ "Liên hệ tư vấn" (chỉ nằm ở trang cuối nhóm chuột).
  - Pipeline đã thử tải trang chi tiết của cả 80 mục (20 mục/lượt, đúng giới hạn 20 trang chi tiết). 67/80 offer có `raw_specs` có nhãn; 13 offer còn lại (4 tai nghe, 6 bàn phím, 1 laptop, 2 chuột) **không** thiếu vì lỗi tải hay parser: trang chi tiết của chúng có JSON-LD `Product` nhưng không có `additionalProperty` và không có phần "Thông số kỹ thuật" nào trong HTML (đã kiểm hai trang thật). Đây là khoảng trống dữ liệu của GearVN; phần thông số của chúng chỉ có thể lấy từ tên sản phẩm hoặc chip trên thẻ (xem điểm đầu của mục này).
  - `detect_brand` chưa nhận ra 12/80 sản phẩm (hãng `Unknown`, ví dụ HyperWork, Pulsar): xem lại ở M5 (chuẩn hóa hãng).
  - Chưa chạy lượt đầy đủ (57 trang danh sách) và chưa kiểm tra trang giữa chừng có cả `rel=prev` lẫn `rel=next`.
- T3.4: robots.txt bị CDN chặn (403, 429, 5xx challenge) → `RobotsBlocked` → lượt `BLOCKED` và nghỉ 24 giờ (chỉ có test với phản hồi giả; GearVN thật chưa gặp). Liên kết trang sau đọc bằng `link[rel~=next]` nên `rel="prev next"` cũng được nhận.
- Chưa xử lý, để M5 (matcher): cùng sản phẩm xuất hiện với `href` http và https là hai khóa URL khác nhau; cùng URL xuất hiện ở hai nhóm (khóa `offer.url` là duy nhất nên chỉ một bản được giữ; chưa kiểm tra hành vi khi hai lượt tranh nhau).
