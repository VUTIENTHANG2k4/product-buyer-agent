# 07. Đặc tả API

> Phiên bản 1.0 · 2026-10-16 · Base URL: `http://localhost:8000/api`
> Liên quan: [04 Dữ liệu](04-data-model.md) · [05 Agent](05-agent-design.md) · [08 UI/UX](08-ui-ux.md)

## 1. Quy ước

- JSON UTF-8, tên trường `snake_case`. Thời gian ISO 8601 UTC (`2026-10-16T03:00:00Z`). Tiền là số nguyên VND.
- Phân trang: `?page=1&page_size=20` (tối đa 100), phản hồi `{items, total, page, page_size}`.
- Lỗi: HTTP 4xx/5xx với thân
  ```json
  {"error": {"code": "PRODUCT_NOT_FOUND", "message": "Không tìm thấy sản phẩm 999", "details": {}}}
  ```
  `details` luôn là object (có thể rỗng). Với `VALIDATION_ERROR`: `{"errors": [{"in": "query|body|path|header|cookie", "field": "page_size", "message": "…", "type": "less_than_equal"}]}`; `field` là đường dẫn chấm (`items.0.name`, rỗng nếu lỗi ở gốc body hoặc JSON sai cú pháp). Không trả lại trường `input`/`ctx` của pydantic; `message` do pydantic sinh (tiếng Anh) và một số loại lỗi (uuid, `value_error`) có thể nhắc một phần giá trị, nên giao diện dựa vào `type`. Lỗi 500 không kèm stack trace hay thông điệp ngoại lệ. Router không ném `HTTPException` cho lỗi nghiệp vụ mà dùng lớp con của `AppError`; `HTTPException` chỉ giữ thông điệp riêng khi khác cụm chuẩn của HTTP (ví dụ "Not Found"). Mã 204 và 304 không có thân.
- OpenAPI tự sinh tại `/api/openapi.json`; frontend sinh kiểu bằng `openapi-typescript` (lệnh `npm run gen:api`). **OpenAPI là nguồn sự thật**; bảng dưới là bản tóm tắt để lập kế hoạch.
- Không xác thực (ứng dụng cục bộ). CORS cho `http://localhost:5173`.
- Frontend: `VITE_API_BASE_URL` là gốc máy chủ (`http://localhost:8000`, không gồm `/api`); `src/api/client.ts` tự thêm tiền tố `/api`.

## 2. Mã lỗi

| Code | HTTP | Khi nào |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Tham số sai |
| `NOT_FOUND` | 404 | Đường dẫn không tồn tại |
| `METHOD_NOT_ALLOWED` | 405 | Sai phương thức HTTP (kèm header `Allow`) |
| `PRODUCT_NOT_FOUND`, `LIST_NOT_FOUND`, `ALERT_NOT_FOUND`, `RUN_NOT_FOUND` | 404 | |
| `DUPLICATE_ALERT` | 409 | Đã có cảnh báo `active` cùng sản phẩm và ngưỡng |
| `SCRAPE_ALREADY_RUNNING` | 409 | Đang có lượt RUNNING cho (site, category) |
| `SITE_COOLDOWN` | 409 | Trang đang trong thời gian tạm nghỉ sau BLOCKED |
| `OFFLINE_MODE` | 409 | Yêu cầu chạy trang thật khi `SCRAPER_OFFLINE_ONLY=true` |
| `CHALLENGE_NOT_PENDING` | 409 | Gửi đáp án khi run không ở `NEEDS_HUMAN` |
| `CHALLENGE_FAILED` | 400 | Đáp án sai |
| `LLM_UNAVAILABLE` | 503 | Không gọi được LLM |
| `AGENT_HALLUCINATION` | – (chỉ trong sự kiện SSE `error`) | Guardrail loại toàn bộ sản phẩm LLM nêu vì không có trong kết quả tool |
| `AGENT_STEP_LIMIT` | – (chỉ trong sự kiện SSE `error`) | Vượt `AGENT_MAX_STEPS` mà chưa có kết quả nào để tổng hợp |
| `INTERNAL_ERROR` | 500 | Lỗi không lường trước (response vẫn mang header CORS) |

