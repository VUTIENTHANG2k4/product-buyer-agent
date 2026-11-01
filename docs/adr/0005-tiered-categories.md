# ADR-0005: Phân tầng nhóm sản phẩm

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Người dùng muốn tìm đa dạng sản phẩm. Hỗ trợ đầy đủ (chuẩn hóa thông số, lọc, ghép giữa trang) cho mọi loại là quá lớn với một người; không nguồn nào bán đủ mọi nhóm.

## Quyết định
- Tầng 1: laptop, chuột, bàn phím, tai nghe — mỗi nhóm có ≥ 2 nguồn lõi (GearVN, Laptop88; laptop có thêm Hoàng Hà).
- Tầng 2: mọi nhóm khác — tìm trực tiếp trên trang cho phép, trả tên/giá/link, nhãn "chưa chuẩn hóa thông số".
- Điện thoại là pha mở rộng.
- Planner quyết định tầng; tầng 2 không lưu vào bảng Product.

## Hệ quả
- Đáp ứng "tìm mọi loại" với chất lượng giảm có kiểm soát, minh bạch với người dùng.
- Thêm một nhóm vào tầng 1 = khung specs + bộ trích xuất + golden test (skill `add-category`).

## Phương án đã cân nhắc
- Chỉ laptop gaming: an toàn nhưng thiếu đa dạng.
- Tìm tự do mọi nhóm với LLM trích thông số: chất lượng không đều, khó kiểm chứng.
