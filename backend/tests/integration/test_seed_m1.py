"""QA M1: fixture hỏng, chạy lại và tập con e2e của seed (scripts/seed.py, docs/09 §3)."""

import codecs
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session, func, select

import scripts.seed as seed_module
from app.db.models import Offer, PriceHistory, Product
from app.db.repositories import OfferRepository, ProductQuery, ProductRepository
from app.domain.enums import Category
from scripts.seed import (
    FIXTURE_DIR,
    SeedDataError,
    load_catalog,
    load_extras,
    main,
    reset_database,
    seed_database,
)
from tests.integration.test_seed_loader import EXTRAS, LAPTOP, MOUSE, write_fixtures

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

LAPTOPS_JSON = json.dumps({"category": "laptop", "products": [LAPTOP]})


def _count(session: Session, model: type[Any]) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def _outcome(action: Callable[[], object]) -> str:
    """'ok', 'seed-error' (SeedDataError) hoặc tên lớp lỗi khác (lỗi thô lọt ra ngoài)."""
    try:
        action()
    except SeedDataError:
        return "seed-error"
    except Exception as error:  # noqa: BLE001 - cần biết lớp lỗi thô nào lọt ra
        return type(error).__name__
    return "ok"


# --- Fixture hỏng: lỗi phải là SeedDataError (main in thông báo gọn, exit code 1) -----------------

BROKEN_BYTES: list[tuple[str, bytes]] = [
    ("malformed-json", b'{"category": "laptop", "products": ['),
    ("empty-file", b""),
    ("json-null", b"null"),
    ("top-level-array", b"[]"),
    ("utf8-bom", b"\xef\xbb\xbf" + LAPTOPS_JSON.encode()),
]


@pytest.mark.parametrize(("label", "payload"), BROKEN_BYTES, ids=[b[0] for b in BROKEN_BYTES])
def test_broken_category_file_is_reported_as_seed_data_error(
    tmp_path: Path, label: str, payload: bytes
) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / "laptops.json").write_bytes(payload)

    outcome = _outcome(lambda: load_catalog(tmp_path))

    # BOM của Notepad/Excel trên Windows có thể được chấp nhận ("ok") hoặc báo lỗi rõ ràng.
    allowed = ("seed-error", "ok") if label == "utf8-bom" else ("seed-error",)
    assert outcome in allowed, f"{label}: {outcome}"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            b'{"category": "laptop", "products": []}' + bytes([0xFF, 0xFE]), id="invalid-utf8"
        ),
        pytest.param(
            b'{"category": "laptop", "products": ["' + "đ".encode()[:1], id="truncated-utf8"
        ),
        pytest.param('{"category": "laptop"}'.encode("utf-16"), id="utf-16"),
    ],
)
def test_category_file_with_wrong_encoding_is_reported_as_seed_data_error(
    tmp_path: Path, payload: bytes
) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / "laptops.json").write_bytes(payload)

    assert _outcome(lambda: load_catalog(tmp_path)) == "seed-error"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'{"shopping_list_name": "Mock", ', id="malformed-json"),
        pytest.param(b"", id="empty-file"),
        pytest.param(b'{"shopping_list_name": "Mock"}\xff', id="invalid-utf8"),
        pytest.param(b"\xef\xbb\xbf" + json.dumps(EXTRAS).encode(), id="utf8-bom"),
    ],
)
def test_broken_extras_file_is_reported_as_seed_data_error_or_loaded(
    tmp_path: Path, payload: bytes
) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / "extras.json").write_bytes(payload)

    assert _outcome(lambda: load_extras(tmp_path)) in ("seed-error", "ok")


def test_extras_file_saved_with_utf8_bom_is_loaded(tmp_path: Path) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / "extras.json").write_bytes(codecs.BOM_UTF8 + json.dumps(EXTRAS).encode())

    extras = load_extras(tmp_path)

    assert extras is not None
    assert extras.shopping_list_name == EXTRAS["shopping_list_name"]


@pytest.mark.parametrize(
    ("name", "load"),
    [("laptops.json", load_catalog), ("extras.json", load_extras)],
)
def test_wrong_encoding_error_names_the_file(
    tmp_path: Path, name: str, load: Callable[[Path], object]
) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / name).write_bytes('{"category": "laptop"}'.encode("utf-16"))

    with pytest.raises(SeedDataError, match=name):
        load(tmp_path)


