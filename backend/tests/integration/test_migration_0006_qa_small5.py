"""QA small-fixes-5: migration 0006 (extension `unaccent`): lên -> xuống -> lên, dữ liệu giữ nguyên,
truy vấn tìm kiếm dùng được sau khi lên lại; ghép lại offer có `raw_specs` chứa mọi kiểu JSON.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.domain.enums import Category
from app.services.rematch_service import RematchService
from tests.db_support import downgrade_to, upgrade_to, upgrade_to_head
from tests.integration.test_rematch_service import ACER, ACER_FPT, offer, product

CONNECT_ARGS = {"connect_timeout": 3}
EXTENSION = "SELECT count(*) FROM pg_extension WHERE extname = 'unaccent'"


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


def extension_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(EXTENSION)).scalar_one())


def unaccent(engine: Engine, value: str) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT unaccent(:v)"), {"v": value}).scalar_one())


def test_upgrade_downgrade_upgrade_round_trip_keeps_the_function_working(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0006")
    downgrade_to(empty_engine, "0005")
    assert extension_count(empty_engine) == 0

    upgrade_to(empty_engine, "0006")

    assert extension_count(empty_engine) == 1
    assert unaccent(empty_engine, "Đặng Thuỳ Chuột") == "Dang Thuy Chuot"


def test_upgrade_is_idempotent_when_the_extension_already_exists(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0005")
    with empty_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION unaccent"))

    upgrade_to(empty_engine, "0006")

    assert extension_count(empty_engine) == 1


def test_downgrade_when_the_extension_is_already_gone_does_not_fail(
    empty_engine: Engine,
) -> None:
    upgrade_to(empty_engine, "0006")
    with empty_engine.begin() as connection:
        connection.execute(text("DROP EXTENSION unaccent"))

    downgrade_to(empty_engine, "0005")

    assert extension_count(empty_engine) == 0


def test_downgrade_keeps_product_rows_and_a_second_upgrade_restores_search(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO product (category, brand, model_code, canonical_name, specs, "
                "specs_confidence, created_at, updated_at) VALUES "
                "('mouse', 'Mock', 'MOCK-1', 'Chuột Mock', "
                "'{}'::jsonb, 1.0, now(), now())"
            )
        )

    downgrade_to(migrated_engine, "0005")
    with migrated_engine.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM product")).scalar_one()
    upgrade_to_head(migrated_engine)

    assert remaining == 1
    with migrated_engine.connect() as connection:
        found = connection.execute(
            text("SELECT count(*) FROM product WHERE unaccent(canonical_name) ILIKE '%chuot%'")
        ).scalar_one()
    assert found == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Đ", "D"),
        ("đ", "d"),
        ("Ơ", "O"),
        ("ư", "u"),
        ("ǆ", "dz"),
        ("ß", "ss"),
        ("é", "e"),
        ("ụ̂", "u"),
    ],
)
def test_unaccent_folds_vietnamese_letters_and_combining_marks(
    migrated_engine: Engine,
    raw: str,
    expected: str,
) -> None:
    assert unaccent(migrated_engine, raw) == expected


# ---------------------------------------------------- rematch với raw_specs mọi kiểu JSON
JSON_VALUES: list[Any] = [
    16,
    -1,
    0,
    3.5,
    1e300,
    True,
    False,
    None,
    "",
    "   ",
    [],
    ["16 GB", 8],
    [[["16 GB"]]],
    {},
    {"a": {"b": "16 GB"}},
    {"value": "16 GB"},
]


def test_rematch_survives_every_json_type_in_every_raw_spec_value(db_session: Session) -> None:
    host = product(
        db_session,
        Category.laptop,
        brand="Acer",
        canonical_name="Acer Aspire Lite 15 AL15-53P-56QH",
    )
    raw: dict[str, Any] = {
        f"{label} {index}": value
        for index, value in enumerate(JSON_VALUES)
        for label in ("Dung lượng RAM", "Ổ cứng", "CPU", "Card đồ họa", "Tần số quét", "Màn hình")
    }
    offer(db_session, host, ACER, raw_specs=raw)
    offer(db_session, host, ACER_FPT, raw_specs={"RAM": 8, "CPU": None, "Ổ cứng": ["512GB"]})

    report = RematchService(db_session).run([Category.laptop], apply=True)

    assert report.offers_checked == 2


@pytest.mark.parametrize(
    "category",
    [Category.laptop, Category.mouse, Category.keyboard, Category.headset],
)
def test_rematch_survives_json_values_in_all_four_categories(
    db_session: Session, category: Category
) -> None:
    host = product(db_session, category, brand="Mock", canonical_name="Mock thiết bị")
    labels = [
        "Kết nối",
        "Switch",
        "Loại switch",
        "Đèn nền",
        "Trọng lượng",
        "Số nút",
        "Micro",
        "Driver",
        "Nhóm thuộc tính",
        "Hệ điều hành",
        "Cân nặng",
    ]
    raw: dict[str, Any] = {f"{label}": value for label in labels for value in JSON_VALUES[:1]} | {
        f"{label} {index}": value for label in labels for index, value in enumerate(JSON_VALUES)
    }
    offer(db_session, host, "Mock thiết bị Gaming Wireless RGB 75% Switch Reaper", raw_specs=raw)

    report = RematchService(db_session).run([category], apply=True)

    assert report.offers_checked == 1