Lỗi HTTP khác do framework sinh ra (ví dụ 418) dùng mã `HTTP_<status>`; frontend dùng cùng quy ước khi thân lỗi không phải JSON.

## 3. Endpoint

### 3.1 Hệ thống
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/health` | `{status: "ok", db: "ok", llm_provider, offline_mode, version}`. Khi CSDL không kết nối được: HTTP 200 với `status: "degraded"`, `db: "error"` (các trường còn lại giữ nguyên). |

### 3.2 Chat / Agent
| Method | Path | Mô tả |
| --- | --- | --- |
| POST | `/chat` | Body `{message: str (1..1000), conversation_id?: int}` → 202 `{run_id, conversation_id}` |
| GET | `/chat/{run_id}/events` | `text/event-stream`; sự kiện theo [05 §6](05-agent-design.md#6-sự-kiện-tiến-trình-sse). Kết nối lại sau khi run xong → phát lại toàn bộ sự kiện đã lưu rồi đóng |
| GET | `/chat/{run_id}` | Trạng thái và kết quả cuối `{status, intent, final?}` |
| GET | `/conversations` | Danh sách hội thoại gần đây |
| GET | `/conversations/{id}/messages` | Tin nhắn của hội thoại |

`ProductRow` (dùng trong sự kiện `final.table`):
```json
{
  "product_id": 12, "name": "MockBook Gaming 15 MG15-4060", "brand": "MockBrand",
  "category": "laptop", "key_specs": {"cpu_model": "i7-13620H", "gpu_model": "RTX 4060", "ram_gb": 16},
  "min_price": 27490000,
  "offers": [{"site": "mockshop", "price": 27490000, "price_type": "sale", "url": "http://localhost:8100/p/mg15-4060", "scraped_at": "2026-10-16T02:00:00Z", "stock_status": "in_stock"}],
  "image_url": null
}
```
(Dữ liệu hư cấu từ mock-shop, chỉ để minh họa định dạng.)

### 3.3 Danh mục
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/products` | Lọc: `category`, `q`, `price_min`, `price_max`, `brand` (lặp), `site` (lặp), `spec.<field>__<op>=<value>` (ví dụ `spec.gpu_rank__gte=40`), `sort` (`price_asc` mặc định, `price_desc`, `rating_desc`, `updated_desc`), phân trang. Phản hồi thêm `stale` (dữ liệu cũ hơn 24 giờ) và `data_as_of` (mốc thu thập cũ nhất trong kết quả) ngoài `{items, total, page, page_size}` |
| GET | `/products/{id}` | Sản phẩm + toàn bộ offer |
| GET | `/products/{id}/price-history?days=30` | `{series: [{site, points: [{t, price, price_type}]}], min_price, max_price}`; `days` 1..180 |
| POST | `/compare` | Body `{product_ids: [int] (2..5, khác nhau)}` → `{products, differing_fields, cheapest_product_id}`; id không tồn tại → 404 `PRODUCT_NOT_FOUND` (`details.product_ids`) |
| GET | `/categories` | `{items: [{key, tier, product_count, filter_fields: [{name, kind, ops, choices}]}]}` để frontend dựng bộ lọc |

Quy ước `spec.*` ở `/products`: cần có `category`; `<op>` là `eq` (mặc định nếu bỏ `__<op>`), `gte`, `lte`, `contains`, `contains_any`, `in`; `in` và `contains_any` nhận danh sách cách nhau bằng dấu phẩy. Trường, kiểu (`integer`, `number`, `boolean`, `string`, `list`), toán tử hợp lệ và giá trị enum (`choices`) của từng nhóm lấy từ `GET /categories` (sinh từ khung specs, gồm cả `gpu_rank` của laptop). Trường lạ, toán tử không hợp với kiểu, giá trị sai kiểu hoặc ngoài `choices` → 422 `VALIDATION_ERROR`. `tier` là 1 cho nhóm có khung specs, 2 cho `other` (chỉ tìm trực tiếp, `product_count` 0, không có `filter_fields`); `product_count` đếm sản phẩm còn ít nhất một offer đang bán.