def test_main_returns_exit_code_1_for_malformed_extras_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_engine: Engine
) -> None:
    write_fixtures(tmp_path, extras=None)
    (tmp_path / "extras.json").write_text('{"shopping_list_name": ', encoding="utf-8")
    real = seed_module.seed_database
    monkeypatch.setattr(seed_module, "get_engine", lambda _url: db_engine)
    monkeypatch.setattr(
        seed_module,
        "seed_database",
        lambda session, fixture: real(session, fixture, now=NOW, fixtures_dir=tmp_path),
    )

    assert main(["--fixture", "dev"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"quantity": 0}, id="quantity-zero"),
        pytest.param({"quantity": True}, id="quantity-bool"),
        pytest.param({"quantity": "2"}, id="quantity-string"),
        pytest.param({"brand": "  "}, id="blank-brand"),
        pytest.param({"unknown": 1}, id="unknown-key"),
    ],
)
def test_extras_list_items_are_validated(tmp_path: Path, changes: dict[str, Any]) -> None:
    extras = deepcopy(EXTRAS)
    extras["shopping_list_items"][0].update(changes)
    write_fixtures(tmp_path, extras=extras)

    with pytest.raises(SeedDataError):
        load_extras(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"target_price": 0}, id="target-zero"),
        pytest.param({"target_price": -1}, id="target-negative"),
        pytest.param({"target_price": True}, id="target-bool"),
        pytest.param({"destination": ""}, id="blank-destination"),
        pytest.param({"channel": "sms"}, id="unknown-channel"),
    ],
)
def test_extras_alerts_are_validated(tmp_path: Path, changes: dict[str, Any]) -> None:
    extras = deepcopy(EXTRAS)
    extras["alerts"][0].update(changes)
    write_fixtures(tmp_path, extras=extras)

    with pytest.raises(SeedDataError):
        load_extras(tmp_path)


@pytest.mark.parametrize(
    "other_url",
    [
        pytest.param("https://MOCK-GEARVN.example/p/l1", id="host-case"),
        pytest.param("https://mock-gearvn.example:443/p/l1", id="default-port"),
        pytest.param("https://mock-gearvn.example/p/./l1", id="dot-segment"),
    ],
)
def test_catalog_detects_duplicate_offer_urls_after_url_normalization(
    tmp_path: Path, other_url: str
) -> None:
    other = deepcopy(MOUSE)
    other["offers"][0]["url"] = other_url
    laptop = deepcopy(LAPTOP)
    laptop["offers"] = [laptop["offers"][0]]
    write_fixtures(tmp_path, laptops=[laptop], mice=[other])

    with pytest.raises(SeedDataError, match="trùng URL"):
        load_catalog(tmp_path)


# --- Chạy lại, tập con e2e, reset -----------------------------------------------------------------


def test_real_fixtures_seeded_twice_leave_every_table_unchanged(db_session: Session) -> None:
    first = seed_database(db_session, "dev", now=NOW)
    before = {model: _count(db_session, model) for model in (Product, Offer, PriceHistory)}

    second = seed_database(db_session, "dev", now=NOW)

    assert {model: _count(db_session, model) for model in before} == before
    assert (second.products_created, second.offers_created, second.history_rows) == (0, 0, 0)
    assert second.products_existing == first.products_created
    assert second.offers_refreshed == first.offers_created


def test_e2e_subset_then_full_profile_adds_the_rest_without_duplicating(
    db_session: Session,
) -> None:
    subset = seed_database(db_session, "e2e", now=NOW)
    full = seed_database(db_session, "dev", now=NOW)

    total = len(load_catalog(FIXTURE_DIR))
    assert subset.products_created + full.products_created == total
    assert full.products_existing == subset.products_created
    assert _count(db_session, Product) == total


def test_full_profile_then_e2e_subset_changes_nothing(db_session: Session) -> None:
    seed_database(db_session, "dev", now=NOW)
    before = _count(db_session, Offer), _count(db_session, PriceHistory)

    again = seed_database(db_session, "e2e", now=NOW)

    assert (_count(db_session, Offer), _count(db_session, PriceHistory)) == before
    assert again.products_created == again.offers_created == again.history_rows == 0


def test_reseeding_reactivates_offers_the_pipeline_had_switched_off(db_session: Session) -> None:
    seed_database(db_session, "dev", now=NOW)
    active_query = ProductQuery(category=Category.laptop, limit=100)
    expected = ProductRepository(db_session).search(active_query).total
    db_session.exec(text("UPDATE offer SET is_active = false"))  # type: ignore[call-overload]
    assert ProductRepository(db_session).search(active_query).total == 0

    seed_database(db_session, "dev", now=NOW)

    assert ProductRepository(db_session).search(active_query).total == expected > 0
    assert all(offer.is_active for offer in db_session.exec(select(Offer)).all())


def test_reseeding_restores_fixture_price_after_the_offer_price_drifted(
    db_session: Session,
) -> None:
    seed_database(db_session, "e2e", now=NOW)
    offer = db_session.exec(select(Offer)).first()
    assert offer is not None
    fixture_price = offer.price
    offer.price = fixture_price + 1_000_000
    db_session.flush()

    seed_database(db_session, "e2e", now=NOW)

    refreshed = OfferRepository(db_session).get_by_url(offer.url)
    assert refreshed is not None and refreshed.price == fixture_price


def test_reset_database_keeps_the_alembic_version_table(db_session: Session) -> None:
    seed_database(db_session, "e2e", now=NOW)
    versions = db_session.exec(text("SELECT count(*) FROM alembic_version")).scalar_one()  # type: ignore[call-overload]
    assert versions == 1

    reset_database(db_session)

    assert db_session.exec(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1  # type: ignore[call-overload]
    assert _count(db_session, Product) == 0


@pytest.mark.parametrize("argv", [[], ["--reset"], ["--fixture", "dev", "--yes", "--reset", "x"]])
def test_main_rejects_missing_or_unknown_arguments_before_touching_the_database(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_url: str) -> Engine:
        raise AssertionError("main không được tạo engine khi tham số sai")

    monkeypatch.setattr(seed_module, "get_engine", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 2
