# Nguồn: FPT Shop (`fptshop`)

> Khảo sát ngày: 2026-10-19 · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T4.1
> Người dùng đã duyệt kết luận điều khoản ngày 2026-10-19 (sau khi tự mở link đối chiếu). Lý do chọn trang: [ADR-0008](../adr/0008-fptshop-anphat-replace-hoangha-laptop88.md).

## 1. robots.txt
- Ngày đọc: 2026-10-19 (`https://fptshop.com.vn/robots.txt`). Lần đầu bằng WebFetch (tóm tắt, thiếu và sai chi tiết), sau đó **bản gốc lưu bằng Fetcher** tại `backend/tests/fixtures/fptshop/robots.txt` (1549 ký tự); các mục dưới đây theo bản gốc.
- Quy tắc áp dụng cho `*` (chỉ một nhóm `User-agent: *`, không có nhóm riêng cho bot AI, không có `Allow`, không `Crawl-delay`):
  - Thư mục: `/admin/`, `/cms/`, `/web/`, `/ajax/`, `/gio-hang/`, `/so-sanh-san-pham/`, `/dien-dan/`, `/tai-khoan/`, `/don-hang/`, `/dat-hang/`. (Không thấy `/tim-kiem`: tìm kiếm không bị chặn.)
  - Mẫu có tham số: `/*sort=`, `/*orderby=`, `/*categories=`, `/*muc-gia=`, `/*hang-san-xuat=`, `/*loai-san-pham=`, `/*ram=`, `/*mau-sac=`, `/*o-cung=`, `/*nhu-cau=`, `/*thong-so=`, `/*fbclid=`, `/*utm_*=`… (hơn 40 tham số lọc/theo dõi).
  - **`Disallow: /*t=`** rất rộng: khớp mọi URL chứa chuỗi `t=` (kể cả `sort=`, `limit=`). Đã kiểm bằng `parse_robots` với bản gốc: `?page=2`, `?trang=2`, `?p=2` **không** bị chặn; `?sort=…` bị chặn. Scraper không dùng tham số truy vấn nào (xem mục 3), nên `/*t=` không ảnh hưởng.
  - `Sitemap: https://fptshop.com.vn/sitemap.xml`.
