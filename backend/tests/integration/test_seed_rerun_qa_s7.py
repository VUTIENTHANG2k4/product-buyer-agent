"""QA lượt việc nhỏ 7 (T6.7): chạy seed lần hai với sản phẩm "ca khó" và `specs_confidence`.

Dùng `db_session` (rollback cuối test) nên nằm riêng khỏi `test_seed_hard_cases_qa_s7.py`.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, col, func, select

from app.db.models import Offer, Product
from app.domain.enums import Category, StockStatus
from scripts.seed import FIXTURE_DIR, SeedDataError, load_catalog, seed_database
from tests.service_support import add_product

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
SOLD_OUT = {"MOCK-MSI-SOLDOUT", "MOCK-LOG-G203-SOLDOUT"}
INCOMPLETE = {"MOCK-ACER-NOSPEC", "MOCK-AKKO-5075-NOSPEC"}

COMPLETE_SPECS: dict[str, Any] = {
    "cpu_model": "i5-1235U",
    "gpu_model": "GeForce RTX4060 8GB",
    "ram_gb": 16,
    "storage_gb": 512,
}
THIN_SPECS: dict[str, Any] = {"cpu_model": "i5-1235U", "ram_gb": 8}


def laptop(specs: dict[str, Any], *, incomplete: bool = False) -> dict[str, Any]:
    return {
        "brand": "Acer",
        "model_code": "MOCK-RERUN-1",
        "canonical_name": "Acer Mock Rerun",
        "specs": deepcopy(specs),
        "incomplete_specs": incomplete,
        "offers": [
            {
                "site": "gearvn",
                "url": "https://mock-gearvn.example/p/rerun-1",
                "title": "Acer Mock Rerun",
                "price": 15_000_000,
            }
        ],
    }


def write_laptops(directory: Path, products: list[dict[str, Any]]) -> Path:
    payload = {"category": "laptop", "products": products}
    (directory / "laptops.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def stored(session: Session, code: str) -> Product:
    return session.exec(select(Product).where(Product.model_code == code)).one()


def test_rerun_lowers_specs_confidence_when_a_product_becomes_incomplete(
    db_session: Session, tmp_path: Path
) -> None:
    directory = write_laptops(tmp_path, [laptop(COMPLETE_SPECS)])
    seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
    assert stored(db_session, "MOCK-RERUN-1").specs_confidence == 1.0

    write_laptops(tmp_path, [laptop(THIN_SPECS, incomplete=True)])
    seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

    product = stored(db_session, "MOCK-RERUN-1")
    assert product.specs == THIN_SPECS
    assert 0 < product.specs_confidence < 0.5


def test_rerun_restores_full_specs_confidence_when_a_product_becomes_complete(
    db_session: Session, tmp_path: Path
) -> None:
    directory = write_laptops(tmp_path, [laptop(THIN_SPECS, incomplete=True)])
    seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
    assert stored(db_session, "MOCK-RERUN-1").specs_confidence < 0.5

    write_laptops(tmp_path, [laptop(COMPLETE_SPECS)])
    seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

    assert stored(db_session, "MOCK-RERUN-1").specs_confidence == 1.0


def test_seed_overwrites_the_confidence_of_a_product_that_already_exists_from_elsewhere(
    db_session: Session, tmp_path: Path
) -> None:
    """Sản phẩm do pipeline tạo trước (độ tin cậy 0,3) được seed ghi lại theo specs của fixture."""
    add_product(
        db_session,
        category=Category.laptop,
        brand="Acer",
        model_code="MOCK-RERUN-1",
        specs=THIN_SPECS,
        specs_confidence=0.3,
    )
    directory = write_laptops(tmp_path, [laptop(COMPLETE_SPECS)])

    summary = seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

    assert (summary.products_created, summary.products_existing) == (0, 1)
    product = stored(db_session, "MOCK-RERUN-1")
    assert product.specs_confidence == 1.0
    assert product.specs["ram_gb"] == 16 and product.specs["storage_gb"] == 512


def test_removing_the_incomplete_flag_without_completing_the_specs_is_a_loud_error(
    db_session: Session, tmp_path: Path
) -> None:
    directory = write_laptops(tmp_path, [laptop(THIN_SPECS, incomplete=True)])
    seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
    write_laptops(tmp_path, [laptop(THIN_SPECS, incomplete=False)])

    with pytest.raises(SeedDataError, match="thiếu trường bắt buộc") as caught:
        load_catalog(directory)

    assert "MOCK-RERUN-1" in str(caught.value)


def count_rows(session: Session, model: type[Any]) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def test_seeding_the_real_eval_profile_twice_keeps_the_hard_cases_unchanged(
    db_session: Session,
) -> None:
    catalog = load_catalog(FIXTURE_DIR)
    seed_database(db_session, "eval", now=NOW)

    def snapshot() -> dict[str, tuple[float, tuple[tuple[str, str], ...]]]:
        result: dict[str, tuple[float, tuple[tuple[str, str], ...]]] = {}
        for code in sorted(SOLD_OUT | INCOMPLETE):
            product = stored(db_session, code)
            offers = db_session.exec(
                select(Offer).where(Offer.product_id == product.id).order_by(col(Offer.url))
            ).all()
            result[code] = (
                product.specs_confidence,
                tuple((offer.url, offer.stock_status.value) for offer in offers),
            )
        return result

    first = snapshot()
    counts = (count_rows(db_session, Product), count_rows(db_session, Offer))
    again = seed_database(db_session, "eval", now=NOW)

    assert snapshot() == first
    assert (count_rows(db_session, Product), count_rows(db_session, Offer)) == counts
    assert (again.products_created, again.products_existing) == (0, len(catalog))
    assert counts[0] == len(catalog)
    for code in SOLD_OUT:
        assert {status for _, status in first[code][1]} == {StockStatus.out_of_stock.value}
    for code in INCOMPLETE:
        assert first[code][0] < 0.5


def test_the_e2e_profile_never_loads_a_hard_case(db_session: Session) -> None:
    summary = seed_database(db_session, "e2e", now=NOW)

    codes = set(db_session.exec(select(Product.model_code)).all())

    assert summary.products_created == 16
    assert codes.isdisjoint(SOLD_OUT | INCOMPLETE)
    low_confidence = db_session.exec(
        select(func.count()).select_from(Product).where(col(Product.specs_confidence) < 1.0)
    ).one()
    assert low_confidence == 0
