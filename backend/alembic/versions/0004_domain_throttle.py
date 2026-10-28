"""add domain_throttle: per-domain request slots shared by every process

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28 00:00:00.000000

Bộ giới hạn độ trễ domain (>= 5 s/domain) từng nằm riêng trong mỗi tiến trình `Fetcher`, nên `api`
và `worker` có thể cùng tải một domain (T9.8). Mỗi domain một dòng giữ mốc sớm nhất được gửi request
kế tiếp; các tiến trình đặt chỗ nguyên tử bằng `INSERT ... ON CONFLICT DO UPDATE`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_throttle",
        sa.Column("domain", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column(
            "next_allowed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_domain_throttle")),
    )


def downgrade() -> None:
    op.drop_table("domain_throttle")
