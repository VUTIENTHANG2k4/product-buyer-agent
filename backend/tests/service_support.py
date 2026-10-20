"""Hàm dùng chung cho test service: dựng sản phẩm/offer trong session test và đồng hồ cố định."""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.config import Settings
from app.db.models import Offer, Product
from tests.factories import make_offer, make_product

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:5432/x",
        "scraper_user_agent": "test-agent/0.1",
        "alert_default_email": "mock@example.com",
        "telegram_chat_id": "",
    }
    return Settings.model_validate({**base, **overrides})


def add_product(session: Session, **overrides: Any) -> Product:
    product = make_product(**overrides)
    session.add(product)
    session.flush()
    return product


def add_offer(session: Session, product: Product, **overrides: Any) -> Offer:
    assert product.id is not None
    overrides.setdefault("scraped_at", NOW)
    offer = make_offer(product.id, **overrides)
    session.add(offer)
    session.flush()
    return offer
