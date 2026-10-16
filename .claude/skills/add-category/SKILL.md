---
name: add-category
description: Thêm một nhóm sản phẩm vào tầng 1 (khung thông số, bộ trích xuất, golden test, lọc, agent) hoặc mở rộng khung thông số của nhóm có sẵn. Dùng cho T1.3, T5.1 và pha mở rộng X1 (điện thoại).
argument-hint: "<category>"
---

# Thêm / mở rộng nhóm sản phẩm tầng 1

Tài liệu gốc: `docs/04-data-model.md` §5, §7; `docs/adr/0005-tiered-categories.md`.

Điều kiện trước: nhóm có ít nhất 2 nguồn lõi cung cấp (`docs/02-scope-and-sources.md` §1). Với điện thoại (X1), Viettel Store và Nguyễn Kim được nâng thành trang lõi của nhóm (cùng Hoàng Hà) — cập nhật ma trận trong 02 §1 trước. Không đủ nguồn → giữ ở tầng 2, báo người dùng.

## Các bước
1. **Thiết kế khung** — thêm mục mới ở `docs/04-data-model.md` §5: bảng trường, kiểu, ví dụ, cột "Bắt buộc" (2–4 trường mà người dùng hay lọc). Người dùng duyệt nếu là nhóm mới.
2. **Enum** — thêm giá trị vào `Category` (`app/domain/enums.py`). Nếu cần migration (ràng buộc CHECK), tạo bằng Alembic.
3. **Model specs** — `app/normalize/specs/<category>.py`: `class <Name>Specs(BaseModel)` + `REQUIRED_FIELDS`. Đăng ký trong `SPEC_MODELS: dict[Category, type[BaseModel]]`.
4. **Bộ trích xuất luật** — `extract_<category>(title: str, raw_specs: dict[str, str]) -> <Name>Specs`: regex trên tiêu đề + ánh xạ nhãn bảng thông số (ví dụ "Kết nối", "Connectivity" → `connection`). Gom từ đồng nghĩa tiếng Việt/Anh trong một dict hằng.
5. **Golden** — `backend/tests/unit/golden/<category>.yaml`: ≥ 15 ca lấy từ tiêu đề **thật** trong fixture (≥ 40 cho laptop). Test tham số hóa; độ chính xác trường bắt buộc ≥ 95%.
6. **Lọc** — kiểm tra `catalog_service.search` lọc được mọi trường bắt buộc (số: `gte`/`lte`; enum: `eq`/`in`; list: `contains`/`contains_any`). Thêm test.
7. **Agent** — cập nhật `app/agent/prompts/planner.md`: tên nhóm, từ đồng nghĩa tiếng Việt ("phím cơ", "tai nghe chụp tai"…), cách chuyển yêu cầu thành `spec_filters`. Thêm ≥ 3 câu vào `docs/eval/queries.yaml` và dữ liệu seed tương ứng.
8. **API/UI** — `GET /api/categories` trả trường lọc mới; frontend hiển thị `key_specs` phù hợp (tối đa 6 trường).
9. `/check`, cập nhật `docs/02` §1 (ma trận) nếu đổi.
