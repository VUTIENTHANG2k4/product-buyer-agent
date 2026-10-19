# 04. Thiết kế dữ liệu

> Phiên bản 1.0 · 2026-10-16
> Liên quan: [03 Kiến trúc](03-architecture.md) · [05 Agent](05-agent-design.md) · [06 Thu thập](06-scraping-design.md)

## 1. Nguyên tắc

- **Product ≠ Offer.** `Product` là một mẫu chuẩn hóa (ví dụ ASUS TUF Gaming F16 FX608JHI-TU209W); `Offer` là việc một trang rao bán mẫu đó với giá và link riêng. Đây là cơ sở để so sánh giá giữa các trang.
- **Tiền là số nguyên VND** (`int`), không dùng float.
- **Thời gian lưu UTC** (`datetime` có timezone, cột `TIMESTAMP WITH TIME ZONE`).
- **Thông số theo khung riêng từng nhóm**, lưu cột `JSONB` `specs`, được kiểm tra bằng model Pydantic tương ứng trước khi ghi.
- **CSDL là PostgreSQL 17** ([ADR-0007](adr/0007-postgresql.md)). Mọi cột `json` trong ERD là `JSONB`. Enum lưu `VARCHAR` + `CHECK`, không dùng kiểu `ENUM` gốc.
- **Lịch sử giá chỉ thêm** (append-only).
- **Không lưu dữ liệu cá nhân** từ trang nguồn.

## 2. Sơ đồ quan hệ (ERD)

```mermaid
erDiagram
  PRODUCT ||--o{ OFFER : "được bán qua"
  OFFER ||--o{ PRICE_HISTORY : "có lịch sử"
  PRODUCT ||--o{ SHOPPING_LIST_ITEM : "nằm trong"
  SHOPPING_LIST ||--o{ SHOPPING_LIST_ITEM : "gồm"
  PRODUCT ||--o{ PRICE_ALERT : "được theo dõi"
  CONVERSATION ||--o{ MESSAGE : "gồm"
  CONVERSATION ||--o{ AGENT_RUN : "sinh ra"

  PRODUCT {
    int id PK
    string category
    string brand
    string model_code "chuẩn hóa, có thể null"
    string canonical_name
    json specs
    float specs_confidence
    string image_url
    datetime created_at
    datetime updated_at
  }
  OFFER {
    int id PK
    int product_id FK
    string site
    string url UK
    string site_sku
    string title
    int price
    int list_price
    string price_type
    string stock_status
    float rating
    int rating_count
    json raw_specs
    string match_method
    float match_score
    bool is_active
    datetime first_seen_at
    datetime scraped_at
  }
  PRICE_HISTORY {
    int id PK
    int offer_id FK
    int price
    string price_type
    string stock_status
    datetime scraped_at
  }
  SCRAPE_RUN {
    int id PK
    string site
    string category
    string status
    string trigger
    int pages_fetched
    int items_parsed
    int items_failed
    int offers_upserted
    int price_changes
    json challenge
    string error_message
    datetime started_at
    datetime finished_at
  }
  SHOPPING_LIST {
    int id PK
    string name
    datetime created_at
    datetime updated_at
  }
  SHOPPING_LIST_ITEM {
    int id PK
    int list_id FK
    int product_id FK
    int preferred_offer_id FK
    int quantity
    int price_at_add
    string note
    datetime added_at
  }
  PRICE_ALERT {
    int id PK
    int product_id FK
    int target_price
    string channel
    string destination
    string status
    int last_notified_price
    datetime last_notified_at
    datetime created_at
  }
  CONVERSATION {
    int id PK
    string title
    datetime created_at
  }
  MESSAGE {
    int id PK
    int conversation_id FK
    string role
    string content
    json payload
    datetime created_at
  }
  AGENT_RUN {
    string id PK "uuid"
    int conversation_id FK
    string status
    json intent
    json events
    int tool_calls
    int latency_ms
    datetime created_at
  }
  LLM_EXTRACTION_CACHE {
    string content_hash PK
    string category
    json result
    string model
    datetime created_at
  }
  LIVE_SEARCH_CACHE {
    string cache_key PK
    json results
    datetime created_at
  }
```

