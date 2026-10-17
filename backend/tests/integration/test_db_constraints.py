"""Ràng buộc, kiểu cột và hành vi của model DB trên PostgreSQL thật (docs/04 §3, ADR-0007)."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app.db.models import (
    LiveSearchCache,
    LlmExtractionCache,
    Product,
)
from app.domain.enums import (
    AlertStatus,
    Category,
    PriceType,
    ScrapeStatus,
    SiteKey,
    StockStatus,
)
from tests.factories import (
    make_agent_run,
    make_conversation,
    make_message,
    make_offer,
    make_price_alert,
    make_price_history,
    make_product,
    make_scrape_run,
    make_shopping_list,
    make_shopping_list_item,
)


def _save(session: Session, *objects: SQLModel) -> None:
    session.add_all(objects)
    session.flush()


def _count(session: Session, table: str, where: str = "TRUE") -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar_one())


@pytest.fixture
def parents(db_session: Session) -> dict[str, Any]:
    """Một bản ghi cha đã lưu cho mỗi quan hệ khóa ngoại."""
    product = make_product()
    shopping_list = make_shopping_list()
    conversation = make_conversation()
    _save(db_session, product, shopping_list, conversation)
    assert product.id is not None
    offer = make_offer(product.id)
    _save(db_session, offer)
    return {
        "product": product,
        "offer": offer,
        "shopping_list": shopping_list,
        "conversation": conversation,
    }


# --- UNIQUE và chỉ mục một phần --------------------------------------------------------------


def test_offer_url_must_be_unique(db_session: Session, parents: dict[str, Any]) -> None:
    url = parents["offer"].url
    with pytest.raises(IntegrityError, match="uq_offer_url"), db_session.begin_nested():
        _save(db_session, make_offer(parents["product"].id, url=url))


def test_product_model_code_is_unique_per_category_and_brand(db_session: Session) -> None:
    _save(db_session, make_product(brand="MockA", model_code="DUP-1"))
    with (
        pytest.raises(IntegrityError, match="uq_product_category_brand_model_code"),
        db_session.begin_nested(),
    ):
        _save(db_session, make_product(brand="MockA", model_code="DUP-1"))


def test_same_model_code_is_allowed_for_other_brand_or_category(db_session: Session) -> None:
    _save(
        db_session,
        make_product(brand="MockA", model_code="SAME-1"),
        make_product(brand="MockB", model_code="SAME-1"),
        make_product(brand="MockA", model_code="SAME-1", category=Category.mouse),
    )
    assert _count(db_session, "product", "model_code = 'SAME-1'") == 3


def test_products_without_model_code_never_conflict(db_session: Session) -> None:
    _save(
        db_session,
        make_product(brand="MockA", model_code=None),
        make_product(brand="MockA", model_code=None),
    )
    assert _count(db_session, "product", "model_code IS NULL") == 2


def test_shopping_list_item_is_unique_per_list_and_product(
    db_session: Session, parents: dict[str, Any]
) -> None:
    list_id, product_id = parents["shopping_list"].id, parents["product"].id
    _save(db_session, make_shopping_list_item(list_id, product_id))
    with (
        pytest.raises(IntegrityError, match="uq_shopping_list_item_list_id_product_id"),
        db_session.begin_nested(),
    ):
        _save(db_session, make_shopping_list_item(list_id, product_id))


# --- CHECK: enum -----------------------------------------------------------------------------

ENUM_COLUMNS = [
    ("product", "category"),
    ("offer", "site"),
    ("offer", "price_type"),
    ("offer", "stock_status"),
    ("offer", "match_method"),
    ("price_history", "price_type"),
    ("price_history", "stock_status"),
    ("scrape_run", "site"),
    ("scrape_run", "category"),
    ("scrape_run", "status"),
    ("scrape_run", "trigger"),
    ("price_alert", "channel"),
    ("price_alert", "status"),
    ("message", "role"),
    ("agent_run", "status"),
    ("llm_extraction_cache", "category"),
]


@pytest.fixture
def one_row_per_enum_table(db_session: Session, parents: dict[str, Any]) -> None:
    product_id = parents["product"].id
    conversation_id = parents["conversation"].id
    _save(
        db_session,
        make_price_history(parents["offer"].id),
        make_scrape_run(),
        make_price_alert(product_id),
        make_message(conversation_id),
        make_agent_run(conversation_id),
        LlmExtractionCache(content_hash="a" * 64, category=Category.laptop, model="mock"),
    )


@pytest.mark.parametrize(("table", "column"), ENUM_COLUMNS)
@pytest.mark.usefixtures("one_row_per_enum_table")
def test_database_rejects_unknown_enum_value(db_session: Session, table: str, column: str) -> None:
    with pytest.raises(IntegrityError, match=f"ck_{table}_{column}"), db_session.begin_nested():
        db_session.execute(text(f"UPDATE {table} SET {column} = 'bogus'"))


def test_enum_columns_store_plain_strings_and_load_members(db_session: Session) -> None:
    run = make_scrape_run(status=ScrapeStatus.NEEDS_HUMAN, site=SiteKey.gearvn)
    _save(db_session, run)
    stored = db_session.execute(
        text("SELECT status, site FROM scrape_run WHERE id = :id"), {"id": run.id}
    ).one()
    assert tuple(stored) == ("NEEDS_HUMAN", "gearvn")
    db_session.expire(run)
    assert run.status is ScrapeStatus.NEEDS_HUMAN
    assert run.site is SiteKey.gearvn


# --- CHECK: số -------------------------------------------------------------------------------


Builder = Callable[[dict[str, Any]], list[SQLModel]]


def _offer(**fields: Any) -> Builder:
    return lambda p: [make_offer(p["product"].id, **fields)]


def _history(**fields: Any) -> Builder:
    return lambda p: [make_price_history(p["offer"].id, **fields)]


def _item(**fields: Any) -> Builder:
    return lambda p: [make_shopping_list_item(p["shopping_list"].id, p["product"].id, **fields)]


def _alert(**fields: Any) -> Builder:
    return lambda p: [make_price_alert(p["product"].id, **fields)]


def _run(**fields: Any) -> Builder:
    return lambda p: [make_scrape_run(**fields)]


def _agent_run(**fields: Any) -> Builder:
    return lambda p: [make_agent_run(p["conversation"].id, **fields)]


def _product(**fields: Any) -> Builder:
    return lambda p: [make_product(**fields)]


# (đối tượng vi phạm, tên ràng buộc phải báo lỗi): mỗi CHECK số của docs/04 §3 có một ca.
OUT_OF_RANGE = [
    (_offer(price=-1), "ck_offer_price_non_negative"),
    (_offer(list_price=-1), "ck_offer_list_price_non_negative"),
    (_offer(rating=5.1), "ck_offer_rating_range"),
    (_offer(rating=-0.1), "ck_offer_rating_range"),
    (_offer(rating_count=-1), "ck_offer_rating_count"),
    (_offer(match_score=1.5), "ck_offer_match_score"),
    (_product(specs_confidence=1.5), "ck_product_specs_confidence"),
    (_product(specs_confidence=-0.1), "ck_product_specs_confidence"),
    (_history(price=-5), "ck_price_history_price_non_negative"),
    (_item(quantity=0), "ck_shopping_list_item_quantity_positive"),
    (_item(price_at_add=-1), "ck_shopping_list_item_price_at_add"),
    (_alert(target_price=0), "ck_price_alert_target_price_positive"),
    (_alert(last_notified_price=-1), "ck_price_alert_last_notified_price"),
    (_run(pages_fetched=-1), "ck_scrape_run_counters_non_negative"),
    (_run(price_changes=-1), "ck_scrape_run_counters_non_negative"),
    (_agent_run(tool_calls=-1), "ck_agent_run_tool_calls"),
    (_agent_run(latency_ms=-1), "ck_agent_run_latency_ms"),
]

# Giá trị biên hợp lệ: ràng buộc không được chặt hơn docs.
BOUNDARY_OK = [
    _offer(price=0, list_price=0, rating=0, rating_count=0, match_score=0),
    _offer(rating=5, match_score=1),
    _product(specs_confidence=0),
    _product(specs_confidence=1),
    _history(price=0),
    _item(quantity=1, price_at_add=0),
    _alert(target_price=1, last_notified_price=0),
    _run(pages_fetched=0),
    _agent_run(tool_calls=0, latency_ms=0),
]


@pytest.mark.parametrize(("build", "constraint"), OUT_OF_RANGE)
def test_database_rejects_out_of_range_numbers(
    db_session: Session, parents: dict[str, Any], build: Builder, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), db_session.begin_nested():
        _save(db_session, *build(parents))


@pytest.mark.parametrize("build", BOUNDARY_OK)
def test_database_accepts_boundary_numbers(
    db_session: Session, parents: dict[str, Any], build: Builder
) -> None:
    _save(db_session, *build(parents))


def test_prices_beyond_int32_are_stored(db_session: Session, parents: dict[str, Any]) -> None:
    offer = make_offer(parents["product"].id, price=9_000_000_000)
    _save(db_session, offer)
    db_session.expire(offer)
    assert offer.price == 9_000_000_000


# --- Khóa ngoại ------------------------------------------------------------------------------


def test_offer_requires_an_existing_product(db_session: Session) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_offer_product_id_product"),
        db_session.begin_nested(),
    ):
        _save(db_session, make_offer(999_999_999))


def test_deleting_a_shopping_list_deletes_its_items(
    db_session: Session, parents: dict[str, Any]
) -> None:
    list_id = parents["shopping_list"].id
    _save(db_session, make_shopping_list_item(list_id, parents["product"].id))
    db_session.execute(text("DELETE FROM shopping_list WHERE id = :id"), {"id": list_id})
    assert _count(db_session, "shopping_list_item") == 0


def test_deleting_an_offer_deletes_its_price_history(
    db_session: Session, parents: dict[str, Any]
) -> None:
    offer_id = parents["offer"].id
    _save(db_session, make_price_history(offer_id))
    db_session.execute(text("DELETE FROM offer WHERE id = :id"), {"id": offer_id})
    assert _count(db_session, "price_history") == 0


def test_deleting_the_preferred_offer_clears_the_reference(
    db_session: Session, parents: dict[str, Any]
) -> None:
    item = make_shopping_list_item(
        parents["shopping_list"].id, parents["product"].id, preferred_offer_id=parents["offer"].id
    )
    _save(db_session, item)
    db_session.execute(text("DELETE FROM offer WHERE id = :id"), {"id": parents["offer"].id})
    assert _count(db_session, "shopping_list_item", "preferred_offer_id IS NULL") == 1


def test_product_with_offers_cannot_be_deleted(
    db_session: Session, parents: dict[str, Any]
) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_offer_product_id_product"),
        db_session.begin_nested(),
    ):
        db_session.execute(
            text("DELETE FROM product WHERE id = :id"), {"id": parents["product"].id}
        )


def test_product_in_a_shopping_list_cannot_be_deleted(db_session: Session) -> None:
    product, shopping_list = make_product(), make_shopping_list()
    _save(db_session, product, shopping_list)
    assert product.id is not None and shopping_list.id is not None
    _save(db_session, make_shopping_list_item(shopping_list.id, product.id))
    with (
        pytest.raises(IntegrityError, match="fk_shopping_list_item_product_id_product"),
        db_session.begin_nested(),
    ):
        db_session.execute(text("DELETE FROM product WHERE id = :id"), {"id": product.id})


def test_deleting_a_product_deletes_its_alerts(db_session: Session) -> None:
    product = make_product()
    _save(db_session, product)
    assert product.id is not None
    _save(db_session, make_price_alert(product.id))
    db_session.execute(text("DELETE FROM product WHERE id = :id"), {"id": product.id})
    assert _count(db_session, "price_alert") == 0


def test_deleting_a_conversation_deletes_messages_and_runs(
    db_session: Session, parents: dict[str, Any]
) -> None:
    conversation_id = parents["conversation"].id
    _save(db_session, make_message(conversation_id), make_agent_run(conversation_id))
    db_session.execute(text("DELETE FROM conversation WHERE id = :id"), {"id": conversation_id})
    assert _count(db_session, "message") == 0
    assert _count(db_session, "agent_run") == 0


# --- Kiểu dữ liệu và mặc định ----------------------------------------------------------------


def test_agent_run_gets_a_uuid_primary_key(db_session: Session, parents: dict[str, Any]) -> None:
    run = make_agent_run(parents["conversation"].id)
    _save(db_session, run)
    db_session.expire(run)
    assert isinstance(run.id, uuid.UUID)
    assert run.events == []
    assert run.tool_calls == 0


def test_defaults_are_applied(db_session: Session, parents: dict[str, Any]) -> None:
    offer = parents["offer"]
    alert = make_price_alert(parents["product"].id)
    _save(db_session, alert)
    assert (offer.price_type, offer.stock_status) == (PriceType.unknown, StockStatus.unknown)
    assert offer.is_active is True
    assert alert.status is AlertStatus.active
    assert parents["product"].specs_confidence == 1.0


def test_json_and_time_defaults_exist_in_the_database_for_raw_inserts(
    db_session: Session,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO product (category, brand, canonical_name, specs_confidence)"
            " VALUES ('laptop', 'MockRaw', 'Mock Raw', 1)"
        )
    )
    row = db_session.execute(
        text("SELECT specs, created_at FROM product WHERE brand = 'MockRaw'")
    ).one()
    assert row.specs == {}
    assert row.created_at.tzinfo is not None


def test_timestamps_are_timezone_aware_utc(db_session: Session, parents: dict[str, Any]) -> None:
    product = parents["product"]
    db_session.expire(product)
    assert product.created_at.tzinfo is not None
    assert product.created_at.utcoffset() == timedelta(0)


def test_created_at_uses_python_clock_and_updated_at_follows_updates(
    db_session: Session,
) -> None:
    first = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    later = first + timedelta(days=2)
    with time_machine.travel(first, tick=False):
        product = make_product()
        _save(db_session, product)
    assert product.created_at == first
    assert product.updated_at == first
    with time_machine.travel(later, tick=False):
        product.canonical_name = "Mock đổi tên"
        db_session.flush()
    assert product.created_at == first
    assert product.updated_at == later


def test_none_json_value_is_stored_as_sql_null(db_session: Session) -> None:
    _save(
        db_session,
        make_scrape_run(challenge=None),
        make_scrape_run(challenge={"kind": "captcha"}),
    )
    assert _count(db_session, "scrape_run", "challenge IS NULL") == 1
    assert _count(db_session, "scrape_run", "challenge IS NOT NULL") == 1


def test_json_columns_round_trip_structures(db_session: Session, parents: dict[str, Any]) -> None:
    message = make_message(parents["conversation"].id, payload={"product_ids": [12, 31]})
    cache = LiveSearchCache(cache_key="mock-key", results=[{"title": "Mock", "price": 1}])
    _save(db_session, message, cache)
    db_session.expire_all()
    assert message.payload == {"product_ids": [12, 31]}
    assert cache.results == [{"title": "Mock", "price": 1}]


# --- Lọc theo thông số JSONB (đường dẫn cho repository ở T1.4) -------------------------------


def test_spec_filter_uses_jsonb_operators(db_session: Session) -> None:
    slow = make_product(specs={"gpu_rank": 30, "is_gaming": False, "tag": "mock-filter"})
    mid = make_product(specs={"gpu_rank": 40, "is_gaming": True, "tag": "mock-filter"})
    fast = make_product(specs={"gpu_rank": 50, "is_gaming": True, "tag": "mock-filter"})
    _save(db_session, slow, mid, fast)

    at_least_40 = select(Product.id).where(
        Product.specs["gpu_rank"].as_integer() >= 40,
        Product.specs["tag"].as_string() == "mock-filter",
    )
    assert set(db_session.exec(at_least_40)) == {mid.id, fast.id}

    gaming_only = select(Product.id).where(
        Product.specs["is_gaming"].as_boolean(), Product.specs["tag"].as_string() == "mock-filter"
    )
    assert set(db_session.exec(gaming_only)) == {mid.id, fast.id}

    contains = select(Product.id).where(Product.specs.contains({"gpu_rank": 30}))
    assert set(db_session.exec(contains)) == {slow.id}
