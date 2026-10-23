# Architecture Decision Records

| ADR | Quyết định | Trạng thái |
| --- | --- | --- |
| [0001](0001-gemini-langchain.md) | LangChain + Gemini, đổi được provider | Chấp nhận |
| [0002](0002-sqlite-sqlmodel.md) | SQLite + SQLModel + Alembic | Bị thay thế bởi ADR-0007 |
| [0003](0003-collect-first-pipeline.md) | Thu thập trước, agent trả lời từ DB | Chấp nhận |
| [0004](0004-react-frontend.md) | React + Vite + TS + Tailwind + shadcn/ui | Chấp nhận |
| [0005](0005-tiered-categories.md) | Phân tầng nhóm sản phẩm | Chấp nhận |
| [0006](0006-mock-shop-hitl.md) | Mock-shop + human-in-the-loop | Chấp nhận |
| [0007](0007-postgresql.md) | PostgreSQL (Docker) + SQLModel + Alembic, test trên Postgres thật | Chấp nhận |
| [0008](0008-fptshop-anphat-replace-hoangha-laptop88.md) | FPT Shop + An Phát thay Hoàng Hà + Laptop88 làm trang lõi | Chấp nhận; thay một phần ADR-0005 |
| [0009](0009-mock-shop-compose-host.md) | Chấp nhận `mock-shop` (tên service Compose) làm địa chỉ cục bộ của mock-shop | Chấp nhận; bổ sung ADR-0006 |

## Quy tắc
- ADR đã chấp nhận **không sửa** (hook `protect_files.py` chặn). Đổi quyết định = tạo ADR mới với số kế tiếp, ghi "Thay thế ADR-XXXX", rồi cập nhật bảng trên.
- Viết ADR khi: đổi thư viện chính, đổi schema lớn, đổi phạm vi, thêm/bớt nguồn dữ liệu.

## Mẫu

```markdown
# ADR-XXXX: <Tiêu đề quyết định>

- Trạng thái: Chấp nhận | Thay thế ADR-YYYY
- Ngày: YYYY-MM-DD

## Bối cảnh
## Quyết định
## Hệ quả
## Phương án đã cân nhắc
```
