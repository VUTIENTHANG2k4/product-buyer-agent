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
- OpenAPI tự sinh tại `/api/openapi.json`; frontend sinh kiểu bằng `openapi-typescript` 7.13.0: `make gen-api` xuất OpenAPI ra `frontend/openapi.json` (`backend/scripts/dump_openapi.py`, không cần CSDL hay `.env`) rồi chạy `npm run gen:api` ra `frontend/src/api/types.gen.ts` (cả hai file đều commit; `src/api/types.ts` đặt tên gọn). Test backend `tests/api/test_openapi.py` báo đỏ khi `openapi.json` lệch API, và CI báo đỏ khi `types.gen.ts` lệch `openapi.json`: đổi API thì chạy `make gen-api` và commit hai file. **OpenAPI là nguồn sự thật**; bảng dưới là bản tóm tắt để lập kế hoạch.
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
| POST | `/chat` | Body `{message: str (1..1000), conversation_id?: int}` → 202 `{run_id, conversation_id}`; agent chạy nền. `conversation_id` không tồn tại → 404 `NOT_FOUND`; tin nhắn rỗng/quá dài/có NUL → 422; thiếu khóa LLM → 503 `LLM_UNAVAILABLE` |
| GET | `/chat/{run_id}/events` | `text/event-stream`; sự kiện theo [05 §6](05-agent-design.md#6-sự-kiện-tiến-trình-sse). Kết nối lại sau khi run xong → phát lại toàn bộ sự kiện đã lưu rồi đóng |
| GET | `/chat/{run_id}` | Trạng thái và kết quả cuối `{run_id, conversation_id, status, intent, final?, clarification?, error?}` (`final`/`error` cùng dạng với dữ liệu sự kiện SSE cùng tên) |
| GET | `/conversations?limit=20` | `{items: [{conversation_id, title, created_at}]}`, mới nhất trước (`limit` 1..100) |
| GET | `/conversations/{id}/messages` | `{items: [{message_id, role, content, payload, created_at}]}`, cũ → mới (tối đa 500 tin cuối); `payload` của tin trợ lý là `{product_ids}` của bảng đã hiển thị; hội thoại không tồn tại → 404 `NOT_FOUND` |

**SSE (T7.2).** Mỗi sự kiện có `event:` (tên), `data:` (JSON như §4) và `id:` là vị trí của sự kiện trong lượt (0, 1, 2…). Máy chủ không giữ kênh trong bộ nhớ: `AgentRunner` lưu từng sự kiện vào `agent_run.events` trước khi phát, và luồng SSE đọc lại từ CSDL (thăm dò 0,25 giây), nên một đường duy nhất cho lượt đang chạy lẫn lượt đã xong, và sống sót qua việc khởi động lại API. Gửi header `Last-Event-ID: n` để nhận tiếp từ sau sự kiện `n`. Luồng đóng sau sự kiện `final`, `error` hoặc `clarification`, hoặc khi lượt đã đóng mà không còn sự kiện mới (lượt bị hủy). Lượt còn `running` quá 15 phút (tiến trình đã chết) được đánh `failed` ở lần `POST /chat` kế tiếp. Dùng `fastapi.sse.EventSourceResponse` (FastAPI 0.143.3).

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
| GET | `/lists` | `{items: [{list_id, name, item_count, total_price, updated_at}]}`; tổng tiền theo giá hiện tại của từng mục |
| POST | `/lists` | `{name}` → 201 |
| GET | `/lists/{id}` | Chi tiết với các mục (kèm giá hiện tại và chênh lệch so với `price_at_add`) |
| PATCH | `/lists/{id}` | `{name}` |
| DELETE | `/lists/{id}` | 204 |
| POST | `/lists/{id}/items` | `{product_id, quantity?, note?, preferred_offer_id?}` → 201; trùng → tăng `quantity` (giữ `price_at_add` ban đầu) |
| PATCH | `/lists/{id}/items/{item_id}` | `{quantity?, note?, preferred_offer_id?}`; trường bỏ vắng giữ nguyên, `null` ở `note`/`preferred_offer_id` xóa giá trị |
| DELETE | `/lists/{id}/items/{item_id}` | 204 |

`quantity` 1..2.147.483.647 (cộng dồn cũng không được vượt); `note` ≤ 500 ký tự; `preferred_offer_id` phải là offer của chính sản phẩm của mục, nếu không 422 `VALIDATION_ERROR`; mục của danh sách khác → 404 `LIST_NOT_FOUND`; `product_id` không tồn tại → 404 `PRODUCT_NOT_FOUND`.

### 3.5 Cảnh báo giá
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/alerts?status=` | `{items: [...]}`, mới nhất trước |
| POST | `/alerts` | `{product_id, target_price, channel?, destination?}` → 201; thiếu channel/destination → lấy mặc định từ cấu hình; nơi nhận chưa cấu hình hoặc sai định dạng → 422 |
| PATCH | `/alerts/{id}` | `{target_price?, status? (active/paused)}`; ngưỡng trùng cảnh báo khác đang hiệu lực → 409 `DUPLICATE_ALERT` |
| DELETE | `/alerts/{id}` | 204 |
| POST | `/alerts/{id}/test` | `{sent, reason?}`. Bộ gửi email/Telegram thuộc M9 nên hiện luôn trả `sent: false` kèm lý do (không giả vờ gửi) |

### 3.6 Quản trị thu thập
| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/admin/sources` | `{items: [...]}`, mỗi trang: `key`, `enabled`, `is_mock`, `categories`, `robots_status`, `effective_delay_s`, `supports_live_search`, `last_run`, `cooldown_until?` |
| GET | `/admin/scrape-runs?site=&category=&status=` | Phân trang `{items, total, page, page_size}`, mới nhất trước |
| GET | `/admin/scrape-runs/{id}` | Chi tiết: trạng thái, bộ đếm (`pages_fetched`, `items_parsed`, `items_failed`, `offers_upserted`, `price_changes`), `started_at`, `finished_at`, `error_message`, `challenge_kind` |
| POST | `/admin/scrape-runs` | `{site, category, max_pages? (1..100)}` → 202 `{run_id}`; chạy nền (theo dõi bằng `GET .../{id}`) |
| GET | `/admin/scrape-runs/{id}/challenge` | Khi `NEEDS_HUMAN`: `{kind, prompt, image_url?}` (không có `token`); lượt không chờ đáp án hoặc đã chờ quá 1 giờ → 409 `CHALLENGE_NOT_PENDING` |
| POST | `/admin/scrape-runs/{id}/challenge` | `{answer}` → 200 `{status: "RUNNING"}` (lượt chạy tiếp ở nền) hoặc 400 `CHALLENGE_FAILED` (lượt vẫn chờ, thử lại được) |

Lỗi đồng bộ của `POST /admin/scrape-runs`: 409 `OFFLINE_MODE` (trang thật khi `SCRAPER_OFFLINE_ONLY=true`), 409 `SCRAPE_ALREADY_RUNNING` (kèm `details.run_id`), 409 `SITE_COOLDOWN` (kèm `details.retry_after`), 422 `VALIDATION_ERROR` (trang chưa có scraper hoặc đã tắt, nhóm không thuộc trang, `max_pages` sai). Lượt chạy nền kết thúc `SUCCEEDED`/`PARTIAL`/`FAILED`/`BLOCKED`/`NEEDS_HUMAN` ghi trong `ScrapeRun`.

`robots_status`: `allowed` (robots.txt đã tải, không chặn gì; mock-shop luôn `allowed`), `partial` (đã tải và có luật chặn một phần hoặc chặn tất cả), `unknown` (chưa tải robots.txt trong tiến trình API này; trang quản trị không gọi mạng). `effective_delay_s` là độ trễ giữa hai request: `max(SCRAPER_MIN_DELAY_SECONDS, độ trễ của trang, Crawl-delay đã tải)` (mock-shop: `MOCK_SHOP_DELAY_SECONDS`). `cooldown_until` chỉ có khi trang thật đang nghỉ 24 giờ sau lượt `BLOCKED`.

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
