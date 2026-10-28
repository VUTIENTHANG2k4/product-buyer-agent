"""Model DB (app/db/models.py): hình dạng schema theo docs/04 §2–3, không cần kết nối DB."""

from datetime import UTC

import pytest
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel

from app.db import models
from app.domain import enums

TABLES = {
    "product",
    "offer",
    "price_history",
    "scrape_run",
    "shopping_list",
    "shopping_list_item",
    "price_alert",
    "conversation",
    "message",
    "agent_run",
    "llm_extraction_cache",
    "live_search_cache",
    "domain_throttle",
}

# (bảng, cột) → enum miền: cột lưu VARCHAR(32) và có CHECK tên ck_<bảng>_<cột>.
ENUM_COLUMNS = {
    ("product", "category"): enums.Category,
    ("offer", "site"): enums.SiteKey,
    ("offer", "price_type"): enums.PriceType,
    ("offer", "stock_status"): enums.StockStatus,
    ("offer", "match_method"): enums.MatchMethod,
    ("price_history", "price_type"): enums.PriceType,
    ("price_history", "stock_status"): enums.StockStatus,
    ("scrape_run", "site"): enums.SiteKey,
    ("scrape_run", "category"): enums.Category,
    ("scrape_run", "status"): enums.ScrapeStatus,
    ("scrape_run", "trigger"): enums.ScrapeTrigger,
    ("price_alert", "channel"): enums.AlertChannel,
    ("price_alert", "status"): enums.AlertStatus,
    ("message", "role"): enums.MessageRole,
    ("agent_run", "status"): enums.AgentRunStatus,
    ("llm_extraction_cache", "category"): enums.Category,
}

MONEY_COLUMNS = [
    ("offer", "price"),
    ("offer", "list_price"),
    ("price_history", "price"),
    ("shopping_list_item", "price_at_add"),
    ("price_alert", "target_price"),
    ("price_alert", "last_notified_price"),
]

JSONB_COLUMNS = [
    ("product", "specs"),
    ("offer", "raw_specs"),
    ("scrape_run", "challenge"),
    ("message", "payload"),
    ("agent_run", "intent"),
    ("agent_run", "events"),
    ("llm_extraction_cache", "result"),
    ("live_search_cache", "results"),
]

TIMESTAMP_COLUMNS = [
    (table.name, column.name)
    for table in SQLModel.metadata.tables.values()
    for column in table.columns
    if column.name.endswith("_at")
]


def _table(name: str) -> Table:
    return SQLModel.metadata.tables[name]


def test_metadata_has_exactly_the_documented_tables() -> None:
    assert set(SQLModel.metadata.tables) == TABLES


@pytest.mark.parametrize(("table", "column"), sorted(ENUM_COLUMNS))
def test_enum_column_is_varchar_without_native_enum(table: str, column: str) -> None:
    column_type = _table(table).c[column].type
    assert isinstance(column_type, Enum)
    assert column_type.native_enum is False
    assert column_type.length == 32


@pytest.mark.parametrize(("table", "column"), sorted(ENUM_COLUMNS))
def test_enum_column_has_named_check_listing_every_enum_value(table: str, column: str) -> None:
    checks = {
        c.name: str(c.sqltext)
        for c in _table(table).constraints
        if isinstance(c, CheckConstraint) and c.name is not None
    }
    sqltext = checks[f"ck_{table}_{column}"]
    for member in ENUM_COLUMNS[(table, column)]:
        assert f"'{member.value}'" in sqltext
    assert sqltext.count("'") == 2 * len(ENUM_COLUMNS[(table, column)])


@pytest.mark.parametrize(("table", "column"), MONEY_COLUMNS)
def test_money_column_is_bigint(table: str, column: str) -> None:
    assert isinstance(_table(table).c[column].type, BigInteger)


def test_offer_price_is_required_but_list_price_is_optional() -> None:
    offer = _table("offer")
    assert offer.c.price.nullable is False
    assert offer.c.list_price.nullable is True


@pytest.mark.parametrize(("table", "column"), JSONB_COLUMNS)
def test_json_column_is_jsonb(table: str, column: str) -> None:
    assert isinstance(_table(table).c[column].type, JSONB)


@pytest.mark.parametrize(("table", "column"), TIMESTAMP_COLUMNS)
def test_every_timestamp_column_has_timezone(table: str, column: str) -> None:
    column_type = _table(table).c[column].type
    assert isinstance(column_type, DateTime)
    assert column_type.timezone is True


def test_all_timestamp_columns_were_found() -> None:
    assert len(TIMESTAMP_COLUMNS) == 18


def test_every_constraint_and_index_has_an_explicit_or_conventional_name() -> None:
    for table in SQLModel.metadata.tables.values():
        for constraint in table.constraints:
            assert constraint.name is not None, f"{table.name}: ràng buộc không tên {constraint}"
        for index in table.indexes:
            assert index.name is not None, f"{table.name}: chỉ mục không tên"


def test_product_indexes_match_docs() -> None:
    indexes = {index.name: index for index in _table("product").indexes}
    assert set(indexes) == {
        "ix_product_category",
        "ix_product_specs_gin",
        "uq_product_category_brand_model_code",
    }
    gin = indexes["ix_product_specs_gin"]
    assert gin.dialect_options["postgresql"]["using"] == "gin"
    unique = indexes["uq_product_category_brand_model_code"]
    assert unique.unique is True
    assert [c.name for c in unique.columns] == ["category", "brand", "model_code"]
    assert str(unique.dialect_options["postgresql"]["where"]) == "model_code IS NOT NULL"


def test_agent_run_primary_key_is_uuid() -> None:
    assert _table("agent_run").c.id.type.python_type.__name__ == "UUID"


def test_utc_now_returns_aware_utc_datetime() -> None:
    now = models.utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(None)
