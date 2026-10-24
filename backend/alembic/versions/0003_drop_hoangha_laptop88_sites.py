"""drop hoangha and laptop88 from the site CHECK constraints

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24 00:00:00.000000

ADR-0008 đã loại Hoàng Hà và Laptop88 (T4.6). Dòng cũ (chỉ là dữ liệu seed hư cấu, URL `.example`)
được chuyển sang `fptshop`/`anphat` thay vì xóa để giữ lịch sử giá, danh sách mua và cảnh báo.
Viết tay vì Alembic không so sánh CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SITES = ("gearvn", "hoangha", "laptop88", "viettelstore", "nguyenkim", "mockshop")
BEFORE_SITES = (*OLD_SITES, "fptshop", "anphat")  # danh sách ở revision 0002
AFTER_SITES = ("gearvn", "fptshop", "anphat", "viettelstore", "nguyenkim", "mockshop")
SITE_TABLES = (
    ("offer", "ck_offer_site"),
    ("scrape_run", "ck_scrape_run_site"),
)
# (site cũ, site thay thế, host URL seed cũ, host URL seed mới)
RENAMES = (
    ("hoangha", "fptshop", "mock-hoangha.example", "mock-fptshop.example"),
    ("laptop88", "anphat", "mock-laptop88.example", "mock-anphat.example"),
)


def _check(sites: Sequence[str]) -> str:
    return "site IN (" + ", ".join(f"'{site}'" for site in sites) + ")"


def _replace_site_checks(sites: Sequence[str]) -> None:
    for table, name in SITE_TABLES:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, sa.text(_check(sites)))


def upgrade() -> None:
    """Chuyển dòng `hoangha`→`fptshop`, `laptop88`→`anphat` rồi bỏ hai giá trị khỏi CHECK."""
    connection = op.get_bind()
    for old, new, old_host, new_host in RENAMES:
        params = {"old": old, "new": new, "old_host": old_host, "new_host": new_host}
        connection.execute(
            sa.text(
                "UPDATE offer SET site = :new, url = replace(url, :old_host, :new_host)"
                " WHERE site = :old"
            ),
            params,
        )
        connection.execute(sa.text("UPDATE scrape_run SET site = :new WHERE site = :old"), params)
    _replace_site_checks(AFTER_SITES)


def downgrade() -> None:
    """Cho phép lại hai giá trị cũ; các dòng đã chuyển sang `fptshop`/`anphat` không khôi phục."""
    _replace_site_checks(BEFORE_SITES)
