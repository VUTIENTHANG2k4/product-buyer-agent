# Nguồn: <Tên trang> (`<site_key>`)

> Khảo sát ngày: YYYY-MM-DD · Người khảo sát: Claude Code + người dùng (cách lấy trang: xem mục 6) · Task: T?.?

## 1. robots.txt
- Ngày đọc:
- Quy tắc áp dụng cho `*`:
- Crawl-delay:
- Độ trễ cấu hình (`min_delay`):

## 2. Điều khoản sử dụng
- Link:
- Có điều khoản về thu thập tự động không? Trích nguyên văn đoạn liên quan:
- Kết luận: Được dùng / Không dùng / Cần hỏi giảng viên

## 3. Danh mục theo nhóm
| Nhóm | URL danh mục | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |

## 4. Cấu trúc dữ liệu
- Trang danh sách có JSON nhúng (JSON-LD, `__NEXT_DATA__`, biến JS) không?
- Có cần JavaScript để hiển thị sản phẩm không? (httpx đủ hay cần Playwright)
- Selector/đường dẫn JSON cho: tên, giá, giá gốc, loại giá, link, ảnh, còn hàng, đánh giá, thông số rút gọn
- Trang chi tiết: bảng thông số nằm ở đâu

## 5. Loại giá hiển thị
- Ví dụ: giá niêm yết, giá khuyến mãi, giá thành viên, flash sale bị che số → ánh xạ sang `price_type`

## 6. Fixtures đã lưu
- `backend/tests/fixtures/<site_key>/listing_<category>_p1.html` (mỗi nhóm)
- `backend/tests/fixtures/<site_key>/listing_<category>_p<n>.html` (trang cuối, không còn trang sau)
- `backend/tests/fixtures/<site_key>/detail_<slug>.html` (≥ 2)
- `backend/tests/fixtures/<site_key>/search_<query>.html` (nếu trang dùng cho tầng 2)
- `backend/tests/fixtures/<site_key>/robots.txt` (bản đã đọc, dùng cho test URL không bị chặn)
- Cách lấy: `fetch_page.py` / người dùng tự lưu / Playwright MCP (chỉ trang không chặn agent AI)

## 7. Vấn đề và lưu ý
