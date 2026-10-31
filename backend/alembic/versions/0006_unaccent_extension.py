"""enable the unaccent extension for accent-insensitive product search

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31 00:00:00.000000

`GET /products?q=` so khớp không phân biệt dấu ("chuot khong day" tìm được "Chuột không dây",
BUG-M7-3) bằng `unaccent(...)` ở truy vấn. Không đổi bảng nào; `unaccent` là extension "trusted"
của PostgreSQL 13+ nên không cần quyền superuser.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS unaccent")
