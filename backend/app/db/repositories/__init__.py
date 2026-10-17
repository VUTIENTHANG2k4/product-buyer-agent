"""Repository truy cập PostgreSQL (docs/04 §3, docs/03 §4).

Quy ước: nhận `Session` qua `__init__`; chỉ `flush`, không `commit` (service/pipeline giữ
transaction); thời gian truyền vào qua `now` (UTC) để test dùng đồng hồ cố định.
"""

from app.db.repositories.agent_runs import AgentRunRepository
from app.db.repositories.caches import LiveSearchCacheRepository, LlmExtractionCacheRepository
from app.db.repositories.conversations import ConversationRepository, MessageRepository
from app.db.repositories.offers import OfferRepository, OfferUpsert, UpsertResult, effective_price
from app.db.repositories.price_alerts import PriceAlertRepository
from app.db.repositories.price_history import (
    PriceHistoryRepository,
    PricePoint,
    SnapshotResult,
)
from app.db.repositories.products import (
    ProductHit,
    ProductPage,
    ProductQuery,
    ProductRepository,
)
from app.db.repositories.scrape_runs import ScrapeRunRepository
from app.db.repositories.shopping_lists import ShoppingListRepository

__all__ = [
    "AgentRunRepository",
    "ConversationRepository",
    "LiveSearchCacheRepository",
    "LlmExtractionCacheRepository",
    "MessageRepository",
    "OfferRepository",
    "OfferUpsert",
    "PriceAlertRepository",
    "PriceHistoryRepository",
    "PricePoint",
    "ProductHit",
    "ProductPage",
    "ProductQuery",
    "ProductRepository",
    "ScrapeRunRepository",
    "ShoppingListRepository",
    "SnapshotResult",
    "UpsertResult",
    "effective_price",
]
