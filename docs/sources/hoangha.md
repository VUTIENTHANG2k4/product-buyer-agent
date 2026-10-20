# Nguồn: Hoàng Hà Mobile (`hoangha`)

> **KHÔNG DÙNG từ 2026-10-19** ([ADR-0008](../adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)): người dùng chọn thay bằng FPT Shop và An Phát thay vì chờ xác nhận của giảng viên. Giữ nội dung khảo sát dưới đây để tham khảo; không viết scraper.

> Khảo sát ngày: 2026-10-17 (mục 1–2) · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T0.4 (mục 1–2), T4.1 (mục 3–7)

## 1. robots.txt
- Ngày đọc: 2026-10-17 (`https://hoanghamobile.com/robots.txt`). Giống bảng [02 §2](../02-scope-and-sources.md#2-kết-quả-robotstxt-đọc-ngày-2026-10-16), không có thay đổi.
- Quy tắc áp dụng cho `*`: `Allow: /`; `Disallow: /*filters=`, `/tim-kiem`, `/tin-tuc/search`, `/so-sanh/`, `/Ajax/`, `/account/`, `/gio-hang/`. Có `Sitemap: https://hoanghamobile.com/sitemap.xml`.
- Crawl-delay: không khai báo.
- Độ trễ cấu hình (`min_delay`): 5 s (mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link:
  - Quy chế hoạt động (điều khoản mua bán hàng hóa): https://hoanghamobile.com/dieu-khoan-mua-ban-hang-hoa
  - Chính sách bảo mật và xử lý dữ liệu cá nhân: https://hoanghamobile.com/chinh-sach-bao-mat
- Có điều khoản về thu thập tự động không? **Không nêu trực tiếp** bot, crawler hay scraping, nhưng có 2 đoạn có thể bị hiểu là liên quan (trích ngắn, chưa đối chiếu toàn văn):
  - Mục 1 "Hướng dẫn sử dụng Nền Tảng": "Nghiêm cấm sử dụng bất kỳ phần nào của Nền Tảng với mục đích thương mại". (Tóm tắt của công cụ đọc trang: cần có sự cho phép bằng văn bản; chưa đối chiếu.) Vi phạm thì: "chúng tôi có quyền ngay lập tức thu hồi quyền sử dụng và/hoặc khóa quyền truy cập website của khách hàng".
  - Mục 9 "Quy định về bảo mật": "Khách hàng không được sử dụng bất kỳ chương trình, công cụ hay hình thức nào khác để can thiệp vào hệ thống". (Tóm tắt: đoạn này cấm *can thiệp* hệ thống; không rõ có áp dụng cho việc đọc trang công khai bằng bot hay không.)
  - Mục 2 "Ý kiến khách hàng", hai đoạn trích riêng của cùng một câu: "Tất cả nội dung hiển thị và đăng tải trên Nền Tảng" và "đều là tài sản của Hoanghamobile.com".
- Kết luận (đề xuất, chờ người dùng duyệt): **Cần hỏi giảng viên.**
  - Lý do: câu cấm "mục đích thương mại" mơ hồ. Đồ án này phi thương mại, đọc trang công khai với độ trễ ≥ 5 s, không đăng nhập, nhưng điều khoản không phân biệt rõ.
  - Nếu giảng viên đồng ý: dùng, với điều kiện không công bố lại dữ liệu thu thập, chỉ hiển thị trong demo và có link về trang gốc.
  - Nếu giảng viên không đồng ý: loại khỏi nguồn, cập nhật 02 và ADR, cân nhắc X2.
- Ghi chú về cách đọc: công cụ đọc trang chỉ trả về tóm tắt và trích ngắn (≤ 125 ký tự mỗi đoạn). Người dùng nên mở link quy chế và đối chiếu mục 1, 2, 9 trước khi quyết định.

## 3. Danh mục theo nhóm
| Nhóm | URL danh mục | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| (T4.1) | | | |

## 4. Cấu trúc dữ liệu
(T4.1)

## 5. Loại giá hiển thị
(T4.1)

## 6. Fixtures đã lưu
(T4.1)

## 7. Vấn đề và lưu ý
(T4.1)
