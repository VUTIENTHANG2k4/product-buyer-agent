"""rename domain_throttle.next_allowed_at to last_slot_at

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 00:00:00.000000

Cột lưu khe gần nhất đã cấp chứ không phải mốc được phép kế tiếp: khe kế tiếp cách khe này đúng độ
trễ của request MỚI (review T9.8), nên `Crawl-delay` lớn hơn của request sau vẫn được giữ giữa các
tiến trình. Bảng chỉ chứa mốc tạm thời nên không cần chuyển dữ liệu.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("domain_throttle", "next_allowed_at", new_column_name="last_slot_at")


def downgrade() -> None:
    op.alter_column("domain_throttle", "last_slot_at", new_column_name="next_allowed_at")
