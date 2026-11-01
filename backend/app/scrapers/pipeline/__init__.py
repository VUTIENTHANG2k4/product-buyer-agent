"""Pipeline thu thập: scraper → chuẩn hóa → repository (docs/06 §7, docs/03 §5.2).

Đây là gói duy nhất trong `app/scrapers` được import `app.db`. Pipeline sở hữu transaction: mỗi
trang danh sách được lưu trong một transaction, từng mục trong một savepoint để lỗi lưu một mục chỉ
tính vào `items_failed`. Repository đồng bộ nên mọi thao tác CSDL chạy qua `asyncio.to_thread`.
Pipeline KHÔNG gọi `app.services`; đánh giá cảnh báo giá do `scrape_service` làm với kết quả trả về.

Gắn offer vào `Product` (`resolve_product`): offer đã có giữ nguyên sản phẩm của nó (chạy lại không
nhân đôi); offer mới được trích thông số theo luật rồi ghép bằng `model_code` hoặc tên
(`normalize.matcher`), không ghép được thì tạo `Product` mới.

Gói: `state` (hằng số, kết quả, trạng thái lượt), `resolve` (gắn offer vào product), `writer`
(`OfferWriter`: lưu offer/lịch sử giá), `run_store` (`RunStore`: vòng đời `ScrapeRun`), `core`
(`ScrapePipeline`: điều phối). Nơi khác chỉ import từ `app.scrapers.pipeline`
(test được vào module con).
"""

from app.scrapers.pipeline.core import ScrapePipeline
from app.scrapers.pipeline.resolve import (
    ProductResolver,
    Resolution,
    find_existing_offer,
    make_resolver,
    resolve_product,
)
from app.scrapers.pipeline.state import (
    BLOCK_COOLDOWN,
    CANCELLED_BY_USER,
    NEEDS_HUMAN_STALE_AFTER,
    RUNNING_STALE_AFTER,
    PipelineResult,
    SessionFactory,
    StartedRun,
)

__all__ = [
    "BLOCK_COOLDOWN",
    "CANCELLED_BY_USER",
    "NEEDS_HUMAN_STALE_AFTER",
    "PipelineResult",
    "ProductResolver",
    "RUNNING_STALE_AFTER",
    "Resolution",
    "ScrapePipeline",
    "SessionFactory",
    "StartedRun",
    "find_existing_offer",
    "make_resolver",
    "resolve_product",
]
