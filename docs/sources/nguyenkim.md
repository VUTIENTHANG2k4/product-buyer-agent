# Nguồn: Nguyễn Kim (`nguyenkim`)

> Khảo sát ngày: 2026-10-17 (mục 1–2) · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T0.4 (mục 1–2), T10.1 (mục 3–7)

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
- Kết luận (đề xuất, chờ người dùng duyệt): **Được dùng**, chỉ cho tìm kiếm trực tiếp tầng 2 theo yêu cầu người dùng, số lượng nhỏ và có độ trễ. Các điều khoản trên nhắm vào thành viên và thương nhân trên sàn, không nhắm vào người đọc trang công khai. Chỉ hiển thị tên, giá, link và ảnh đại diện (URL).
- Ghi chú về cách đọc: công cụ đọc trang chỉ trả về tóm tắt và trích ngắn. Một số trang quy chế có nội dung cũ (nhắc mốc 2010, 2015). Người dùng nên mở 2 link quy chế đối chiếu mục V, VII, VIII.

## 3. Danh mục theo nhóm
| Nhóm | URL danh mục | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| (T10.1) | | | |

## 4. Cấu trúc dữ liệu
(T10.1)

## 5. Loại giá hiển thị
(T10.1)

## 6. Fixtures đã lưu
(T10.1)

## 7. Vấn đề và lưu ý
(T10.1)
