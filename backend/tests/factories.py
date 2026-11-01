"""Factory dựng model DB với giá trị mặc định hợp lệ (docs/09 §3).

Trả về đối tượng chưa lưu; test tự `session.add(...)` và `session.flush()`. Dữ liệu là hư cấu
(tên có chữ "Mock") và mỗi lần gọi sinh `url`/`model_code` khác nhau để không đụng ràng buộc UNIQUE.
"""

from itertools import count
from typing import Any

from app.db.models import (
    AgentRun,
    Conversation,
    Message,
    Offer,
    PriceAlert,
    PriceHistory,
    Product,
    ScrapeRun,
    ShoppingList,
    ShoppingListItem,
)
from app.domain.enums import (
    AlertChannel,
    Category,
    MessageRole,
    ScrapeTrigger,
    SiteKey,
)

_sequence = count(1)


def make_product(**overrides: Any) -> Product:
    n = next(_sequence)
    data: dict[str, Any] = {
        "category": Category.laptop,
        "brand": "MockBrand",
        "model_code": f"MOCK-{n:04d}",
        "canonical_name": f"MockBrand Mock Laptop {n}",
        "specs": {"gpu_rank": 40, "ram_gb": 16, "is_gaming": True},
    }
    data.update(overrides)
    return Product(**data)


def make_offer(product_id: int, **overrides: Any) -> Offer:
    n = next(_sequence)
    data: dict[str, Any] = {
        "product_id": product_id,
        "site": SiteKey.mockshop,
        "url": f"https://mock.example/p/mock-laptop-{n}",
        "title": f"Mock Laptop {n}",
        "price": 27_490_000,
    }
    data.update(overrides)
    return Offer(**data)


def make_price_history(offer_id: int, **overrides: Any) -> PriceHistory:
    data: dict[str, Any] = {"offer_id": offer_id, "price": 27_490_000}
    data.update(overrides)
    return PriceHistory(**data)


def make_scrape_run(**overrides: Any) -> ScrapeRun:
    data: dict[str, Any] = {
        "site": SiteKey.mockshop,
        "category": Category.laptop,
        "trigger": ScrapeTrigger.test,
    }
    data.update(overrides)
    return ScrapeRun(**data)


def make_shopping_list(**overrides: Any) -> ShoppingList:
    data: dict[str, Any] = {"name": "Mock danh sách mua"}
    data.update(overrides)
    return ShoppingList(**data)


def make_shopping_list_item(list_id: int, product_id: int, **overrides: Any) -> ShoppingListItem:
    data: dict[str, Any] = {"list_id": list_id, "product_id": product_id}
    data.update(overrides)
    return ShoppingListItem(**data)


def make_price_alert(product_id: int, **overrides: Any) -> PriceAlert:
    data: dict[str, Any] = {
        "product_id": product_id,
        "target_price": 25_000_000,
        "channel": AlertChannel.email,
        "destination": "mock@example.com",
    }
    data.update(overrides)
    return PriceAlert(**data)


def make_conversation(**overrides: Any) -> Conversation:
    data: dict[str, Any] = {"title": "Mock hội thoại"}
    data.update(overrides)
    return Conversation(**data)


def make_message(conversation_id: int, **overrides: Any) -> Message:
    data: dict[str, Any] = {
        "conversation_id": conversation_id,
        "role": MessageRole.user,
        "content": "tìm laptop gaming dưới 30 triệu",
    }
    data.update(overrides)
    return Message(**data)


def make_agent_run(conversation_id: int, **overrides: Any) -> AgentRun:
    data: dict[str, Any] = {"conversation_id": conversation_id}
    data.update(overrides)
    return AgentRun(**data)
