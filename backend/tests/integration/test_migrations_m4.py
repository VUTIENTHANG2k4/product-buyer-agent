"""QA M4: migration 0002 (thêm `fptshop`/`anphat` vào CHECK `site`) với dữ liệu cũ và mới.

Bổ sung cho `test_migrations.py` (đã kiểm `scrape_run`): ở đây kiểm bảng `offer`, mọi giá trị cũ,
downgrade khi còn dữ liệu trang mới (phải lỗi và để nguyên CSDL) và vòng upgrade/downgrade/upgrade.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from tests.db_support import downgrade_to, upgrade_to

OLD_SITES = ("gearvn", "hoangha", "laptop88", "viettelstore", "nguyenkim", "mockshop")
NEW_SITES = ("fptshop", "anphat")
CONNECT_ARGS = {"connect_timeout": 3}


@pytest.fixture
def empty_engine(db_engine: Engine) -> Iterator[Engine]:
    """Database tạm hoàn toàn rỗng (tạo và xóa trong cùng test)."""
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


def _product(engine: Engine) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    "INSERT INTO product (category, brand, canonical_name, specs_confidence)"
                    " VALUES ('laptop', 'Mock', 'Mock laptop', 1) RETURNING id"
                )
            ).scalar_one()
        )


def _offer(engine: Engine, product_id: int, site: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO offer (product_id, site, url, title, price, price_type,"
                " stock_status, match_method, is_active)"
                " VALUES (:product_id, :site, :url, 'Mock', 1000000, 'regular', 'in_stock',"
                " 'new', true)"
            ),
            {"product_id": product_id, "site": site, "url": f"https://{site}.example/p"},
        )


def _run(engine: Engine, site: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scrape_run (site, category, status, trigger, pages_fetched,"
                " items_parsed, items_failed, offers_upserted, price_changes)"
                " VALUES (:site, 'laptop', 'SUCCEEDED', 'test', 1, 1, 0, 1, 0)"
            ),
            {"site": site},
        )


def _sites(engine: Engine, table: str) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT site FROM {table} ORDER BY id"))
        return [row[0] for row in rows]


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _check_names(engine: Engine, table: str) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE contype = 'c'"
                " AND conrelid = CAST(:table AS regclass) AND conname LIKE '%site%'"
            ),
            {"table": table},
        )
        return [row[0] for row in rows]


def test_every_old_site_row_in_both_tables_survives_the_upgrade(empty_engine: Engine) -> None:
    upgrade_to(empty_engine, "0001")
    product_id = _product(empty_engine)
    for site in OLD_SITES:
        _offer(empty_engine, product_id, site)
        _run(empty_engine, site)

    upgrade_to(empty_engine, "0002")

    assert _sites(empty_engine, "offer") == list(OLD_SITES)
    assert _sites(empty_engine, "scrape_run") == list(OLD_SITES)


def test_offer_table_accepts_the_new_sites_after_0002_and_still_rejects_others(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0001")
    product_id = _product(empty_engine)
    with pytest.raises(IntegrityError):
        _offer(empty_engine, product_id, "fptshop")

    upgrade_to(empty_engine, "0002")

    for site in NEW_SITES:
        _offer(empty_engine, product_id, site)
    assert _sites(empty_engine, "offer") == list(NEW_SITES)
    with pytest.raises(IntegrityError):
        _offer(empty_engine, product_id, "shopee")


@pytest.mark.parametrize("table", ["offer", "scrape_run"])
def test_downgrade_with_new_site_rows_fails_and_leaves_the_database_untouched(
    empty_engine: Engine, table: str
) -> None:
    upgrade_to(empty_engine, "0002")
    product_id = _product(empty_engine)
    if table == "offer":
        _offer(empty_engine, product_id, "gearvn")
        _offer(empty_engine, product_id, "anphat")
    else:
        _run(empty_engine, "gearvn")
        _run(empty_engine, "fptshop")

    with pytest.raises(IntegrityError):
        downgrade_to(empty_engine, "0001")

    # DDL của PostgreSQL chạy trong transaction: lỗi thì giữ nguyên bản 0002 và mọi dòng.
    assert _revision(empty_engine) == "0002"
    assert len(_sites(empty_engine, table)) == 2
    other = "anphat" if table == "offer" else "fptshop"
    assert other in _sites(empty_engine, table)
    if table == "offer":
        _offer(empty_engine, product_id, "fptshop")  # CHECK mới vẫn còn hiệu lực


def test_downgrade_succeeds_once_the_new_site_rows_are_removed(empty_engine: Engine) -> None:
    upgrade_to(empty_engine, "0002")
    product_id = _product(empty_engine)
    _offer(empty_engine, product_id, "hoangha")
    _offer(empty_engine, product_id, "fptshop")
    _run(empty_engine, "anphat")
    with empty_engine.begin() as connection:
        connection.execute(text("DELETE FROM offer WHERE site = 'fptshop'"))
        connection.execute(text("DELETE FROM scrape_run WHERE site = 'anphat'"))

    downgrade_to(empty_engine, "0001")

    assert _revision(empty_engine) == "0001"
    assert _sites(empty_engine, "offer") == ["hoangha"]


def test_upgrade_downgrade_upgrade_keeps_one_site_check_per_table(empty_engine: Engine) -> None:
    upgrade_to(empty_engine, "0002")
    downgrade_to(empty_engine, "0001")
    upgrade_to(empty_engine, "0002")

    assert _check_names(empty_engine, "offer") == ["ck_offer_site"]
    assert _check_names(empty_engine, "scrape_run") == ["ck_scrape_run_site"]
    _run(empty_engine, "anphat")
    assert _revision(empty_engine) == "0002"


# ---- T4.6: migration 0003 (bỏ hoangha/laptop88 khỏi CHECK `site`, chuyển dòng cũ) ----
def _offer_at(engine: Engine, product_id: int, site: str, url: str) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    "INSERT INTO offer (product_id, site, url, title, price, price_type,"
                    " stock_status, match_method, is_active)"
                    " VALUES (:product_id, :site, :url, 'Mock', 1000000, 'regular', 'in_stock',"
                    " 'new', true) RETURNING id"
                ),
                {"product_id": product_id, "site": site, "url": url},
            ).scalar_one()
        )


def _rows(engine: Engine, sql: str) -> list[tuple[str, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def test_0003_moves_legacy_rows_to_the_replacement_sites_and_keeps_their_history(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0002")
    product_id = _product(empty_engine)
    old_id = _offer_at(empty_engine, product_id, "hoangha", "https://mock-hoangha.example/p/a")
    _offer_at(empty_engine, product_id, "laptop88", "https://mock-laptop88.example/p/b")
    _offer_at(empty_engine, product_id, "gearvn", "https://mock-gearvn.example/p/c")
    _run(empty_engine, "hoangha")
    _run(empty_engine, "laptop88")
    with empty_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO price_history (offer_id, price, price_type, stock_status)"
                " VALUES (:offer_id, 900000, 'regular', 'in_stock')"
            ),
            {"offer_id": old_id},
        )

    upgrade_to(empty_engine, "0003")

    assert _rows(empty_engine, "SELECT site, url FROM offer ORDER BY id") == [
        ("fptshop", "https://mock-fptshop.example/p/a"),
        ("anphat", "https://mock-anphat.example/p/b"),
        ("gearvn", "https://mock-gearvn.example/p/c"),
    ]
    assert _sites(empty_engine, "scrape_run") == ["fptshop", "anphat"]
    assert _rows(
        empty_engine, f"SELECT price::text FROM price_history WHERE offer_id = {old_id}"
    ) == [("900000",)]
    assert _revision(empty_engine) == "0003"


@pytest.mark.parametrize("table", ["offer", "scrape_run"])
@pytest.mark.parametrize("site", ["hoangha", "laptop88"])
def test_0003_check_rejects_the_removed_sites(empty_engine: Engine, table: str, site: str) -> None:
    upgrade_to(empty_engine, "0003")
    product_id = _product(empty_engine)

    with pytest.raises(IntegrityError):
        if table == "offer":
            _offer(empty_engine, product_id, site)
        else:
            _run(empty_engine, site)


def test_0003_still_accepts_every_remaining_site(empty_engine: Engine) -> None:
    upgrade_to(empty_engine, "0003")
    product_id = _product(empty_engine)
    sites = ("gearvn", "fptshop", "anphat", "viettelstore", "nguyenkim", "mockshop")

    for site in sites:
        _offer(empty_engine, product_id, site)
        _run(empty_engine, site)

    assert _sites(empty_engine, "offer") == list(sites)
    assert _check_names(empty_engine, "offer") == ["ck_offer_site"]
    assert _check_names(empty_engine, "scrape_run") == ["ck_scrape_run_site"]


def test_0003_downgrade_reallows_the_legacy_sites_and_does_not_restore_moved_rows(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0002")
    product_id = _product(empty_engine)
    _offer_at(empty_engine, product_id, "hoangha", "https://mock-hoangha.example/p/a")
    upgrade_to(empty_engine, "0003")

    downgrade_to(empty_engine, "0002")

    assert _revision(empty_engine) == "0002"
    assert _sites(empty_engine, "offer") == ["fptshop"]
    _offer(empty_engine, product_id, "hoangha")  # CHECK của 0002 nhận lại giá trị cũ
