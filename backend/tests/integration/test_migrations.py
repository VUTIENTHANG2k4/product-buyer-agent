"""Migration Alembic trên PostgreSQL rỗng (docs/04 §3, ADR-0007)."""

import os
import re
import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, Enum, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from tests.db_support import downgrade_to, downgrade_to_base, upgrade_to, upgrade_to_head

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

CONNECT_ARGS = {"connect_timeout": 3}
# Chỉ ràng buộc của schema `public` (bảng hệ thống pg_catalog cũng có ràng buộc loại 'u').
_PUBLIC_CONSTRAINTS = (
    "SELECT c.conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
    " WHERE n.nspname = 'public' AND c.contype = '{kind}'"
)


@pytest.fixture
def empty_engine(db_engine: Engine) -> Iterator[Engine]:
    """Engine tới một database tạm hoàn toàn rỗng (tạo và xóa trong cùng test)."""
    admin_url = make_url(os.environ["TEST_DATABASE_URL"]).set(database="postgres")
    name = f"product_buyer_migrate_{uuid.uuid4().hex[:8]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args=CONNECT_ARGS)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(admin_url.set(database=name), connect_args=CONNECT_ARGS)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_engine(empty_engine: Engine) -> Engine:
    upgrade_to_head(empty_engine)
    return empty_engine


def _scalars(engine: Engine, sql: str) -> list[str]:
    with engine.connect() as connection:
        return [row[0] for row in connection.execute(text(sql))]


def test_upgrade_head_on_empty_database_creates_every_table(empty_engine: Engine) -> None:
    assert inspect(empty_engine).get_table_names() == []
    upgrade_to_head(empty_engine)
    assert set(inspect(empty_engine).get_table_names()) == TABLES | {"alembic_version"}


def test_upgrade_head_twice_is_a_no_op(migrated_engine: Engine) -> None:
    upgrade_to_head(migrated_engine)
    assert _scalars(migrated_engine, "SELECT version_num FROM alembic_version") == ["0005"]


def test_downgrade_base_removes_every_table_and_upgrade_restores_them(
    migrated_engine: Engine,
) -> None:
    downgrade_to_base(migrated_engine)
    assert set(inspect(migrated_engine).get_table_names()) <= {"alembic_version"}
    upgrade_to_head(migrated_engine)
    assert set(inspect(migrated_engine).get_table_names()) == TABLES | {"alembic_version"}


def test_models_and_migration_describe_the_same_schema(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, SQLModel.metadata)
    assert differences == []


def test_expected_indexes_exist(migrated_engine: Engine) -> None:
    definitions = {
        name: definition
        for name, definition in zip(
            _scalars(migrated_engine, "SELECT indexname FROM pg_indexes WHERE schemaname='public'"),
            _scalars(migrated_engine, "SELECT indexdef FROM pg_indexes WHERE schemaname='public'"),
            strict=True,
        )
    }
    assert "USING gin (specs)" in definitions["ix_product_specs_gin"]
    unique = definitions["uq_product_category_brand_model_code"]
    assert unique.startswith("CREATE UNIQUE INDEX")
    assert "(category, brand, model_code)" in unique
    assert "WHERE (model_code IS NOT NULL)" in unique
    assert {
        "ix_product_category",
        "ix_offer_product_id",
        "ix_offer_site_is_active",
        "ix_price_history_offer_id_scraped_at",
        "ix_scrape_run_site_category_started_at",
        "ix_price_alert_product_id_status",
        "ix_message_conversation_id_created_at",
        "ix_agent_run_conversation_id",
    } <= set(definitions)


def test_expected_unique_constraints_exist(migrated_engine: Engine) -> None:
    uniques = set(_scalars(migrated_engine, _PUBLIC_CONSTRAINTS.format(kind="u")))
    assert uniques == {"uq_offer_url", "uq_shopping_list_item_list_id_product_id"}


