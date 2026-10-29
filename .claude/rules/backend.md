---
paths:
  - "backend/**/*.py"
  - "backend/pyproject.toml"
  - "backend/alembic/**"
---

# Quy tắc backend

- Chạy mọi lệnh Python qua `uv run` trong `backend/`. Thêm gói bằng `uv add <gói>` (dev: `uv add --dev`), không dùng pip.
- Ranh giới module (kiểm tra trước khi import; bảng đầy đủ ở `docs/03-architecture.md` §4, kiểm tự động bằng `tests/unit/test_layer_boundaries.py`, đổi quy tắc thì sửa cả hai):
  - Mọi module được import `app/domain` và `app/config`.
  - `app/api` chỉ import `app/agent`, `app/services`.
  - `app/agent` chỉ import `app/agent/tools`, `app/services`, `app/normalize` (hàm thuần); `app/agent/tools` chỉ import `app/services`.
  - `app/scrapers` chỉ import `app/normalize`. **Ngoại lệ duy nhất:** `app/scrapers/pipeline.py` được import thêm `app/db/repositories` (nối scraper → normalize → repository). Pipeline không gọi `services`.
  - Chạy thu thập (worker, router quản trị) luôn qua `app/services/scrape_service.py`, nơi gọi pipeline rồi `alert_service.evaluate`.
  - `app/db` chỉ import `app/domain`, `app/config`.
- Hàm I/O dùng `async`; không gọi blocking I/O trong coroutine (dùng `httpx.AsyncClient`, `asyncio.to_thread` khi bắt buộc).
- Pydantic v2: `model_config = ConfigDict(...)`, `model_validate`, `model_dump`. Không dùng API v1.
- Phiên DB: một session mỗi request (dependency FastAPI), repository nhận session qua tham số; không tạo engine trong hàm nghiệp vụ.
- Lỗi nghiệp vụ là exception riêng trong `app/domain/errors.py` có `code` khớp bảng mã lỗi ở `docs/07-api-spec.md` §2; handler ở `app/api` chuyển thành JSON lỗi chuẩn.
- Router FastAPI khai báo `response_model` và `summary` để OpenAPI đầy đủ (frontend sinh kiểu từ đó).
- Log bằng `logging` theo cấu hình ở `app/logging.py`, kèm `run_id` khi có; không `print`.
- Docstring ngắn cho hàm public, ghi rõ đơn vị (VND, giây, UTC).
- CSDL là PostgreSQL ([ADR-0007](../../docs/adr/0007-postgresql.md)): cột JSON dùng `JSONB` (`sqlalchemy.dialects.postgresql.JSONB`), lọc bằng toán tử JSONB của SQLAlchemy, không SQL thô; enum là `VARCHAR` + `CHECK`; datetime có timezone. Không viết code tương thích SQLite.
- Đổi model SQLModel → tạo migration Alembic (`uv run alembic revision --autogenerate -m "..."`), đọc lại file migration sinh ra, thêm test upgrade.
