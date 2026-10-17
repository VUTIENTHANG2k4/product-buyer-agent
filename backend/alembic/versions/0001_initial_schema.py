"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-17 16:51:05.700848

Sinh bằng autogenerate rồi chỉnh tay: cột enum là `VARCHAR(32)` + `CHECK` có tên (không dùng
`sa.Enum`), vì Alembic không so sánh CHECK nên migration là nguồn sự thật của danh sách giá trị.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "conversation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
    )
    op.create_table(
        "live_search_cache",
        sa.Column("cache_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_live_search_cache")),
    )
    op.create_table(
        "llm_extraction_cache",
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('laptop', 'mouse', 'keyboard', 'headset', 'phone', 'other')",
            name=op.f("ck_llm_extraction_cache_category"),
        ),
        sa.PrimaryKeyConstraint("content_hash", name=op.f("pk_llm_extraction_cache")),
    )
    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("brand", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("canonical_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "specs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("specs_confidence", sa.Float(), nullable=False),
        sa.Column("image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('laptop', 'mouse', 'keyboard', 'headset', 'phone', 'other')",
            name=op.f("ck_product_category"),
        ),
        sa.CheckConstraint(
            "specs_confidence >= 0 AND specs_confidence <= 1",
            name=op.f("ck_product_specs_confidence"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
    )
    op.create_index("ix_product_category", "product", ["category"], unique=False)
    op.create_index(
        "ix_product_specs_gin", "product", ["specs"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "uq_product_category_brand_model_code",
        "product",
        ["category", "brand", "model_code"],
        unique=True,
        postgresql_where=sa.text("model_code IS NOT NULL"),
    )
    op.create_table(
        "scrape_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "site",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("items_parsed", sa.Integer(), nullable=False),
        sa.Column("items_failed", sa.Integer(), nullable=False),
        sa.Column("offers_upserted", sa.Integer(), nullable=False),
        sa.Column("price_changes", sa.Integer(), nullable=False),
        sa.Column(
            "challenge", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('laptop', 'mouse', 'keyboard', 'headset', 'phone', 'other')",
            name=op.f("ck_scrape_run_category"),
        ),
        sa.CheckConstraint(
            "site IN ('gearvn', 'hoangha', 'laptop88', 'viettelstore', 'nguyenkim', 'mockshop')",
            name=op.f("ck_scrape_run_site"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'NEEDS_HUMAN', 'BLOCKED', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name=op.f("ck_scrape_run_status"),
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'tracked_refresh', 'test')",
            name=op.f("ck_scrape_run_trigger"),
        ),
        sa.CheckConstraint(
            "pages_fetched >= 0 AND items_parsed >= 0 AND items_failed >= 0 AND offers_upserted >= 0 AND price_changes >= 0",
            name=op.f("ck_scrape_run_counters_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scrape_run")),
    )
    op.create_index(
        "ix_scrape_run_site_category_started_at",
        "scrape_run",
        ["site", "category", "started_at"],
        unique=False,
    )
    op.create_table(
        "shopping_list",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_list")),
    )
    op.create_table(
        "agent_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "intent", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'needs_clarification', 'failed')",
            name=op.f("ck_agent_run_status"),
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name=op.f("ck_agent_run_latency_ms")
        ),
        sa.CheckConstraint("tool_calls >= 0", name=op.f("ck_agent_run_tool_calls")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_agent_run_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run")),
    )
    op.create_index("ix_agent_run_conversation_id", "agent_run", ["conversation_id"], unique=False)
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_message_role")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_message_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message")),
    )
    op.create_index(
        "ix_message_conversation_id_created_at",
        "message",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "offer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "site",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("site_sku", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("list_price", sa.BigInteger(), nullable=True),
        sa.Column(
            "price_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "stock_status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column(
            "raw_specs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "match_method",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "match_method IN ('model_code', 'fuzzy', 'new')", name=op.f("ck_offer_match_method")
        ),
        sa.CheckConstraint(
            "price_type IN ('regular', 'sale', 'member', 'flash', 'unknown')",
            name=op.f("ck_offer_price_type"),
        ),
        sa.CheckConstraint(
            "site IN ('gearvn', 'hoangha', 'laptop88', 'viettelstore', 'nguyenkim', 'mockshop')",
            name=op.f("ck_offer_site"),
        ),
        sa.CheckConstraint(
            "stock_status IN ('in_stock', 'out_of_stock', 'preorder', 'unknown')",
            name=op.f("ck_offer_stock_status"),
        ),
        sa.CheckConstraint(
            "list_price IS NULL OR list_price >= 0", name=op.f("ck_offer_list_price_non_negative")
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name=op.f("ck_offer_match_score"),
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_offer_price_non_negative")),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 0 AND rating <= 5)", name=op.f("ck_offer_rating_range")
        ),
        sa.CheckConstraint(
            "rating_count IS NULL OR rating_count >= 0", name=op.f("ck_offer_rating_count")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"], name=op.f("fk_offer_product_id_product")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offer")),
        sa.UniqueConstraint("url", name="uq_offer_url"),
    )
    op.create_index("ix_offer_product_id", "offer", ["product_id"], unique=False)
    op.create_index("ix_offer_site_is_active", "offer", ["site", "is_active"], unique=False)
    op.create_table(
        "price_alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("target_price", sa.BigInteger(), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("destination", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("last_notified_price", sa.BigInteger(), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("channel IN ('email', 'telegram')", name=op.f("ck_price_alert_channel")),
        sa.CheckConstraint(
            "status IN ('active', 'triggered', 'paused')", name=op.f("ck_price_alert_status")
        ),
        sa.CheckConstraint(
            "last_notified_price IS NULL OR last_notified_price >= 0",
            name=op.f("ck_price_alert_last_notified_price"),
        ),
        sa.CheckConstraint("target_price > 0", name=op.f("ck_price_alert_target_price_positive")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_price_alert_product_id_product"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_alert")),
    )
    op.create_index(
        "ix_price_alert_product_id_status", "price_alert", ["product_id", "status"], unique=False
    )
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column(
            "price_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "stock_status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "price_type IN ('regular', 'sale', 'member', 'flash', 'unknown')",
            name=op.f("ck_price_history_price_type"),
        ),
        sa.CheckConstraint(
            "stock_status IN ('in_stock', 'out_of_stock', 'preorder', 'unknown')",
            name=op.f("ck_price_history_stock_status"),
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_price_history_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["offer.id"],
            name=op.f("fk_price_history_offer_id_offer"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_history")),
    )
    op.create_index(
        "ix_price_history_offer_id_scraped_at",
        "price_history",
        ["offer_id", "scraped_at"],
        unique=False,
    )
    op.create_table(
        "shopping_list_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("preferred_offer_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_at_add", sa.BigInteger(), nullable=True),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "price_at_add IS NULL OR price_at_add >= 0",
            name=op.f("ck_shopping_list_item_price_at_add"),
        ),
        sa.CheckConstraint("quantity >= 1", name=op.f("ck_shopping_list_item_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_list.id"],
            name=op.f("fk_shopping_list_item_list_id_shopping_list"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preferred_offer_id"],
            ["offer.id"],
            name=op.f("fk_shopping_list_item_preferred_offer_id_offer"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_shopping_list_item_product_id_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_list_item")),
        sa.UniqueConstraint(
            "list_id", "product_id", name="uq_shopping_list_item_list_id_product_id"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("shopping_list_item")
    op.drop_index("ix_price_history_offer_id_scraped_at", table_name="price_history")
    op.drop_table("price_history")
    op.drop_index("ix_price_alert_product_id_status", table_name="price_alert")
    op.drop_table("price_alert")
    op.drop_index("ix_offer_site_is_active", table_name="offer")
    op.drop_index("ix_offer_product_id", table_name="offer")
    op.drop_table("offer")
    op.drop_index("ix_message_conversation_id_created_at", table_name="message")
    op.drop_table("message")
    op.drop_index("ix_agent_run_conversation_id", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_table("shopping_list")
    op.drop_index("ix_scrape_run_site_category_started_at", table_name="scrape_run")
    op.drop_table("scrape_run")
    op.drop_index(
        "uq_product_category_brand_model_code",
        table_name="product",
        postgresql_where=sa.text("model_code IS NOT NULL"),
    )
    op.drop_index("ix_product_specs_gin", table_name="product", postgresql_using="gin")
    op.drop_index("ix_product_category", table_name="product")
    op.drop_table("product")
    op.drop_table("llm_extraction_cache")
    op.drop_table("live_search_cache")
    op.drop_table("conversation")
