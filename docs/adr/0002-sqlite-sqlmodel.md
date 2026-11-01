# ADR-0002: SQLite + SQLModel + Alembic

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Ứng dụng một người dùng, chạy cục bộ; dữ liệu ước tính dưới 20.000 offer. Cần dễ cài đặt, dễ sao lưu, test nhanh.

## Quyết định
- SQLite (chế độ WAL, bật foreign keys), một file `backend/data/app.db`.
- SQLModel cho model (dùng chung Pydantic), Alembic cho migration.
- Thông số sản phẩm lưu cột JSON, lọc bằng `json_extract`.

## Hệ quả
- Không cần cài máy chủ CSDL; test dùng SQLite bộ nhớ.
- Ghi đồng thời hạn chế: API và worker dùng chung file, chấp nhận được với tải thấp.
- Chuyển sang PostgreSQL sau này chỉ đổi `DATABASE_URL` và một số truy vấn JSON; khi đó ghi ADR mới.

## Phương án đã cân nhắc
- PostgreSQL ngay từ đầu: mạnh hơn nhưng thêm Docker bắt buộc cho người phát triển.
- MongoDB: hợp dữ liệu thông số linh hoạt nhưng mất ràng buộc quan hệ cần cho Product/Offer/Alert.