`SCRAPE_RUN`, `LLM_EXTRACTION_CACHE`, `LIVE_SEARCH_CACHE` không có khóa ngoại.

## 3. Bảng chi tiết và ràng buộc

| Bảng | Ràng buộc / chỉ mục | Ghi chú |
| --- | --- | --- |
| `product` | UNIQUE(`category`, `brand`, `model_code`) khi `model_code` khác null (chỉ mục unique một phần, `postgresql_where`); INDEX(`category`); GIN(`specs`) | `canonical_name` là tên sạch, không chứa từ quảng cáo |
| `offer` | UNIQUE(`url`); INDEX(`product_id`); INDEX(`site`, `is_active`) | `is_active=false` khi lượt chạy đầy đủ không còn thấy offer |
| `price_history` | INDEX(`offer_id`, `scraped_at`) | Thêm dòng khi giá, `price_type` hoặc `stock_status` đổi, **hoặc** dòng cuối cũ hơn 24 giờ |
| `scrape_run` | INDEX(`site`, `category`, `started_at`) | |
| `shopping_list_item` | UNIQUE(`list_id`, `product_id`) | Thêm trùng → tăng `quantity` |
| `price_alert` | INDEX(`product_id`, `status`) | `destination` = email hoặc Telegram chat id |
| `agent_run` | PK uuid | `events` lưu toàn bộ sự kiện SSE để xem lại và debug |

**Quy ước lưu trữ đã cài đặt** (`app/db/models.py`, migration `backend/alembic/versions/0001_initial_schema.py`):

- Tiền (`price`, `list_price`, `price_at_add`, `target_price`, `last_notified_price`) là `BIGINT` + `CHECK >= 0` (`target_price > 0`). `offer.price` **NOT NULL**: mục không đọc được giá bị bỏ qua ở pipeline (T2.6) và tính vào `items_failed`; `price_history.price` cũng NOT NULL.
- Cột nullable theo DTO: `product.model_code`, `product.image_url`, `offer.list_price/site_sku/rating/rating_count/match_score`, `shopping_list_item.preferred_offer_id/price_at_add/note`, `scrape_run.challenge/error_message/finished_at`, `price_alert.last_notified_*`, `conversation.title`, `message.payload`, `agent_run.intent/latency_ms`. Còn lại NOT NULL (`product.brand` cũng NOT NULL: `detect_brand` phải có giá trị dự phòng).
- Enum là `VARCHAR(32)` + `CHECK` tên `ck_<bảng>_<cột>`. Alembic autogenerate **không** so sánh CHECK: thêm giá trị enum phải viết migration tay (bỏ và tạo lại ràng buộc).
- `CHECK` bổ sung: `specs_confidence`, `match_score` trong 0..1; `rating` trong 0..5; `quantity >= 1`; `rating_count`, các bộ đếm của `scrape_run`, `agent_run.tool_calls`, `latency_ms` ≥ 0.
- Khóa ngoại: `offer.product_id` không cascade (chặn xóa `product` còn offer); `shopping_list_item.product_id` `RESTRICT`; `price_history.offer_id`, `shopping_list_item.list_id`, `price_alert.product_id`, `message.conversation_id`, `agent_run.conversation_id` `ON DELETE CASCADE`; `shopping_list_item.preferred_offer_id` `SET NULL`.
- Chỉ mục thêm ngoài bảng trên: `message(conversation_id, created_at)` và `agent_run(conversation_id)` (liệt kê theo hội thoại). `agent_run.id` là `UUID` gốc của PostgreSQL.
- Chỉ mục GIN mặc định (`jsonb_ops`) chỉ tăng tốc `@>` và `?`; lọc `specs["gpu_rank"].as_integer() >= 40` dùng `->>` nên không dùng GIN. Nếu đo thấy chậm ở T1.4, thêm chỉ mục biểu thức riêng cho `gpu_rank`.
- JSONB không theo dõi thay đổi tại chỗ: repository gán lại cả dict/list. Python `None` ở cột JSONB nullable lưu thành SQL `NULL` (`none_as_null`).

