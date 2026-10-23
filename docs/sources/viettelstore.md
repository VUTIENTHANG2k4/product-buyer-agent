# Nguồn: Viettel Store (`viettelstore`)

> Khảo sát ngày: 2026-10-17 (mục 1–2) · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T0.4 (mục 1–2), T10.1 (mục 3–7, khảo sát 2026-10-23)

## 1. robots.txt
- Ngày đọc: 2026-10-17 (`https://viettelstore.vn/robots.txt`). Giống bảng [02 §2](../02-scope-and-sources.md#2-kết-quả-robotstxt-đọc-ngày-2026-10-16), không có thay đổi.
- Quy tắc áp dụng cho `*`: không có `Allow`; chỉ `Disallow` thư mục kỹ thuật `/DataFiles/`, `/bin/`, `/css/`, `/js/`, `/layout/`, `/Log/`, `/Properties/`, `/Web References/`. Có `Sitemap: https://viettelstore.vn/sitemap.xml`.
- Crawl-delay: không khai báo.
- Độ trễ cấu hình (`min_delay`): 5 s (mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link:
  - Quy chế hoạt động website: https://viettelstore.vn/quy-che-hoat-dong-website.html
  - Chính sách bảo vệ dữ liệu cá nhân: https://viettelstore.vn/chinh-sach-bao-ve-du-lieu-ca-nhan-doi-voi-khach-hang-viettel-store.html
- Có điều khoản về thu thập tự động không? **Không nêu về bot, crawler hay scraping.** Các đoạn gần nhất (trích ngắn qua công cụ đọc trang, chưa đối chiếu toàn văn):
  - Mục VII.1 (Quyền của chủ sở hữu), hai đoạn trích riêng: "Viettelstore.vn giữ bản quyền sử dụng dịch vụ và các nội dung trên Viettelstore.vn" và "Nghiêm cấm mọi hành vi sao chép, sử dụng và phổ biến bất hợp pháp các quyền sở hữu trên."
  - Mục V (đoạn dành cho thành viên), ba đoạn trích riêng, cùng một câu: "Thành viên không được thay đổi, chỉnh sửa, gán gép [sic], copy, truyền bá, phân phối, cung cấp"; "và tạo những công cụ tương tự của dịch vụ do Viettelstore.vn cung cấp cho một bên thứ ba"; "nếu không được sự đồng ý của Viettelstore.vn". (Tóm tắt: đoạn này nói về *thành viên* (người dùng có tài khoản) và *dịch vụ*, không nói về dữ liệu giá công khai.)
- Kết luận: điều khoản **Được dùng** cho tìm kiếm tầng 2 theo yêu cầu người dùng, số lượng nhỏ, có độ trễ (**người dùng đã duyệt 2026-10-23**); chỉ hiển thị tên, giá, link, ảnh đại diện (URL). **Nhưng không dùng cho tầng 2 vì trang tìm kiếm cần JavaScript** (mục 7, [ADR-0010](../adr/0010-tier2-sites-gearvn-fptshop.md)).
- Ghi chú về cách đọc: công cụ đọc trang chỉ trả về tóm tắt và trích ngắn. Người dùng nên mở link quy chế và đối chiếu mục V, VII, VIII.

## 3. Danh mục theo nhóm
Chỉ khảo sát **tìm kiếm** (tầng 2); chưa viết scraper danh mục.

| Nhóm | URL | Phân trang | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| Tìm kiếm | `https://viettelstore.vn/ket-qua-tim-kiem.html?keyword=<từ khóa>` (robots.txt không chặn; các liên kết trên trang chủ cũng dùng `&sort=SearchResult`) | Không khảo sát | – |

## 4. Cấu trúc dữ liệu
Khảo sát ngày 2026-10-23 (3 trang qua Fetcher: "loa bluetooth", "ssd 1tb", "zzqxnotfound"; mỗi trang ~150 KB):
- Không có JSON-LD (0 khối), không có giá nào dạng `1.290.000đ` trong HTML.
- Khung kết quả `<div id="div_Danh_Sach_San_Pham" class="product-list-item">` **để trống**; bên dưới là `div_Danh_Sach_San_Pham_loadMore` ("Đang tải....") và các script `jquery.lazyload`, `lodash`. Danh sách nạp bằng `POST /Site/_Sys/ajax.aspx` sau khi trang chạy JavaScript.
- Ba trang có kích thước gần như nhau (152–156 KB) dù một trang là từ khóa không có kết quả.

## 5. Loại giá hiển thị
Không đọc được: giá không có trong HTML tĩnh.

## 6. Fixtures đã lưu
| File | Nội dung |
| --- | --- |
| `robots.txt` | Bản gốc đọc ngày 2026-10-23 (223 ký tự), giống mục 1 |

Không lưu trang tìm kiếm (không có sản phẩm để kiểm thử).

## 7. Vấn đề và lưu ý
- **`requires_js = True` cho tìm kiếm** → không dùng cho tầng 2 ([ADR-0010](../adr/0010-tier2-sites-gearvn-fptshop.md)). Code chưa hỗ trợ JavaScript, và `ajax.aspx` là API nội bộ, không gọi.
- Người dùng đã duyệt kết luận điều khoản ngày 2026-10-23; trang không bị loại vì điều khoản mà vì kỹ thuật. Nếu thêm trình duyệt headless hoặc nguồn dữ liệu công khai sau này, mở lại bằng ADR mới.
- Đã đăng ký thử rồi gỡ khung scraper trong lúc khảo sát; `SiteKey.viettelstore` vẫn có trong enum (pha mở rộng điện thoại X1).