Id trong đường dẫn hoặc thân yêu cầu ngoài miền khóa chính (≤ 0 hoặc > 2^31−1) được coi là không tồn tại: 404 với mã `*_NOT_FOUND` tương ứng, không phải 500.

### 3.4 Danh sách mua
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/lists` | Danh sách + số mục + tổng tiền theo giá thấp nhất hiện tại |
| POST | `/lists` | `{name}` |
| GET | `/lists/{id}` | Chi tiết với các mục (kèm giá hiện tại và chênh lệch so với `price_at_add`) |
| PATCH | `/lists/{id}` | `{name}` |
| DELETE | `/lists/{id}` | |
| POST | `/lists/{id}/items` | `{product_id, quantity?, note?, preferred_offer_id?}`; trùng → tăng `quantity` |
| PATCH | `/lists/{id}/items/{item_id}` | `{quantity?, note?, preferred_offer_id?}` |
| DELETE | `/lists/{id}/items/{item_id}` | |

### 3.5 Cảnh báo giá
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/alerts?status=` | |
| POST | `/alerts` | `{product_id, target_price, channel?, destination?}`; thiếu channel/destination → lấy mặc định từ cấu hình |
| PATCH | `/alerts/{id}` | `{target_price?, status? (active/paused)}` |
| DELETE | `/alerts/{id}` | |
| POST | `/alerts/{id}/test` | Gửi thông báo thử tới kênh đã cấu hình |

### 3.6 Quản trị thu thập
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/admin/sources` | Mỗi trang: `key`, `enabled`, `categories`, `robots_status` (`allowed`/`partial`/`unknown`), `effective_delay_s`, `supports_live_search`, `last_run`, `cooldown_until?` |
| GET | `/admin/scrape-runs?site=&category=&status=` | Phân trang, mới nhất trước |
| GET | `/admin/scrape-runs/{id}` | Chi tiết + thống kê + lỗi |
| POST | `/admin/scrape-runs` | `{site, category, max_pages?}` → 202 `{run_id}`; chạy nền |
| GET | `/admin/scrape-runs/{id}/challenge` | Khi `NEEDS_HUMAN`: `{kind, prompt, image_url?}` |
| POST | `/admin/scrape-runs/{id}/challenge` | `{answer}` → 200 `{status: "RUNNING"}` hoặc `CHALLENGE_FAILED` |

## 4. Ví dụ SSE

```
event: plan
data: {"intent":{"category":"laptop","tier":1,"price_max":30000000,"spec_filters":[{"field":"gpu_rank","op":"gte","value":40}],"sort":"price_asc","limit":10,"needs_clarification":false},"steps":["Tìm laptop trong danh mục đã thu thập","Lọc GPU từ RTX 4060 trở lên, giá dưới 30 triệu","So sánh giá giữa GearVN, FPT Shop, An Phát"]}

event: tool_start
data: {"call_id":"c1","tool":"search_catalog","args_summary":"laptop, ≤ 30.000.000 ₫, GPU ≥ RTX 4060"}

event: tool_end
data: {"call_id":"c1","tool":"search_catalog","ok":true,"summary":"Tìm thấy 7 sản phẩm","duration_ms":84}

event: final
data: {"text":"Có 7 laptop phù hợp…","table":[…],"live_items":[],"suggestions":["So sánh 2 máy rẻ nhất","Đặt cảnh báo giá"],"data_as_of":"2026-10-16T02:00:00Z"}
```
