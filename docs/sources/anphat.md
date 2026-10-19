# Nguồn: An Phát Computer (`anphat`)

> Khảo sát ngày: 2026-10-19 · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T4.3
> Người dùng đã duyệt kết luận điều khoản ngày 2026-10-19 (sau khi tự mở link đối chiếu). Lý do chọn trang: [ADR-0008](../adr/0008-fptshop-anphat-replace-hoangha-laptop88.md).

## 1. robots.txt
- Ngày đọc: 2026-10-19 (`https://www.anphatpc.com.vn/robots.txt`). Lần đầu bằng WebFetch (tóm tắt), sau đó **bản gốc lưu bằng Fetcher** tại `backend/tests/fixtures/anphat/robots.txt` (763 ký tự); các mục dưới đây theo bản gốc.
- Quy tắc áp dụng cho `*` (có **hai** nhóm `User-agent: *`, được gộp theo RFC 9309; `parse_robots` của dự án đã kiểm: cả hai nhóm đều có hiệu lực):
  - Nhóm 1: `Disallow: /admin/`, `/ajax/`, `/cart`, `/cart/*`; `Crawl-delay: 5`.
  - Nhóm 2 (cuối file, trong khối chú thích `hurasoft-fix`): `Disallow: /tim` → chặn mọi đường dẫn bắt đầu bằng `/tim` (gồm `/tim-kiem…`), nên **không có tìm kiếm trực tiếp (tầng 2)**.
  - Không có `Allow`; không có mẫu chứa tham số truy vấn: `?page=N` được phép.
  - Các nhóm chặn hoàn toàn (`Disallow: /`): `OAI-SearchBot`, `CCBot`, `Google-Extended`, `Bytespider`, `PerplexityBot`, `AhrefsBot`, `SemrushBot`, `MJ12bot`, `DotBot`, `DataForSeoBot`, `Amazonbot`, `Applebot-Extended`. `ClaudeBot`, `Claude-User`, `ChatGPT-User`, `GPTBot` không có nhóm riêng nên rơi vào `*`. Vì trang chặn nhiều bot AI khác, chỉ thu thập định kỳ, chậm, khối lượng nhỏ, không dùng cho tầng 2.
  - `Sitemap: https://www.anphatpc.com.vn/sitemap.xml` (chỉ mục `sitemap_category.xml`, `sitemap_product.xml`, `sitemap_pc.xml`, `sitemap_brand.xml`…; không dùng vì danh mục phân trang được).