Migration bằng Alembic (`make migrate`; URL lấy từ `DATABASE_URL`). Mỗi thay đổi schema = một migration + test chạy `alembic upgrade head` trên DB PostgreSQL rỗng (`backend/tests/integration/test_migrations.py` còn kiểm model và migration không lệch nhau).

Lọc thông số dùng toán tử JSONB của SQLAlchemy (ví dụ `Product.specs["gpu_rank"].as_integer() >= 40`, `Product.specs["is_gaming"].as_boolean()`), không viết SQL thô.

**Repository** (`app/db/repositories/`, T1.4):

- Mỗi lớp nhận `Session` qua `__init__`, chỉ `flush`, **không `commit`** (service/pipeline giữ transaction). Hàm có yếu tố thời gian nhận `now` (UTC), mặc định `utc_now()`, để test dùng mốc cố định. Đồng bộ (sync), cùng kiểu với `db/engine.py`; pipeline async bọc bằng `asyncio.to_thread`.
- `OfferRepository.upsert` là `INSERT … ON CONFLICT (url) DO UPDATE … RETURNING`: giữ `id` và `first_seen_at`, làm mới phần còn lại, bật lại `is_active`; trả `created` theo `xmax = 0`. `deactivate_unseen(site, category, scraped_before)` là bước 3 của pipeline ([06 §7](06-scraping-design.md#7-pipeline-appscraperspipelinepy)).
- Luật thêm `price_history` (`PriceHistoryRepository.record_snapshot`) so với **dòng lịch sử gần nhất** của offer, không so với `offer.price`: thêm khi chưa có dòng nào (`first`), khi `price`/`price_type`/`stock_status` đổi (`changed`), hoặc khi dòng cuối cũ hơn 24 giờ (`heartbeat`; đúng 24 giờ chưa thêm). Kết quả có `previous_price` và `price_changed` (chỉ đổi `price_type`/tồn kho thì `price_changed=False`) để pipeline đếm `price_changes` và `alert_service` biết giá cũ.
- `effective_price()` (§4) là biểu thức SQL duy nhất cho giá hiệu lực; `ProductRepository.search` tính giá, `sites`, số offer trên các offer **đang bán (`is_active`)** khớp điều kiện, nên sản phẩm không còn offer đang bán không xuất hiện. Từ khóa và `sort=relevance` do `catalog_service` ánh xạ trước khi gọi.
- Ánh xạ `SpecFilter` → JSONB: `eq`/`gte`/`lte` với số dùng `CASE WHEN jsonb_typeof(…) = 'number' THEN CAST(… AS FLOAT)` (trường thiếu hoặc sai kiểu thì không khớp, không lỗi truy vấn); bool dùng `as_boolean()` có cùng cách bảo vệ; chuỗi dùng `as_string()`; `contains` là `specs @> {field: [value]}`; `contains_any` là OR của các `@>` (danh sách rỗng không khớp gì); `in` dùng `as_string() IN (…)`. Tên trường luôn là tham số ràng buộc.
- `upsert` ghi đè mọi cột còn lại bằng giá trị mới, kể cả `None`/`{}` (`rating`, `site_sku`, `raw_specs`, `match_*`): pipeline (T2.6) phải truyền đủ giá trị (ví dụ gộp `raw_specs` từ trang chi tiết) trước khi gọi, nếu không lượt chỉ có trang danh sách sẽ xóa dữ liệu đã có. `record_snapshot` đọc rồi ghi không khóa; chấp nhận được vì `scrape_service` không chạy hai lượt cùng (site, category) (T9.3).
- `ShoppingListRepository.add_item`, `update_item`, `remove_item`, `rename` đều chạm `shopping_list.updated_at` (danh sách sắp theo `updated_at` mới nhất trước). `add_item` và các cache dùng `ON CONFLICT` (cộng `quantity`; ghi đè kết quả cache và làm mới `created_at`).
- `ScrapeRunRepository.set_status`: `finished_at` chỉ có ở `SUCCEEDED`/`PARTIAL`/`FAILED`/`BLOCKED`; `NEEDS_HUMAN` là trạng thái chờ, chưa kết thúc (chuyển lại `RUNNING` khi `resume`). `error_message`/`challenge` được thay bằng giá trị truyền vào (None là xóa). Repository không kiểm tra chuyển trạng thái hợp lệ; pipeline chịu trách nhiệm.
- `SpecFilter` với `in` chỉ so khớp trường vô hướng bằng chuỗi (`ram_gb in ["8","32"]` khớp số 8 và 32); không khớp trường bool hay list.

## 4. Enum

| Enum | Giá trị |
| --- | --- |
| `Category` | `laptop`, `mouse`, `keyboard`, `headset`, `phone` (mở rộng), `other` |
| `SiteKey` | `gearvn`, `hoangha`, `laptop88`, `viettelstore`, `nguyenkim`, `mockshop` |
| `PriceType` | `regular` (giá bán không giảm), `sale` (giá khuyến mãi công khai), `member` (giá thành viên), `flash` (flash sale đang diễn ra), `unknown` |
| `StockStatus` | `in_stock`, `out_of_stock`, `preorder`, `unknown` |
| `ScrapeStatus` | `PENDING`, `RUNNING`, `NEEDS_HUMAN`, `BLOCKED`, `SUCCEEDED`, `PARTIAL`, `FAILED` |
| `ScrapeTrigger` | `schedule`, `manual`, `tracked_refresh`, `test` |
| `MatchMethod` | `model_code`, `fuzzy`, `new` |
| `AlertChannel` | `email`, `telegram` |
| `AlertStatus` | `active`, `triggered`, `paused` |
| `AgentRunStatus` | `running`, `succeeded`, `needs_clarification`, `failed` |
| `MessageRole` | `user`, `assistant` (lời gọi tool nằm trong `agent_run.events`, không nằm ở bảng tin nhắn) |
| `ChallengeKind` | `http_403`, `http_429`, `captcha`, `soft_block` (chỉ nằm trong JSON của cột scrape_run.challenge, không có cột riêng nên không có CHECK) |

**Giá dùng để so sánh** (`effective_price`) của một offer: lấy `price` nếu `price_type` ∈ {`regular`, `sale`, `flash`}; nếu `member` thì vẫn hiển thị nhưng mặc định so sánh bằng `list_price` khi có, kèm nhãn "giá thành viên". Giá bị che (ví dụ flash sale sắp diễn ra hiển thị "2*.**0.000") **không lưu**.

## 5. Khung thông số theo nhóm (Pydantic)

Mọi trường đều tùy chọn khi parse; cột "Bắt buộc" là trường cần có để sản phẩm được dùng trong lọc tầng 1. Thiếu trường bắt buộc → mở trang chi tiết → vẫn thiếu → LLM dự phòng → vẫn thiếu → `specs_confidence < 0.5`, sản phẩm chỉ xuất hiện khi lọc không dùng trường đó.

Kiểu dữ liệu chặt như DTO §6: số nguyên strict (không nhận bool/chuỗi/float), dung lượng và số đo (`ram_gb`, `storage_gb`, `refresh_hz`, `dpi_max`, `weight_g`…) phải > 0 (parser đọc hỏng trả `None`, không trả 0; riêng `gpu_vram_gb` cho phép 0), số thực hữu hạn và > 0, chuỗi không rỗng. Khóa lạ bị bỏ qua (`extra="ignore"`).

### 5.1 `LaptopSpecs`

| Trường | Kiểu | Ví dụ | Bắt buộc |
| --- | --- | --- | --- |
| `cpu_model` | str | `i7-13620H`, `Ryzen 7 7435HS`, `Core Ultra 7 155H` | ✓ |
| `cpu_vendor` | enum `intel`/`amd`/`apple`/`qualcomm` | `intel` | |
| `gpu_model` | str | `RTX 4060`, `Integrated` | ✓ |
| `gpu_rank` | int | xem 5.6 | (tính từ `gpu_model`) |
| `gpu_vram_gb` | int | 8 | |
| `ram_gb` | int | 16 | ✓ |
| `storage_gb` | int | 512 | ✓ |
| `storage_type` | enum `ssd`/`hdd` | `ssd` | |
| `screen_in` | float | 15.6 | |
| `resolution` | str | `1920x1080` | |
| `refresh_hz` | int | 144 | |
| `panel` | str | `IPS`, `OLED` | |
| `weight_kg` | float | 2.2 | |
| `os` | str | `Windows 11 Home` | |
| `is_gaming` | bool | true | (suy ra: GPU rời RTX/RX hoặc danh mục gaming) |

### 5.2 `MouseSpecs`

| Trường | Kiểu | Ví dụ | Bắt buộc |
| --- | --- | --- | --- |
| `connection` | list enum `wired`/`wireless_2_4`/`bluetooth` | `[wired, wireless_2_4]` | ✓ |
| `dpi_max` | int | 26000 | |
| `sensor` | str | `HERO 25K` | |
| `buttons` | int | 6 | |
| `weight_g` | int | 63 | |
| `rgb` | bool | true | |
| `shape` | enum `ergo_right`/`ambidextrous` | | |

### 5.3 `KeyboardSpecs`

| Trường | Kiểu | Ví dụ | Bắt buộc |
| --- | --- | --- | --- |
| `connection` | list enum (như chuột) | `[wired]` | ✓ |
| `switch_type` | enum `mechanical`/`membrane`/`optical`/`magnetic` | `mechanical` | ✓ |
| `switch_name` | str | `Red`, `Gateron Brown` | |
| `form_factor` | enum `full`/`tkl`/`75`/`65`/`60`/`other` | `tkl` | |
| `hot_swap` | bool | true | |
| `backlight` | enum `none`/`single`/`rgb` | `rgb` | |

### 5.4 `HeadsetSpecs`

| Trường | Kiểu | Ví dụ | Bắt buộc |
| --- | --- | --- | --- |
| `form` | enum `over_ear`/`on_ear`/`in_ear`/`tws` | `over_ear` | ✓ |
| `connection` | list enum `wired_3_5`/`usb`/`wireless_2_4`/`bluetooth` | `[usb]` | ✓ |
| `has_mic` | bool | true | |
| `anc` | bool | false | |
| `surround_7_1` | bool | true | |
| `driver_mm` | int | 50 | |

### 5.5 `PhoneSpecs` (pha mở rộng)
`chipset`, `ram_gb`, `storage_gb` (bắt buộc), `screen_in`, `battery_mah`, `os`. Mỗi biến thể dung lượng là một `Product` riêng.

### 5.6 Xếp hạng GPU (`gpu_rank`)

Để hiểu "RTX 4060 trở lên", mỗi `gpu_model` được ánh xạ sang một số thứ hạng trong `app/normalize/specs/gpu_rank.py`. Đây là **thứ tự xấp xỉ do dự án tự định nghĩa** để lọc, không phải điểm benchmark; cần rà soát khi thêm GPU mới và có test bảo vệ thứ tự.

Giá trị khởi tạo (càng lớn càng mạnh): `Integrated` 0 · `RTX 2050` 10 · `RTX 3050` 20 · `RTX 3050 Ti` 22 · `RTX 4050` 30 · `RTX 3060` 32 · `RTX 5050` 34 · `RTX 4060` 40 · `RTX 5060` 45 · `RTX 4070` 50 · `RTX 5070` 55 · `RTX 5070 Ti` 60 · `RTX 4080` 70 · `RTX 5080` 75 · `RTX 4090` 80 · `RTX 5090` 85. GPU không có trong bảng → `null` và không thỏa bộ lọc theo hạng.

**Chuẩn hóa tên GPU** (`normalize_gpu_name`, chạy trước khi tra bảng). `LaptopSpecs` đưa `gpu_model` về tên chuẩn khi dựng model; `gpu_rank` là trường dẫn xuất chỉ đọc (`computed_field`), tính từ `gpu_model` mỗi lần truy cập nên luôn khớp kể cả khi `gpu_model` bị gán lại. `gpu_rank` vẫn có trong `model_dump()` để lọc JSONB; giá trị `gpu_rank` truyền vào khi parse bị bỏ qua.

- Không phân biệt hoa/thường; bỏ `GeForce`, `NVIDIA`, `™`, `®`, `Laptop GPU`, dung lượng VRAM. Chấp nhận `RTX4060`, `rtx 4060`, `RTX-4060`, `RTX_4060`, `GeForceRTX4060`. `"GeForce RTX4060 8GB"` → `RTX 4060`.
- Dạng chuẩn: `RTX <4 chữ số>`, `GTX <3-4 chữ số>`, `RX <4 chữ số>[M|S]`, kèm hậu tố đứng riêng từ `Ti`, `XT`, `Super` theo thứ tự đó (ví dụ `RTX 3050 Ti`, `RX 7600M XT`, `RX 6700S`). `"RTX 4060 TIGER"` vẫn ra `RTX 4060`. RTX workstation (`RTX 4000 Ada`) không được nhận.
- GPU tích hợp (`Integrated`, `Onboard`, `UHD`, `Iris`, `Intel Graphics`, `Arc Graphics`, `Radeon Graphics`, `Radeon <3-4 số>M|S`, `Apple M<số>`) → `Integrated`. GPU rời được xét trước, nên `Radeon RX 7600M` không bị coi là tích hợp. Intel Arc rời (`Arc A370M`) và `GeForce MX` cố ý không nằm trong danh sách: chưa có hạng, nên `None`.
- Tên nhận ra nhưng chưa có trong bảng (GTX, RX, `RTX 4070 Ti`, `RTX 4070 Super`…) giữ nguyên tên chuẩn, `gpu_rank = null`.
- Chuỗi nhắc tới nhiều GPU rời **khác nhau** (`"RTX 4050 (up to RTX 4060)"`) là mơ hồ → `normalize_gpu_name` trả `None`. Chuỗi không phải GPU cũng trả `None`; khi đó `LaptopSpecs` giữ nguyên chuỗi đã bỏ khoảng trắng đầu/cuối và `gpu_rank = null`.

## 6. DTO miền (`app/domain/dto.py`)

```python
class ListingItem(BaseModel):          # đầu ra parser trang danh sách
    site: SiteKey
    url: HttpUrl                       # http/https hợp lệ; pipeline gọi clean_url (§7) trước khi dựng DTO
    title: str
    price: int | None                  # None nếu không đọc được hoặc bị che
    list_price: int | None
    price_type: PriceType
    stock_status: StockStatus
    image_url: HttpUrl | None
    rating: float | None
    rating_count: int | None
    site_sku: str | None
    raw_specs: dict[str, str]          # cặp nhãn → giá trị thô hiển thị trên thẻ
    category_hint: Category

class ListingPage(BaseModel):
    items: list[ListingItem]
    has_next: bool
    next_url: HttpUrl | None

class ProductDetail(BaseModel):        # đầu ra parser trang chi tiết
    url: HttpUrl
    raw_specs: dict[str, str]
    model_code_hint: str | None        # MPN/SKU từ JSON-LD nếu có
    brand_hint: str | None

class Challenge(BaseModel):           # dấu hiệu bị chặn/captcha (06 §4); lưu vào scrape_run.challenge
    kind: ChallengeKind
    site: SiteKey
    url: HttpUrl                       # URL của trang gặp challenge
    prompt: str | None                 # đề bài (chỉ mock-shop)
    image_url: HttpUrl | None
    token: str | None                  # mã gắn với form captcha (chỉ mock-shop)

class SpecFilter(BaseModel):
    field: str                         # tên trường trong khung specs, ví dụ "gpu_rank", "ram_gb"
    op: Literal["eq", "gte", "lte", "contains", "contains_any", "in"]
    # contains: trường list chứa giá trị; contains_any: trường list chứa ít nhất một giá trị trong value (list);
    # in: trường vô hướng thuộc value (list)
    value: bool | int | float | str | list[str]   # bool cho trường bool (is_gaming); float hữu hạn

class QueryIntent(BaseModel):          # đầu ra planner
    category: Category | None
    tier: Literal[1, 2]
    keywords: list[str]
    price_min: int | None
    price_max: int | None
    brands: list[str]
    sites: list[SiteKey]               # rỗng = mọi trang
    spec_filters: list[SpecFilter]
    sort: Literal["relevance", "price_asc", "price_desc", "rating_desc"]
    limit: int = 10                    # 1..20
    needs_clarification: bool
    clarification_question: str | None
    plan_steps: list[str]              # các bước hiển thị cho người dùng
```

**Ràng buộc kiểm tra khi dựng DTO** (cài đặt ở `app/domain/dto.py`, lỗi → `ValidationError`):

- Số nguyên không nhận bool, chuỗi hay float (`price`, `list_price`, `price_min`, `price_max`, `rating_count`, `limit`): parser phải chuẩn hóa về `int` trước. Tiền ≥ 0, `rating_count` ≥ 0, `rating` 0..5, `limit` 1..20.
- `price_min ≤ price_max` khi cả hai có. `title` và `SpecFilter.field` không rỗng sau khi bỏ khoảng trắng đầu/cuối.
- `SpecFilter`: `in`/`contains_any` cần `value` là list; `gte`/`lte` cần số (không phải bool, không NaN/inf); `eq`/`contains` cần giá trị đơn.
- Giá trị mặc định: `tier=1`, `sort="relevance"`, `limit=10`, `needs_clarification=False`, các list rỗng, `price_type`/`stock_status` là `unknown`, `category_hint=other`.
- `HttpUrl` không phải `str`: lớp lưu trữ (T1.2/T1.4) ghi `str(url)`. DTO chỉ kiểm tra URL hợp lệ, không bỏ tham số theo dõi, userinfo hay fragment; việc đó là của `clean_url` (T2.5).
- Giá trị PostgreSQL không lưu được bị chặn ngay ở DTO (T1.6): `Vnd`, `ProductQuery.offset` và số nguyên của `SpecFilter` nằm trong miền BIGINT (≤ 2^63 − 1); `OfferUpsert` từ chối `url` dài hơn 2.704 byte (giới hạn chỉ mục UNIQUE) và ký tự NUL trong `url`, `title`, `site_sku`, `raw_specs`. Cận trên nghiệp vụ của giá (500.000.000) là của `parse_price` (T2.5).

## 7. Quy tắc chuẩn hóa

| Việc | Quy tắc | Module |
| --- | --- | --- |
| Giá | Bỏ ký tự không phải số trong `27.490.000₫`, `27,490,000 đ` → `27490000`. Chuỗi có `*` hoặc `?` → `None`. Giá < 10.000 hoặc > 500.000.000 → `None` + cảnh báo log | `normalize/price.py` |
| URL | Bỏ `utm_*`, `fbclid`, `gclid`, `srsltid`, fragment; giữ đường dẫn gốc | `normalize/url.py` |
| Hãng | So khớp danh sách hãng đã biết (ASUS, Acer, Lenovo, MSI, HP, Dell, Gigabyte, Apple, Logitech, Razer, Corsair, SteelSeries, HyperX, Akko, DareU, E-Dra, Rapoo…) ở đầu tên | `normalize/brand.py` |
| Mã model | Ưu tiên MPN/SKU từ JSON-LD; nếu không có, regex mẫu mã theo hãng (ví dụ `FX608JHI-TU209W`, `AN515-57-5669`, `83JE00PEVN`); viết hoa, bỏ khoảng trắng | `normalize/model_code.py` |
| Thông số | Bộ luật regex theo nhóm trên `title` + `raw_specs` (ví dụ `RTX\s?(\d{4})(\s?Ti)?`, `(\d+)\s?GB` gần từ "RAM") | `normalize/specs/<category>.py` |
| LLM dự phòng | Chỉ khi thiếu trường bắt buộc sau luật và trang chi tiết; structured output theo khung; cache theo SHA-256 của (`category`, `title`, `raw_specs`) | `normalize/llm_extractor.py` |
| Ghép model | (1) trùng `model_code` cùng `category` + `brand` → `model_code`, score 1.0. (2) Cùng hãng, cùng các trường bắt buộc, độ giống tên ≥ 0.90 (rapidfuzz `token_set_ratio`) → `fuzzy`. (3) Còn lại → `Product` mới, `new` | `normalize/matcher.py` |

Bộ test vàng: `backend/tests/unit/golden/` gồm các cặp (tiêu đề thô, thông số mong đợi) và (offer A, offer B, nên ghép hay không), tối thiểu 40 ca cho laptop và 15 ca cho mỗi nhóm phụ kiện.
