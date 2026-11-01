"""add fptshop and anphat to the site CHECK constraints

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 00:00:00.000000

ADR-0008: FPT Shop và An Phát thay Hoàng Hà và Laptop88 làm trang lõi. Giá trị cũ vẫn được giữ
(seed và test còn dùng). Viết tay vì Alembic không so sánh CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SITES = ("gearvn", "hoangha", "laptop88", "viettelstore", "nguyenkim", "mockshop")
NEW_SITES = (*OLD_SITES, "fptshop", "anphat")
SITE_TABLES = (
    ("offer", "ck_offer_site"),
    ("scrape_run", "ck_scrape_run_site"),
)


def _check(sites: Sequence[str]) -> str:
    return "site IN (" + ", ".join(f"'{site}'" for site in sites) + ")"


def _replace_site_checks(sites: Sequence[str]) -> None:
    for table, name in SITE_TABLES:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, sa.text(_check(sites)))


def upgrade() -> None:
    """Cho phép `fptshop` và `anphat` ở cột `site` của `offer` và `scrape_run`."""
    _replace_site_checks(NEW_SITES)


def downgrade() -> None:
    """Về danh sách 6 trang; lỗi nếu còn dòng dùng `fptshop`/`anphat` (xóa chúng trước)."""
    _replace_site_checks(OLD_SITES)