- Crawl-delay: không khai báo.
- Độ trễ cấu hình (`min_delay`): 5 s (mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link:
  - Quy chế hoạt động: https://fptshop.com.vn/tos
  - Chính sách thu thập và xử lý dữ liệu cá nhân: https://fptshop.com.vn/ho-tro/chinh-sach-thu-thap-va-xu-ly-du-lieu-ca-nhan
  - Footer không có trang "Điều khoản sử dụng" hay "Điều khoản mua bán" riêng.
- Có điều khoản về thu thập tự động không? **Không tìm thấy** điều khoản về bot, crawler, scraping hay khai thác dữ liệu trong Quy chế hoạt động (các mục I–XII). Có hai nhóm điều khoản về sao chép nội dung, theo bản tóm tắt của công cụ (người dùng đã đối chiếu khi duyệt):
  - Mục IX.1 (Quyền của FPT Shop): "Tất cả các biểu tượng, nội dung theo các ngôn ngữ khác nhau đều thuộc quyền sở hữu của FPT Shop." và "Nghiêm cấm mọi hành vi sao chép, sử dụng và phổ biến bất hợp pháp các quyền sở hữu trên."
  - Mục VII và X.2 (nghĩa vụ của **thành viên**): "Thành viên không được thay đổi, chỉnh sửa, gán ghép, copy, truyền bá, phân phối, cung cấp…" (câu bị cắt; áp dụng cho thành viên đã đăng ký, mà bot của dự án không đăng nhập).
  - Không thấy điều khoản coi giá là tài sản trí tuệ.
- Kết luận (**đã duyệt** bởi người dùng, 2026-10-19): **Được dùng**, theo 02 §3 (robots.txt, độ trễ ≥ 5 s, không chạm `/ajax/`, giỏ hàng, tài khoản, đặt hàng; không dùng tham số bị chặn). Lưu ý: mục IX.1 nghiêm cấm sao chép và phổ biến "bất hợp pháp" nội dung; dự án chỉ thu thập tên, giá, link, thông số công khai cho mục đích học tập phi thương mại và không đăng lại dữ liệu thật (bản trình diễn công khai chỉ dùng dữ liệu seed, ADR-0008).

## 3. Danh mục theo nhóm
Danh sách sản phẩm **không duyệt bằng phân trang** (xem mục 7): trang danh mục chỉ có ~25 sản phẩm trong HTML tĩnh, phần còn lại nạp bằng nút "Xem thêm" qua API và `?page=N` bị bỏ qua. Thay vào đó scraper lấy URL sản phẩm từ **sitemap** (có trong robots.txt, không bị chặn), rồi tải trang chi tiết.

| Nhóm | Nguồn URL sản phẩm | Cách nhận diện nhóm | Số URL (2026-10-19) |
| --- | --- | --- | --- |
| laptop | `https://fptshop.com.vn/products/sitemap-may-tinh-xach-tay.xml` | Cả sitemap là laptop; URL `/may-tinh-xach-tay/<slug>` | 370 |
| mouse | `sitemap-phu-kien.xml`, `sitemap-phu-kien-1.xml`, `sitemap-phu-kien-2.xml` (cùng thư mục `/products/`) | Slug sau `/phu-kien/` bắt đầu bằng `chuot-` | 141 |
| keyboard | như trên | Slug bắt đầu bằng `ban-phim-` | 85 |
| headset | như trên | Slug bắt đầu bằng `tai-nghe-` | 286 |

- `sitemap.xml` là chỉ mục: `sitemap-may-tinh-xach-tay.xml` (370 URL), `sitemap-phu-kien.xml` (1000), `sitemap-phu-kien-1.xml` (1000), `sitemap-phu-kien-2.xml` (645), `sitemap-phu-kien-gia-dung.xml` (không dùng), `sitemap-category.xml` (chưa xem). Mỗi `<url>` có `loc`, `changefreq`, `priority`, `image:image/image:loc`; không có `lastmod`.
- Phụ kiện đều ở `/phu-kien/<slug>` nên nhóm chỉ suy ra từ tiền tố slug (heuristic). Số trên là đếm theo **tiền tố** (141/85/286); đếm theo "có chứa" là 169/120/294 vì có cả tên như `apple-ban-phim-ipad-…`. Chấp nhận bỏ sót thay vì đoán thêm.
- Trang danh mục (`/may-tinh-xach-tay`, `/phu-kien/chuot`, `/phu-kien/ban-phim`, `/phu-kien/tai-nghe`) tồn tại và tải được nhưng không dùng.
- `requires_js`: **False** cho trang chi tiết (JSON-LD `Product` và giá nằm trong HTML dựng sẵn). Code chưa hỗ trợ JavaScript nên đây là điều kiện bắt buộc.

## 4. Cấu trúc dữ liệu
Trang chi tiết `/<danh-mục>/<slug>` (Next.js app router, HTML ~1,0–1,3 MB trước khi rút gọn):
- **JSON-LD `Product`** (một khối, cùng `WebSite`, `Organization`, `BreadcrumbList`): `name` (không có tiền tố loại, ví dụ "Acer Aspire Lite 14 AL14-44P-R0SP R7-7730U"), `sku` và `mpn` **trùng nhau** (mã nội bộ FPT Shop, ví dụ `00930661`; **không phải mã hãng**, không dùng làm `model_code_hint`), `brand.name`, `aggregateRating` (`ratingValue`, `reviewCount`), `offers` (`price` số nguyên VND, `priceCurrency`, `priceValidUntil` = ngày khảo sát, `availability` kiểu `https://schema.org/InStock`, `url`), `review` (một đối tượng, có `author` là tên người đánh giá → **không lưu**, fixture ẩn thành "[đã ẩn]"), `image`, `description` và `additionalProperty[{name, value}]`.
  - `additionalProperty` là phần **rút gọn** (laptop 6 mục: CPU, RAM, Card đồ hoạ, Kích thước màn hình, Thời lượng Pin, Tấm nền; chuột 3: Trọng lượng, Chuẩn kết nối, Độ phân giải; bàn phím/tai nghe 4–7 mục) và nhiều giá trị **rỗng** (`"value": ""`) cần bỏ. Bảng "Thông số kỹ thuật" đầy đủ chỉ nằm trong dữ liệu `self.__next_f` của script Next.js; không parse (khó và dễ vỡ), nên thông số đầy đủ lấy từ **tên sản phẩm** (thẻ `h1`; laptop có cả CPU/RAM/SSD/màn hình/GPU, ví dụ `Laptop Asus TUF Gaming 16 FX610JH-TU008W i5-14450HX/16GB/512GB/16"/Nvidia Geforce RTX5050 8GB/Win 11`) bằng bộ trích xuất ở M5.
- **Giá hiển thị trong HTML:** khối giá đầu trang gồm giá bán và giá gốc gạch ngang (`p.line-through`/`span.line-through`) kèm `-N%`; trùng với `offers.price` của JSON-LD (ví dụ 38.990.000đ, gốc 43.990.000đ, -11%). Lớp CSS là Tailwind dài, dễ đổi; ưu tiên JSON-LD cho giá bán và dùng phần tử gạch ngang chỉ cho giá gốc.
- **Trang danh mục** `/may-tinh-xach-tay`: 24–25 thẻ sản phẩm trong HTML tĩnh, "N kết quả", nút "Xem thêm N kết quả"; JSON-LD chỉ `WebSite`/`Organization`/`BreadcrumbList`; không `rel=next`; `?page=2` trả cùng 25 sản phẩm. Không dùng.
- Tìm kiếm tầng 2 (T10.1, khảo sát 2026-10-23, 3 trang qua Fetcher): `https://fptshop.com.vn/tim-kiem?s=<từ khóa>` (`SearchAction` của JSON-LD trang chủ; robots.txt không chặn). **HTML dựng sẵn ở máy chủ, `requires_js=False`**: tiêu đề "Tìm thấy N kết quả với từ khoá …"; mỗi sản phẩm là thẻ `a[href="/<danh-mục>/<slug>"]` chứa `h3` (tên) và các `p` giá: giá bán đúng dạng `12.990.000đ` đứng cuối, giá gốc gạch ngang là phần tử `.line-through` (có thể kèm `-18%` cùng ô), cùng các `p` "Giảm 300.000đ" và đồng hồ "Còn 00 ngày 00:00:00" (không phải giá). Trang đầu có 24 thẻ ("loa bluetooth", 245 kết quả) hoặc 13 thẻ ("ssd 1tb", 121 kết quả); "Xem thêm" nạp qua API nên chỉ lấy trang đầu. Không có JSON-LD sản phẩm. Từ khóa không có kết quả: 0 thẻ. → `supports_live_search=True` ([ADR-0010](../adr/0010-tier2-sites-gearvn-fptshop.md)).

## 5. Loại giá hiển thị
- **Giá bán công khai** (`offers.price`, khớp khối giá đầu trang): `regular` nếu không có giá gốc gạch ngang; `sale` nếu có giá gốc lớn hơn giá bán (kèm `-N%`).
- **Giá flash sale / khuyến mãi theo suất:** trang chi tiết có khối riêng "Đã bán 0/20 suất" + đồng hồ đếm ngược + giá thấp hơn (ví dụ chuột 219.000đ -31% trong khi giá công khai 299.000đ; laptop Acer 19.490.000đ trong khi giá công khai 19.990.000đ). Giá này giới hạn số suất và thời gian nên **không lưu** (dùng giá công khai của JSON-LD); `PriceType.flash` chưa dùng. Chưa tìm thấy giá thành viên (`member`) trong 5 trang đã xem; "Giảm thêm đến 10%" (2.199.000đ) là ưu đãi thanh toán/thẻ, không phải giá.
- Trả góp (`Hoặc 989.000đ /tháng`, "Chỉ từ 1.967.000đ") là số tiền mỗi tháng, **không phải giá**: không đọc. Điểm FPT (`+9.747`) không phải tiền.
- Không thấy giá bị che bằng dấu `***`; không thấy "Liên hệ". Hết hàng: `availability` của JSON-LD (`OutOfStock`…); chưa gặp trang hết hàng trong 5 mẫu.

## 6. Fixtures đã lưu
Lưu ngày 2026-10-19 bằng bot dự án qua Fetcher (`scripts.fetch_page --allow-online`: robots.txt, độ trễ ≥ 5 s, User-Agent trung thực) trong `backend/tests/fixtures/fptshop/`. Trang chi tiết đã bỏ `<script>` (trừ JSON-LD), `<style>`, `<svg>`, `<iframe>`, ảnh `data:` và đổi tên người đánh giá trong JSON-LD thành "[đã ẩn]" (còn 150–260 KB mỗi file); DOM còn nguyên. Còn lại thông tin liên hệ của doanh nghiệp (email `fptshop@fpt.com`, mã số thuế, tổng đài); không có dữ liệu cá nhân (test `test_fptshop_fixtures.py` kiểm).

| File | Nội dung |
| --- | --- |
| `robots.txt` | Bản gốc, 1549 ký tự |
| `sitemap_index.xml` | `sitemap.xml` đầy đủ (chỉ mục) |
| `sitemap_laptop.xml` | 80 URL đầu của `sitemap-may-tinh-xach-tay.xml` (370 URL) |
| `sitemap_phu-kien.xml`, `sitemap_phu-kien-2.xml` | 120 và 60 URL đầu của hai trong ba sitemap phụ kiện |
| `detail_laptop-acer-aspire-lite-14-al14-44p-r0sp-r7-7730u.html` | Laptop giảm 9% (19.990.000đ, gốc 21.990.000đ) + khối flash sale |
| `detail_laptop-asus-tuf-gaming-16-fx610jh-tu008w-i5-14450hx.html` | Laptop gaming giảm 11% (38.990.000đ, gốc 43.990.000đ) |
| `detail_chuot-khong-day-elecom-m-ir07dr.html` | Chuột giảm 6% + khối flash sale theo suất |
| `detail_ban-phim-co-khong-day-mchose-g75-pro-v2.html`, `detail_tai-nghe-corsair-hs50-pro-stereo.html` | Bàn phím và tai nghe |

Ba fixture tìm kiếm (T10.1, lưu 2026-10-23, rút gọn còn lưới thẻ + `<title>`; bỏ script, style, svg):

| File | Nội dung |
| --- | --- |
| `search_loa_bluetooth.html` | `/tim-kiem?s=loa+bluetooth`: 24 thẻ, có thẻ giảm giá (giá gốc kèm `-18%`) |
| `search_ssd_1tb.html` | `/tim-kiem?s=ssd+1tb`: 13 thẻ nhóm `linh-kien` |
| `search_khong_ket_qua.html` | `/tim-kiem?s=zzqxnotfound`: 0 thẻ |

Không lưu trang danh mục (HTML ~2 MB, không dùng). Chưa có fixture trang hết hàng hay trang không có giá gốc; T4.2 dựng từ các fixture trên khi cần.

## 7. Vấn đề và lưu ý
- **Bộ phát hiện challenge báo nhầm (đã sửa, T4.0b).** Lần tải đầu `https://fptshop.com.vn/may-tinh-xach-tay` bằng `fetch_page` trả HTTP 200 nhưng `detect_challenge` báo `captcha` và `fetch_page` dừng, không lưu file (đúng 02 §3 mục 7). Quan sát bằng Playwright MCP (2026-10-19, người dùng đồng ý; robots.txt không chặn agent AI; mở 1 trang + vài `fetch` cùng nguồn) cho thấy cả 4 chỗ có chữ `captcha` đều nằm trong script nội tuyến của Next.js (`window['__ENV'] = {…"NEXT_PUBLIC_CAPTCHA_KEY":"…"}`), không có phần tử/iframe captcha, không có chữ này trong nội dung hiển thị. `detect_challenge` nay bỏ thân `<script>` nội tuyến khỏi vùng khớp từ khóa (06 §4); sau đó các trang chi tiết tải bình thường.
- **Phân trang danh mục không dùng được bằng HTTP tĩnh**: trang hiển thị "362 kết quả" nhưng chỉ ~25 trong HTML; phần còn lại nạp bằng "Xem thêm" (JavaScript gọi API ở `papi.fptshop.com.vn`, máy chủ khác, chưa khảo sát robots.txt của nó và không dùng, theo 06 §6); `?page=2` trả cùng trang 1. Người dùng chọn **duyệt qua sitemap** (2026-10-19). Hệ quả: một lượt đầy đủ phải tải từng trang chi tiết (370 laptop × ≥ 5 s ≈ 31 phút; nhóm phụ kiện phải tải thêm 3 sitemap trước); cần một cách "danh sách từ sitemap" trong scraper (T4.2 ghi đè `crawl_category`: mỗi "trang" là một lô khoảng 20 URL, mỗi sản phẩm lấy từ trang chi tiết nên `ListingItem` đã có `raw_specs` và pipeline không tải chi tiết lần nữa).
- `mpn` = `sku` = mã nội bộ: `model_code_hint` luôn `None`; `site_sku` lấy `sku`.
- `aggregateRating` đều là 4.9 trên cả 5 trang mẫu (có thể là giá trị mặc định của FPT Shop): ghi nhận `rating` nhưng không dùng để xếp hạng.
- Quy chế mục IX.1 cấm sao chép/phổ biến "bất hợp pháp" nội dung: chỉ dùng tên, giá, link, thông số công khai, cho học tập phi thương mại; dữ liệu thật không đăng công khai (ADR-0008).
- `Disallow: /*t=` (robots.txt) khớp mọi URL chứa chuỗi `t=`: scraper không tạo URL có tham số truy vấn nên không bị ảnh hưởng.
- **Cài đặt (T4.2, `app/scrapers/sites/fptshop.py`):** `crawl_category` đọc chỉ mục `sitemap.xml` rồi các sitemap của nhóm (laptop: `sitemap-may-tinh-xach-tay.xml`; phụ kiện: mọi `sitemap-phu-kien*.xml`, trừ `-gia-dung`), lọc URL cùng máy chủ `https` có đúng 2 đoạn đường dẫn (`/may-tinh-xach-tay/<slug>` hoặc `/phu-kien/<tiền tố>-…`), rồi tải trang sản phẩm theo lô `BATCH_SIZE` = 20 (mỗi lô là một "trang" của pipeline; `PAGES=1` tải 20 sản phẩm ≈ 2 phút). Mỗi lượt tốn thêm 1–4 request sitemap. Trang 404/410 (đã gỡ nhưng còn trong sitemap) tính vào `skipped`; lỗi HTTP khác, challenge hay `RobotsBlocked` dừng lượt như các trang khác. Giá = `offers.price` (JSON-LD); giá gốc = phần tử `.line-through` lớn hơn giá bán và nằm cạnh phần tử có đúng giá bán (trong 3 cấp cha), nên giá gạch của khối flash sale không bị đọc nhầm. `title` = `h1` (đầy đủ hơn `name`). `raw_specs` = `additionalProperty` bỏ giá trị rỗng. `parse_listing` ném `NotImplementedError`; `parse_detail` trả thông số và hãng. Pipeline không tải thêm trang chi tiết cho mục đã có thông số; mục có `raw_specs` rỗng (hiếm) vẫn bị tải lại một lần.
- **Chạy thật (T4.5, 2026-10-19, `PAGES=1` mỗi nhóm, người dùng tự bật `SCRAPER_OFFLINE_ONLY=false`):** 4 lượt (laptop, mouse, keyboard, headset), đều `PARTIAL` chỉ vì dừng ở giới hạn trang, 20 mục/lượt, 0 lỗi, không `BLOCKED`/captcha. Tổng 80 offer: 80/80 có giá > 0 (51 `sale`, 29 `regular`), 80/80 có `site_sku` và đánh giá, 78/80 có `raw_specs` (tỷ lệ parse 100%; 2 mục thiếu thông số là phụ kiện: `ban-phim-gaming-co-day-mchose-jet-75`, `tai-nghe-co-day-choang-dau-gaming-hyperx-cloud-stinger-3`). Cả 80 là `in_stock`.
- Chưa xử lý: tình trạng hết hàng (chưa có mẫu `OutOfStock`), giá thành viên (`member`), nhận diện nhóm phụ kiện thiếu tiền tố (ví dụ `apple-ban-phim-ipad-…`). Tìm kiếm tầng 2 đã có từ T10.1 (`FptShopScraper.search_url`/`parse_search`): thẻ không có ô giá đọc được → `price=None`; giá gốc chỉ nhận khi lớn hơn giá bán.