- **Tên miền chính: `www.anphatpc.com.vn`** (thẻ `canonical`, mọi liên kết trong trang, sitemap). Công cụ WebFetch từng báo `anphat.com.vn` là nhầm; `anphat.com.vn` chỉ còn xuất hiện ở URL ảnh sản phẩm (`https://anphat.com.vn/media/product/…`).
- Crawl-delay: 5 s (nhóm 1).
- Độ trễ cấu hình (`min_delay`): 5 s (= `Crawl-delay`, bằng mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link (footer mục "Chính sách chung"; không có "Quy chế hoạt động", "Điều khoản sử dụng" hay "Điều khoản mua bán"):
  - Chính sách bán hàng: https://www.anphatpc.com.vn/chinh-sach-ban-hang.html
  - Bảo mật thông tin khách hàng: https://www.anphatpc.com.vn/chinh-sach-bao-mat.html
  - Chính sách vận chuyển: https://www.anphatpc.com.vn/giao-hang.html
  - Chính sách bảo hành: https://www.anphatpc.com.vn/trung-tam-bao-hanh.html
  - Chính sách kiểm hàng: https://www.anphatpc.com.vn/chinh-sach-kiem-hang.html
  - Chính sách cho doanh nghiệp: https://www.anphatpc.com.vn/phong-du-an-va-khach-hang-doanh-nghiep.html
- Có điều khoản về thu thập tự động không? **Không tìm thấy** trong hai trang đã đọc (Chính sách bán hàng, Bảo mật thông tin khách hàng). Hạn chế: công cụ đọc trang chỉ đọc ~100.000 ký tự đầu mỗi trang (phần lớn là menu điều hướng); người dùng đã tự mở các trang để đối chiếu khi duyệt.
- Kết luận (**đã duyệt** bởi người dùng, 2026-10-19): **Được dùng**, theo 02 §3 (robots.txt, `Crawl-delay: 5`, không chạm `/admin/`, `/ajax/`, `/cart`, `/tim`). Chỉ thu thập định kỳ, chậm, khối lượng nhỏ, không dùng cho tầng 2; dữ liệu thật không đăng công khai (ADR-0008).

## 3. Danh mục theo nhóm
URL lấy từ menu trang chủ và đã mở lại bằng Fetcher ngày 2026-10-19. Chọn danh mục tổng của mỗi nhóm (tập con "chơi game" không dùng).

| Nhóm | URL danh mục | Phân trang | Sản phẩm / trang | Tổng (2026-10-19) |
| --- | --- | --- | --- | --- |
| laptop | `https://www.anphatpc.com.vn/may-tinh-xach-tay-laptop.html` | `?page=N` | 24 | 980 (41 trang) |
| mouse | `https://www.anphatpc.com.vn/chuot-may-tinh_dm1291.html` | `?page=N` | 30 | 342 (12 trang) |
| keyboard | `https://www.anphatpc.com.vn/ban-phim-may-tinh_dm1027.html` | `?page=N` | 30 | 420 (14 trang) |
| headset | `https://www.anphatpc.com.vn/tai-nghe_dm1180.html` | `?page=N` | 30 | 117 (4 trang) |

- Tổng lấy từ chuỗi "N kết quả" trong HTML của trang. Kiểm tra bằng trình duyệt trên nhóm chuột: `?page=2` và `?page=11` trả 30 sản phẩm **khác** trang 1 (0 trùng); `?page=12` trả 12 sản phẩm (trang cuối); `?page=13` trả HTTP 200 với **0 sản phẩm**; `?page=0` và `?page=1` trả trang 1. `?p=` và `?trang=` bị bỏ qua. Không có `rel="next"`; nút "Xem thêm N sản phẩm" (số cố định = tổng − 30, nạp bằng JavaScript qua `/ajax/` bị robots.txt chặn) **không dùng**. Vì vậy `has_next` suy ra từ tổng và cỡ trang: `trang × cỡ trang < tổng`.
- `requires_js`: **False**. Thẻ sản phẩm nằm trong HTML tĩnh.

## 4. Cấu trúc dữ liệu
JSON-LD trang danh sách chỉ có `Website`; sản phẩm đọc bằng selector. Trang chi tiết có JSON-LD `Product`.

**Trang danh sách** (`<danh mục>?page=N`):
- Mỗi sản phẩm là `div.p-item[data-id]` (30 hoặc 24 thẻ). Bên trong:
  - liên kết: `a.p-name[href]` (đường dẫn tương đối `/<slug>.html` hoặc `/<slug>_id<N>.html`); tên: `a.p-name h3`;
  - ảnh: `a.p-img img[data-src]` (tải lười; `src` không có; máy chủ `anphat.com.vn`);
  - mã: `span.p-sku` = "Mã SP: MULG0093" (mã nội bộ của An Phát, không phải mã hãng);
  - đánh giá: `i.icon-star.star-N` (N = số sao, `star-0` khi chưa có) và số lượt "(24)" ngay sau;
  - giá: `div.price-container` gồm `del.p-old-price`, `span.p-discount` ("-14%") và `span.p-price` (xem mục 5);
  - tồn kho: `span.btn-in-stock` ("Còn hàng") hoặc `span.btn-out-stock` ("Đặt hàng", biểu tượng điện thoại);
  - `div.p-special-container` ("N khuyến mại"), `div.p-tooltip` (khuyến mãi và tóm tắt), `div.box-config`.
- **Thông số trên thẻ: không có.** `div.thongso` (và các chip có nhãn `data-info`) được nạp bằng JavaScript sau; HTML tĩnh chỉ có `div.thongso` rỗng. Vì vậy `ListingItem.raw_specs` rỗng và pipeline tải trang chi tiết (tối đa 20 trang/lượt).
- Trang vượt cuối: HTML bình thường, 0 thẻ `p-item`. Không thấy trang lỗi/404.

**Trang chi tiết** (`/<slug>.html`, ~0,7–0,9 MB):
- JSON-LD `Product`: `name`, `sku` (= "Mã SP"), `mpn` (số nội bộ, ví dụ `33297`, không phải mã hãng), `brand.name`, `image`, `aggregateRating` (`ratingValue`, `reviewCount` là chuỗi), `offers` (`price` là **chuỗi** số, `availability`, `priceCurrency`; `priceValidUntil` là ngày cũ vô nghĩa), `review[]` (có `author.name` là người đánh giá → **không lưu**).
- Thông số có nhãn, theo thứ tự ưu tiên:
  1. `div.pro-info-summary span.item`: gạch đầu dòng "Nhãn: giá trị" (laptop: `CPU: …`, `VGA: …`, `Màn hình: …`, `RAM: …`, `Ổ cứng: …`, `Pin: …`, `OS: …`; bàn phím có `- Kết nối: …`); dòng không có dấu `:` là mô tả tự do. Một số dòng có lớp `hide` (chỉ ẩn bằng CSS) vẫn nằm trong HTML.
  2. `div#pro-spec table` (ẩn bằng CSS, vẫn trong HTML): hàng 2 ô = nhãn | giá trị; hàng 1 ô là tiêu đề mục (laptop: "Bộ vi xử lý", "Ổ cứng"…, nhãn lặp như "Dung lượng" xuất hiện ở nhiều mục). **Bàn phím và tai nghe mẫu có `#pro-spec` rỗng.**
- Tiêu đề `h1`: laptop có cả CPU/GPU/màn hình/RAM/SSD/hệ điều hành (ví dụ "Laptop HP VICTUS 15-fa2452TX D44VLPA (Intel Core i5-13420H | RTX 3050 6GB | 15.6 inch FHD 144Hz | 16GB | 512GB | Win 11 | Đen)").
- Giá: `div.pro_info-price-container` ("Giá niêm yết: … Giá khuyến mại: …"); chỉ dùng cho giá khi cần, ưu tiên JSON-LD. Trang còn chứa nhiều khối giá khác (biến thể `variant-price` có cả "Liên hệ", combo, sản phẩm liên quan có `price-container` riêng) nên **không** quét toàn trang tìm giá.

## 5. Loại giá hiển thị
Trên thẻ danh sách, 5 trang mẫu có thẻ (126 thẻ):

| Kiểu hiển thị | Số thẻ | `price` | `list_price` | `price_type` |
| --- | --- | --- | --- | --- |
| Một giá `span.p-price` | 21 | giá đó | `None` | `regular` |
| `del.p-old-price` + `span.p-discount` ("-14%") + `span.p-price` | 105 | giá bán (`p-price`) | giá gốc (`p-old-price`) | `sale` |

- Định dạng giá: `389.000 đ` (có dấu cách trước `đ`); giá lớn nhất thấy là `xxx.xxx.xxx đ` (laptop > 100 triệu). Mọi thẻ mẫu đều có `span.p-price`.
- **Các giá ẩn bằng `d-none` trong `price-container` phải bỏ qua**: `div.p-price-showroom` ("Giá Build PC: 0 đ") và `div.p-price-combo` ("Giá ưu đãi (chỉ áp dụng khu vực TP.HCM): 329.000 đ"). Chúng có dùng lớp khác `p-price` nên đọc theo `.p-price`/`.p-old-price` là đủ an toàn.
- Quy tắc đọc (không đoán): có `p-price` và `p-old-price` lớn hơn `p-price` → `sale`; chỉ `p-price` → `regular`; thiếu `p-price`, hoặc `p-old-price` không lớn hơn → `price = None`/không coi là giảm, kèm log `WARNING`. Giá thành viên, flash sale, giá bị che: chưa thấy.
- Tồn kho: `btn-in-stock` → `in_stock`; `btn-out-stock` ("Đặt hàng": gọi điện để đặt, giá vẫn hiển thị) → `out_of_stock` (theo chính lớp của trang). Cả 12 thẻ trang cuối nhóm chuột là `btn-out-stock`.

## 6. Fixtures đã lưu
Lưu ngày 2026-10-19 bằng bot dự án qua Fetcher (`scripts.fetch_page --allow-online`: robots.txt, độ trễ ≥ 5 s, User-Agent trung thực) trong `backend/tests/fixtures/anphat/`. Đã bỏ `<script>` (trừ JSON-LD), `<style>`, `<svg>`, `<iframe>`, ảnh `data:`, chú thích HTML, **toàn bộ `<header>` (menu ~300 KB) và `<footer>`** (chứa email/số điện thoại nhân viên), đổi tên người đánh giá trong JSON-LD thành "[đã ẩn]" và che số điện thoại/tên liên hệ trong khuyến mãi ("Mr.Kiên 0388…" → "[liên hệ đã ẩn]"). Mỗi file < 500 KB (19–362 KB); còn lại mã số thuế doanh nghiệp trong nội dung; không có email hay số cá nhân (test `test_anphat_fixtures.py` kiểm).

| File | Nội dung |
| --- | --- |
| `robots.txt` | Bản gốc, 763 ký tự (hai nhóm `*`) |
| `listing_laptop_p1.html` | 24 thẻ, 980 kết quả |
| `listing_mouse_p1.html`, `listing_keyboard_p1.html`, `listing_headset_p1.html` | 30 thẻ mỗi trang |
| `listing_mouse_p12.html` | Trang cuối: 12 thẻ, đều `btn-out-stock` |
| `listing_mouse_p13.html` | Vượt trang cuối: 0 thẻ |
| `detail_laptop-hp-victus-15-fa2452tx-d44vlpa.html` | Laptop gaming: bảng `#pro-spec` 43 hàng có mục |
| `detail_chuot-logitech-g102-lightsync.html` | Chuột: `#pro-spec` 9 hàng; có giá ưu đãi combo ẩn |
| `detail_ban-phim-co-aula-f75-grey-white-milk-white-switch.html`, `detail_tai-nghe-logitech-g-pro-x3-lightspeed-magenta.html` | Bàn phím và tai nghe: `#pro-spec` rỗng, thông số ở `pro-info-summary` |

Không lưu trang tìm kiếm (robots.txt chặn `/tim`) và sitemap (không dùng).

## 7. Vấn đề và lưu ý
- **Bộ phát hiện challenge báo nhầm trên mọi trang sản phẩm (đã xử lý bằng ghi đè theo 06 §4).** Mọi trang An Phát (danh sách rỗng, chi tiết, kể cả lần tải bằng trình duyệt) chứa sẵn form đăng ký có ô captcha: `input[name=register_captcha]`, `onkeyup="check_user_captcha(…)"`, `img#captchaimg` trỏ `/includes/captcha/captcha.php`. `detect_challenge` mặc định khớp chữ `captcha` nên `fetch_page` từ chối lưu cả 4 trang chi tiết (đúng quy tắc, chưa lưu file). Nội dung trang bình thường, không có tường captcha. `AnPhatScraper.detect_challenge` loại đúng các tên của form đó (`register_captcha`, `check_user_captcha`, `captchaimg`, `/includes/captcha/captcha.php`) rồi gọi bộ phát hiện chung, nên bất kỳ captcha nào khác (`id="captcha"`, `g-recaptcha`, `hcaptcha`, form `/captcha`…) vẫn dừng lượt; có test hai chiều. `scripts.fetch_page` giờ dùng `detect_challenge` của scraper của trang (không dùng hàm chung) để tôn trọng ghi đè này.
- **Không có tìm kiếm trực tiếp (tầng 2):** `Disallow: /tim`. `supports_live_search=False`.
- **Thông số:** thẻ danh sách không có, nên mỗi lượt tải tối đa 20 trang chi tiết (pipeline); phần lớn sản phẩm của lượt đầy đủ sẽ chưa có `raw_specs` có nhãn. Tên sản phẩm của laptop đã chứa CPU/GPU/RAM/SSD/màn hình cho bộ trích xuất ở M5. Bàn phím/tai nghe chỉ có gạch đầu dòng tự do ở `pro-info-summary`.
- `sku` ("Mã SP", ví dụ `MULG0093`) là mã nội bộ; `mpn` là số nội bộ: không dùng làm `model_code_hint`. `site_sku` lấy từ `p-sku`.
- Hãng: thẻ danh sách không có; `detect_brand` suy từ tên, chi tiết có `brand.name` (JSON-LD).
- Ảnh sản phẩm ở máy chủ `anphat.com.vn` (khác `www.anphatpc.com.vn`): chỉ là URL ảnh, không tải.
- Hai tên miền, một trang: scraper luôn dùng `www.anphatpc.com.vn`; chuyển hướng ra ngoài miền sẽ bị Fetcher từ chối (`RedirectError`).
