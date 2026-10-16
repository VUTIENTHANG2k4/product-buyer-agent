# ADR-0007: PostgreSQL + SQLModel + Alembic

- Trạng thái: Chấp nhận — Thay thế ADR-0002
- Ngày: 2026-10-16

## Bối cảnh
ADR-0002 chọn SQLite để dễ cài đặt. Trước khi viết code (chưa bắt đầu M0), người dùng quyết định dùng PostgreSQL:
- API và worker ghi đồng thời (lượt thu thập, đánh giá cảnh báo, agent run); SQLite chỉ cho một process ghi tại một thời điểm.
- Lọc theo thông số JSON là truy vấn chính của agent; PostgreSQL có `JSONB` và chỉ mục GIN.
- Gần với môi trường triển khai thực tế hơn, phù hợp mục tiêu đồ án.

Đổi lúc này rẻ nhất: chưa có model, migration hay dữ liệu nào.

## Quyết định
- **PostgreSQL 17**, chạy bằng **Docker Compose** (service `db` trong `docker-compose.yml` ở thư mục gốc) cho cả dev và demo. Docker Desktop trở thành yêu cầu bắt buộc.
- Driver **psycopg 3** (`psycopg[binary]`), URL dạng `postgresql+psycopg://user:pass@host:5432/db`. Engine/session đồng bộ như SQLModel mặc định.
- Vẫn dùng **SQLModel** cho model và **Alembic** cho migration.
- Cột `specs`, `raw_specs` và các cột JSON khác dùng **`JSONB`**; lọc thông số bằng toán tử JSONB của SQLAlchemy (`specs["gpu_rank"].as_integer()`…); chỉ mục GIN trên `product.specs`.
- Enum lưu dạng `VARCHAR` + ràng buộc `CHECK` (không dùng kiểu `ENUM` gốc của PostgreSQL) để thêm giá trị chỉ cần migration đơn giản.
- Thời gian: cột `TIMESTAMP WITH TIME ZONE`, lưu UTC.
- UNIQUE có điều kiện (`product` khi `model_code` khác null) dùng chỉ mục unique một phần (`postgresql_where`).
- **Test chạy trên PostgreSQL thật**: database riêng `product_buyer_test`; `alembic upgrade head` một lần mỗi phiên pytest; mỗi test bọc trong transaction và rollback khi xong. CI dùng service `postgres:17` của GitHub Actions.

## Hệ quả
- Người phát triển phải chạy `make db-up` (Docker) trước `make setup`, `make dev`, `make check`.
- Test và production cùng dialect: không lệch hành vi JSON, ràng buộc, múi giờ.
- Test chậm hơn SQLite bộ nhớ một chút; bù lại bằng rollback theo transaction thay vì tạo lại schema.
- Fixture chặn mạng trong test phải cho phép kết nối tới host của `TEST_DATABASE_URL`.
- Sao lưu bằng `pg_dump` thay cho sao chép file.
- Thư mục `backend/data/` vẫn giữ cho cache file (HTML thô, robots.txt), không còn chứa CSDL.

## Phương án đã cân nhắc
- Giữ SQLite (ADR-0002): đơn giản nhất nhưng giới hạn ghi đồng thời và JSON yếu hơn.
- PostgreSQL cài trực tiếp trên Windows: không cần Docker nhưng khó tái lập giữa các máy và với CI.
- Testcontainers: tự bật container mỗi lần test, nhưng chậm khởi động và vẫn cần Docker; dùng chung service `db` đơn giản hơn.
- SQLite cho unit test, PostgreSQL cho integration: nhanh nhưng hai dialect khác nhau ở truy vấn JSON.
- asyncpg + `AsyncSession`: hiệu năng tốt hơn nhưng phức tạp hơn cho repository và Alembic; không cần với tải một người dùng.
