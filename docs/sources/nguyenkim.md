# Nguồn: Nguyễn Kim (`nguyenkim`)

> Khảo sát ngày: 2026-10-17 (mục 1–2) · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T0.4 (mục 1–2), T10.1 (mục 3–7, khảo sát 2026-10-23)

## 1. robots.txt
- Ngày đọc: 2026-10-17 (`https://www.nguyenkim.com/robots.txt`). **Khác bảng [02 §2](../02-scope-and-sources.md#2-kết-quả-robotstxt-đọc-ngày-2026-10-16) một điểm:** có thêm `Disallow: /maintenance` (không ảnh hưởng thu thập danh mục). Các dòng `/checkout/`, `/account/` có thêm dạng có dấu `/` cuối.
- Quy tắc áp dụng cho `*`: `Allow: /`; `Disallow: /checkout`, `/account`, `/cart/`, `/orders/`, `/login`, `/register`, `/otp`, `/compare`, `/search-order`, `/maintenance`. Có 2 `Sitemap` (`sitemap-static.xml`, `sitemap.xml`) và dòng `Host: https://www.nguyenkim.com`.
- Crawl-delay: không khai báo.
- Độ trễ cấu hình (`min_delay`): 5 s (mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link:
  - Quy chế hoạt động website thương mại điện tử: https://www.nguyenkim.com/quy-che-hoat-dong-website-cung-cap-dich-vu-thuong-mai-dien-tu-www.nguyenkim.com.html
  - Quy chế sàn giao dịch: https://www.nguyenkim.com/quy-che-san-giao-dich.html
  - Không có trang "Điều khoản sử dụng" riêng trong footer (footer chỉ có các chính sách thanh toán, trả hàng, bảo hành, bảo mật giao dịch). Hai trang trên tìm được qua tìm kiếm web, không có trong footer.
- Có điều khoản về thu thập tự động không? **Không nêu trực tiếp** bot, crawler hay scraping. Các đoạn gần nhất (trích ngắn qua công cụ đọc trang, chưa đối chiếu toàn văn):
  - Mục V.2 "Phá hoại hệ thống": "Thành viên sử dụng công cụ kỹ thuật nhằm tăng điểm hoạt động, vật phẩm hoặc nhằm treo máy, spam chat." (nói về gian lận điểm hoạt động của thành viên).
  - Mục VII.2 (Nghĩa vụ của thương nhân), hai đoạn trích riêng của cùng một câu: "Cam kết không thay đổi, chỉnh sửa, sao chép, truyền bá, phân phối, cung cấp" và "tạo những công cụ tương tự dịch vụ do Sàn cung cấp cho một bên thứ ba". (Tóm tắt: nói về *thương nhân* và *dịch vụ của sàn*.)
  - Mục V.2 "Vi phạm bản quyền": "sao chép hoặc trích dẫn mà không được phép sử dụng bản quyền của người khác" (nói về tin đăng).
  - Chân trang: "Copyright © 1999 - 2026 Công ty Cổ phần Thương mại Nguyễn Kim."
  - Lưu ý: hai đoạn đều được công cụ gán nhãn "Mục V.2" (một trong "Phá hoại hệ thống", một trong "Vi phạm bản quyền"). Số mục có thể bị công cụ gán sai; người dùng đối chiếu khi mở link.
- Kết luận: điều khoản **Được dùng** cho tìm kiếm tầng 2 theo yêu cầu người dùng, số lượng nhỏ, có độ trễ (**người dùng đã duyệt 2026-10-23**); chỉ hiển thị tên, giá, link, ảnh đại diện (URL). **Nhưng không dùng cho tầng 2 vì trang tìm kiếm cần JavaScript** (mục 7, [ADR-0010](../adr/0010-tier2-sites-gearvn-fptshop.md)).
- Ghi chú về cách đọc: công cụ đọc trang chỉ trả về tóm tắt và trích ngắn. Một số trang quy chế có nội dung cũ (nhắc mốc 2010, 2015). Người dùng nên mở 2 link quy chế đối chiếu mục V, VII, VIII.

> **Cập nhật 2026-11-07 (X1.1, [ADR-0011](../adr/0011-phone-sources-fptshop-nguyenkim.md)):** danh mục và chi tiết điện thoại dùng được cho tầng 1 (xem mục 8); kết luận "không dùng cho tầng 2" bên dưới vẫn đúng. Người dùng xác nhận lại điều khoản cho phạm vi danh mục + chi tiết.

## 3. Danh mục theo nhóm
Mục này ghi khảo sát **tìm kiếm** (tầng 2); điện thoại tầng 1 ở mục 8.

| Nhóm | URL | Phân trang | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| Tìm kiếm | `https://www.nguyenkim.com/search?q=<từ khóa>` (là `SearchAction` trong JSON-LD của trang chủ; robots.txt chỉ chặn `/search-order`, không chặn `/search`) | Không khảo sát (`limit: 25` trong dữ liệu trang) | – |

## 4. Cấu trúc dữ liệu
Khảo sát ngày 2026-10-23 (3 trang qua Fetcher: "loa bluetooth", "ssd 1tb", "zzqxnotfound"; mỗi trang ~200 KB):
- Next.js (pages router): `<script id="__NEXT_DATA__">` có `pageProps.productSearchData = {"pages": 0, "total": 0, "page": 1, "limit": 25, "data": []}` **cho cả ba từ khóa**, kể cả "loa bluetooth" là từ khóa chắc chắn có sản phẩm.
- Hai khối JSON-LD chỉ là `Organization`/`WebSite`. Không có giá nào dạng `1.290.000đ` trong HTML.
- Ba trang gần như cùng kích thước (200.332–200.338 ký tự): phần thân không phụ thuộc từ khóa; kết quả nạp ở phía trình duyệt sau khi hydrate.

## 5. Loại giá hiển thị
Không đọc được: giá không có trong HTML tĩnh.

## 6. Fixtures đã lưu
| File | Nội dung |
| --- | --- |
| `robots.txt` | Bản gốc đọc ngày 2026-10-23 (414 ký tự), giống mục 1 |

Không lưu trang tìm kiếm (không có sản phẩm để kiểm thử).

## 7. Vấn đề và lưu ý
- **`requires_js = True` cho tìm kiếm** → không dùng cho tầng 2 ([ADR-0010](../adr/0010-tier2-sites-gearvn-fptshop.md)). Lấy dữ liệu chỉ có thể bằng JavaScript hoặc gọi API nội bộ của trang, đều trái quy tắc dự án.
- Người dùng đã duyệt kết luận điều khoản ngày 2026-10-23; trang không bị loại vì điều khoản mà vì kỹ thuật.
- Đã đăng ký thử rồi gỡ khung scraper trong lúc khảo sát; `SiteKey.nguyenkim` vẫn có trong enum (pha mở rộng điện thoại X1).

## 8. Điện thoại — tầng 1 (X1.1, khảo sát 2026-11-07)
Khảo sát 5 request qua Fetcher (`scripts.fetch_page --allow-online`, ≥ 5 s/request): sitemap chỉ mục, `/dien-thoai.c`, `/dien-thoai.c?page=2`, một trang chi tiết (thử URL ghép thiếu hậu tố mã sản phẩm bị 404, đã bỏ). robots.txt cho phép (`Allow: /`, không chặn `?page=`); không challenge.

| Nhóm | URL | Phân trang | Số sản phẩm |
| --- | --- | --- | --- |
| phone | `https://www.nguyenkim.com/dien-thoai.c` | `?page=N` (trang 1 không tham số); `pageDetail.pages` = 9, `limit` = 25 | 211 máy (`pageDetail.total`) |

- **`requires_js = False`** cho danh mục và chi tiết: Next.js (pages router) dựng sẵn ở máy chủ. Khác với tìm kiếm, `__NEXT_DATA__.props.pageProps.pageDetail.data` có đủ 25 sản phẩm. Trang không có liên kết phân trang trong HTML: số trang suy từ `pages`/`page`.
- **Danh sách** (`pageDetail.data[]`): `name.vi` ("Điện thoại Samsung Galaxy A18 (6GB/128GB) bạc SM-A185GZSLXXV"), `code`, `price` (giá niêm yết), `salePrice`/`mediaPrice` (giá bán), `finalPrice` (khi có mã giảm, chưa dùng), `stockStatus` (`inStock`), `slugs.value.vi` + `slugs.postfix`, `thumbnail`, `outstandingFeatures[].value.vi` (điểm nổi bật, có "Pin 6000mAh"). **URL sản phẩm = `/` + slug + postfix** (ví dụ `/dien-thoai-di-dong-oppo-cph2859-8gb-256gb-reno16-f-5g-8gb-256gb-trang-CPH28598GB256GB`); slug không kèm postfix trả 404. Đã bỏ `relatedProducts` khỏi fixture.
- **Mỗi dung lượng và mỗi màu là một SKU riêng** (ví dụ "Galaxy A08 4G (4GB, 64GB) Green/Dark Blue/Silver", "iPhone 18 Pro Max 256GB Đen/Đỏ Burgundy"): nhiều offer của cùng một sản phẩm; màu không phải khác biệt sản phẩm, dung lượng thì có (X1.2).
- **Chi tiết:** JSON-LD `Product` (`name`, `sku` = `CPH28598GB256GB`, `mpn` = `CPH2859-8/256/TRANG` — **mã hãng**, dùng làm `model_code_hint` ở X1.4, `brand.name`, `offers.price` = giá bán, `availability`); `__NEXT_DATA__.pageDetail.data.properties[]` là thuộc tính có nhãn (thương hiệu, hệ điều hành, …); `specifications` rỗng.
- **Giá:** `price` niêm yết lớn hơn `salePrice` → `sale` (giá gốc = `price`); bằng nhau → `regular`. Đã thấy 15.990.000 niêm yết, 13.599.000 bán, `finalPrice` 13.499.000 (có mã giảm, không lưu).
- Không thấy captcha/challenge. Từ "captcha" xuất hiện 0 lần trong HTML đã tải.

Fixture (`backend/tests/fixtures/nguyenkim/`, bỏ script trừ JSON-LD và `__NEXT_DATA__`; `__NEXT_DATA__` chỉ giữ `pageDetail`, `pageType`; chi tiết bỏ `reviews`, `relatedProducts`, `description`, khuyến mãi…; test `test_nguyenkim_fixtures.py`):

| File | Nội dung |
| --- | --- |
| `listing_dien-thoai_p1.html`, `listing_dien-thoai_p2.html` | Trang 1 và 2 của `/dien-thoai.c` (25 máy mỗi trang) |
| `detail_dien-thoai-oppo-reno16f-8gb-256gb-trang.html` | OPPO Reno16F 8GB/256GB Trắng: bán 13.599.000đ, niêm yết 15.990.000đ |

Còn lại là mã số thuế của doanh nghiệp (`0302286281`, không phải số cá nhân).