def test_column_types_follow_adr_0007(migrated_engine: Engine) -> None:
    columns = {
        (table, column): (data_type, length)
        for table, column, data_type, length in _rows(
            migrated_engine,
            "SELECT table_name, column_name, data_type, character_maximum_length"
            " FROM information_schema.columns WHERE table_schema = 'public'",
        )
    }
    assert columns[("offer", "price")][0] == "bigint"
    assert columns[("price_alert", "target_price")][0] == "bigint"
    assert columns[("product", "specs")][0] == "jsonb"
    assert columns[("agent_run", "events")][0] == "jsonb"
    assert columns[("agent_run", "id")][0] == "uuid"
    assert columns[("offer", "scraped_at")][0] == "timestamp with time zone"
    assert columns[("offer", "site")] == ("character varying", 32)
    # Không có kiểu ENUM gốc của PostgreSQL ở bất kỳ cột nào.
    assert [key for key, (kind, _) in columns.items() if kind == "USER-DEFINED"] == []
    assert _scalars(migrated_engine, "SELECT typname FROM pg_type WHERE typtype = 'e'") == []


def test_enum_check_constraints_exist_for_every_enum_column(migrated_engine: Engine) -> None:
    checks = set(_scalars(migrated_engine, _PUBLIC_CONSTRAINTS.format(kind="c")))
    assert {
        "ck_product_category",
        "ck_offer_site",
        "ck_offer_price_type",
        "ck_offer_stock_status",
        "ck_offer_match_method",
        "ck_price_history_price_type",
        "ck_price_history_stock_status",
        "ck_scrape_run_site",
        "ck_scrape_run_category",
        "ck_scrape_run_status",
        "ck_scrape_run_trigger",
        "ck_price_alert_channel",
        "ck_price_alert_status",
        "ck_message_role",
        "ck_agent_run_status",
        "ck_llm_extraction_cache_category",
    } <= checks


def _rows(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def _enum_columns() -> list[tuple[str, str, type]]:
    return [
        (table.name, column.name, column.type.enum_class)
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum) and column.type.enum_class is not None
    ]


def test_every_enum_column_was_found() -> None:
    assert len(_enum_columns()) == 16


@pytest.mark.parametrize(("table", "column", "enum_cls"), _enum_columns())
def test_database_check_lists_exactly_the_values_of_the_code_enum(
    migrated_engine: Engine, table: str, column: str, enum_cls: type
) -> None:
    """Alembic không so CHECK nên migration viết tay có thể lệch enum trong code: bắt ở đây."""
    with migrated_engine.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = :name AND conrelid = CAST(:table AS regclass)"
            ),
            {"name": f"ck_{table}_{column}", "table": table},
        ).scalar_one()
    assert set(re.findall(r"'([^']*)'", definition)) == {member.value for member in enum_cls}


_INSERT_RUN = (
    "INSERT INTO scrape_run (site, category, status, trigger, pages_fetched, items_parsed,"
    " items_failed, offers_upserted, price_changes)"
    " VALUES (:site, 'laptop', 'SUCCEEDED', 'test', 1, 1, 0, 1, 0)"
)


def _insert_run(engine: Engine, site: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(_INSERT_RUN), {"site": site})


def test_0002_keeps_old_rows_and_accepts_the_new_sites(empty_engine: Engine) -> None:
    upgrade_to(empty_engine, "0001")
    _insert_run(empty_engine, "hoangha")
    with pytest.raises(IntegrityError):
        _insert_run(empty_engine, "fptshop")

    upgrade_to(empty_engine, "0002")

    _insert_run(empty_engine, "fptshop")
    _insert_run(empty_engine, "anphat")
    sites = _scalars(empty_engine, "SELECT site FROM scrape_run ORDER BY id")
    assert sites == ["hoangha", "fptshop", "anphat"]
    with pytest.raises(IntegrityError):
        _insert_run(empty_engine, "shopee")


def test_0002_downgrade_restores_the_six_site_list(migrated_engine: Engine) -> None:
    downgrade_to(migrated_engine, "0001")

    _insert_run(migrated_engine, "laptop88")
    with pytest.raises(IntegrityError):
        _insert_run(migrated_engine, "anphat")
    upgrade_to_head(migrated_engine)
    _insert_run(migrated_engine, "anphat")
