"""Test bộ nạp seed (scripts/seed.py) với dữ liệu nhỏ dựng ngay trong test (docs/09 §3)."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, col, func, select

import scripts.seed as seed_module
from app.db.models import (
    Offer,
    PriceAlert,
    PriceHistory,
    Product,
    ScrapeRun,
    ShoppingList,
    ShoppingListItem,
)
from app.db.repositories import PriceHistoryRepository
from app.domain.enums import Category, ScrapeStatus, SiteKey
from scripts.seed import (
    SeedDataError,
    load_catalog,
    main,
    normalize_specs,
    reset_database,
    seed_database,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

LAPTOP: dict[str, Any] = {
    "brand": "ASUS",
    "model_code": "MOCK-L1",
    "canonical_name": "ASUS Mock Gaming L1",
    "specs": {
        "cpu_model": "i7-13620H",
        "gpu_model": "GeForce RTX4060 8GB",
        "ram_gb": 16,
        "storage_gb": 512,
    },
    "e2e": True,
    "offers": [
        {
            "site": "gearvn",
            "url": "https://mock-gearvn.example/p/l1",
            "title": "ASUS Mock Gaming L1",
            "price": 27_000_000,
            "history": [
                {"days_ago": 30, "price": 29_000_000},
                {"days_ago": 12, "price": 28_000_000},
            ],
        },
        {
            "site": "anphat",
            "url": "https://mock-anphat.example/p/l1",
            "title": "ASUS Mock Gaming L1 (An Phát)",
            "price": 27_500_000,
        },
    ],
}
MOUSE: dict[str, Any] = {
    "brand": "Logitech",
    "model_code": "MOCK-M1",
    "canonical_name": "Logitech Mock Mouse M1",
    "specs": {"connection": ["wireless_2_4"], "weight_g": 63},
    "offers": [
        {
            "site": "gearvn",
            "url": "https://mock-gearvn.example/p/m1",
            "title": "Logitech Mock Mouse M1",
            "price": 900_000,
        }
    ],
}
EXTRAS: dict[str, Any] = {
    "shopping_list_name": "Mock danh sách mua",
    "shopping_list_items": [
        {"category": "laptop", "brand": "ASUS", "model_code": "MOCK-L1", "note": "máy chính"}
    ],
    "alerts": [
        {
            "category": "mouse",
            "brand": "Logitech",
            "model_code": "MOCK-M1",
            "target_price": 800_000,
            "destination": "mock@example.com",
        }
    ],
}


def write_fixtures(
    directory: Path,
    *,
    laptops: list[dict[str, Any]] | None = None,
    mice: list[dict[str, Any]] | None = None,
    extras: dict[str, Any] | None = EXTRAS,
) -> Path:
    for name, category, products in (
        ("laptops.json", "laptop", [LAPTOP] if laptops is None else laptops),
        ("mice.json", "mouse", [MOUSE] if mice is None else mice),
    ):
        payload = {"category": category, "products": deepcopy(products)}
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    if extras is not None:
        (directory / "extras.json").write_text(json.dumps(extras), encoding="utf-8")
    return directory


def count(session: Session, model: type[Any]) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def with_change(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**deepcopy(base), **changes}


class TestNormalizeSpecs:
    def test_canonicalizes_gpu_and_adds_rank(self) -> None:
        specs = normalize_specs(Category.laptop, LAPTOP["specs"])

        assert specs["gpu_model"] == "RTX 4060"
        assert specs["gpu_rank"] == 40

    def test_rejects_unknown_key_instead_of_dropping_it_silently(self) -> None:
        with pytest.raises(SeedDataError, match="khóa lạ"):
            normalize_specs(Category.laptop, {**LAPTOP["specs"], "ram_gbb": 16})

    def test_rejects_missing_required_field(self) -> None:
        with pytest.raises(SeedDataError, match="thiếu trường bắt buộc"):
            normalize_specs(Category.mouse, {"weight_g": 60})

    def test_rejects_empty_list_as_missing_required_field(self) -> None:
        with pytest.raises(SeedDataError, match="thiếu trường bắt buộc"):
            normalize_specs(Category.mouse, {"connection": []})

    def test_rejects_value_outside_the_spec_schema(self) -> None:
        with pytest.raises(SeedDataError, match="sai khung"):
            normalize_specs(Category.laptop, {**LAPTOP["specs"], "ram_gb": "16"})

    def test_rejects_category_without_spec_model(self) -> None:
        with pytest.raises(SeedDataError, match="không có khung"):
            normalize_specs(Category.other, {})


class TestLoadCatalog:
    def test_loads_every_category_file_with_normalized_specs(self, tmp_path: Path) -> None:
        catalog = load_catalog(write_fixtures(tmp_path))

        assert {(item.category, item.product.model_code) for item in catalog} == {
            (Category.laptop, "MOCK-L1"),
            (Category.mouse, "MOCK-M1"),
        }
        laptop = next(item for item in catalog if item.category is Category.laptop)
        assert laptop.specs["gpu_rank"] == 40

    def test_empty_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(SeedDataError, match="không có file seed"):
            load_catalog(tmp_path)

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            pytest.param({"canonical_name": "ASUS Gaming L1"}, "Mock", id="name-without-mock"),
            pytest.param({"offers": []}, "offers", id="no-offer"),
            pytest.param({"colour": "red"}, "colour", id="unknown-product-field"),
            pytest.param(
                {"image_url": "https://cdn.real-shop.com/l1.jpg"},
                "image_url",
                id="real-image-host",
            ),
        ],
    )
    def test_rejects_invalid_product(
        self, tmp_path: Path, changes: dict[str, Any], message: str
    ) -> None:
        directory = write_fixtures(tmp_path, laptops=[with_change(LAPTOP, **changes)])

        with pytest.raises(SeedDataError, match=message):
            load_catalog(directory)

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            pytest.param({"url": "https://gearvn.vn/p/l1"}, "miền .example", id="real-host"),
            pytest.param({"title": "ASUS Gaming L1"}, "Mock", id="title-without-mock"),
            pytest.param({"price": -1}, "price", id="negative-price"),
            pytest.param(
                {"history": [{"days_ago": 5, "price": 1}, {"days_ago": 9, "price": 2}]},
                "cũ đến mới",
                id="history-not-oldest-first",
            ),
            pytest.param({"history": [{"days_ago": 31, "price": 1}]}, "days_ago", id="too-old"),
        ],
    )
    def test_rejects_invalid_offer(
        self, tmp_path: Path, changes: dict[str, Any], message: str
    ) -> None:
        laptop = deepcopy(LAPTOP)
        laptop["offers"][0].update(changes)

        with pytest.raises(SeedDataError, match=message):
            load_catalog(write_fixtures(tmp_path, laptops=[laptop]))

    def test_rejects_duplicate_model_key(self, tmp_path: Path) -> None:
        other = deepcopy(LAPTOP)
        other["offers"] = [
            {**LAPTOP["offers"][0], "url": "https://mock-gearvn.example/p/other"},
        ]

        with pytest.raises(SeedDataError, match="trùng"):
            load_catalog(write_fixtures(tmp_path, laptops=[LAPTOP, other]))

    def test_rejects_duplicate_offer_url_across_products(self, tmp_path: Path) -> None:
        other = with_change(LAPTOP, model_code="MOCK-L2")

        with pytest.raises(SeedDataError, match="trùng URL"):
            load_catalog(write_fixtures(tmp_path, laptops=[LAPTOP, other]))

    def test_error_names_the_file_and_product(self, tmp_path: Path) -> None:
        bad = with_change(LAPTOP, specs={"cpu_model": "i7"})

        with pytest.raises(SeedDataError, match=r"laptops\.json / MOCK-L1"):
            load_catalog(write_fixtures(tmp_path, laptops=[bad]))


class TestSeedDatabase:
    def test_creates_products_offers_and_price_history(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        summary = seed_database(db_session, "dev", now=NOW, fixtures_dir=write_fixtures(tmp_path))

        assert (summary.products_created, summary.products_existing) == (2, 0)
        assert (summary.offers_created, summary.offers_refreshed) == (3, 0)
        product = db_session.exec(select(Product).where(Product.model_code == "MOCK-L1")).one()
        assert product.specs["gpu_rank"] == 40
        assert product.specs["gpu_model"] == "RTX 4060"
        offers = db_session.exec(select(Offer).where(Offer.product_id == product.id)).all()
        assert {(offer.site, offer.price) for offer in offers} == {
            (SiteKey.gearvn, 27_000_000),
            (SiteKey.anphat, 27_500_000),
        }

    def test_price_history_follows_the_declared_change_points(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        seed_database(db_session, "dev", now=NOW, fixtures_dir=write_fixtures(tmp_path))
        offer = db_session.exec(
            select(Offer).where(Offer.site == SiteKey.gearvn).order_by(col(Offer.id))
        ).first()
        assert offer is not None and offer.id is not None

        points = PriceHistoryRepository(db_session).list_for_offer(offer.id)

        assert [(p.price, (NOW - p.scraped_at).days) for p in points] == [
            (29_000_000, 30),
            (28_000_000, 12),
            (27_000_000, 0),
        ]

    def test_offer_without_history_gets_flat_price_over_thirty_days(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        seed_database(db_session, "dev", now=NOW, fixtures_dir=write_fixtures(tmp_path))
        offer = db_session.exec(select(Offer).where(Offer.site == SiteKey.anphat)).one()
        assert offer.id is not None

        points = PriceHistoryRepository(db_session).list_for_offer(offer.id)

        assert [(p.price, (NOW - p.scraped_at).days) for p in points] == [
            (27_500_000, 30),
            (27_500_000, 0),
        ]
        assert offer.first_seen_at == NOW - timedelta(days=30)
        assert offer.scraped_at == NOW

    def test_adds_shopping_list_alert_and_scrape_runs_for_dev_and_eval(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        summary = seed_database(db_session, "eval", now=NOW, fixtures_dir=write_fixtures(tmp_path))

        assert (summary.shopping_list_items, summary.alerts, summary.scrape_runs) == (1, 1, 3)
        shopping_list = db_session.exec(select(ShoppingList)).one()
        assert shopping_list.name == "Mock danh sách mua"
        item = db_session.exec(select(ShoppingListItem)).one()
        assert (item.list_id, item.note) == (shopping_list.id, "máy chính")
        alert = db_session.exec(select(PriceAlert)).one()
        assert (alert.target_price, alert.destination) == (800_000, "mock@example.com")
        runs = db_session.exec(select(ScrapeRun)).all()
        assert {(run.site, run.category, run.status, run.items_parsed) for run in runs} == {
            (SiteKey.gearvn, Category.laptop, ScrapeStatus.SUCCEEDED, 1),
            (SiteKey.anphat, Category.laptop, ScrapeStatus.SUCCEEDED, 1),
            (SiteKey.gearvn, Category.mouse, ScrapeStatus.SUCCEEDED, 1),
        }
        assert len(runs) == 3
        assert all(run.finished_at == NOW for run in runs)

    def test_e2e_profile_loads_only_tagged_products_without_extras(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        summary = seed_database(db_session, "e2e", now=NOW, fixtures_dir=write_fixtures(tmp_path))

        assert summary.products_created == 1
        assert [p.model_code for p in db_session.exec(select(Product)).all()] == ["MOCK-L1"]
        assert count(db_session, ShoppingList) == 0
        assert count(db_session, PriceAlert) == 0
        assert count(db_session, ScrapeRun) == 0

    def test_running_twice_does_not_duplicate_rows(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        directory = write_fixtures(tmp_path)
        seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
        before = {
            model: count(db_session, model)
            for model in (Product, Offer, PriceHistory, ShoppingListItem, PriceAlert, ScrapeRun)
        }

        again = seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

        assert {model: count(db_session, model) for model in before} == before
        assert (again.products_created, again.products_existing) == (0, 2)
        assert (again.offers_created, again.offers_refreshed) == (0, 3)
        assert (again.history_rows, again.shopping_list_items, again.alerts) == (0, 0, 0)
        assert again.scrape_runs == 0

    def test_rerun_later_refreshes_scraped_at_and_adds_a_heartbeat_row(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        directory = write_fixtures(tmp_path)
        seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
        later = NOW + timedelta(days=2)

        again = seed_database(db_session, "dev", now=later, fixtures_dir=directory)

        offer = db_session.exec(select(Offer).where(Offer.site == SiteKey.anphat)).one()
        assert offer.scraped_at == later
        assert again.history_rows == 3  # mỗi offer thêm một dòng "heartbeat" (>24 giờ)

    def test_rerun_with_a_changed_fixture_price_updates_the_offer_and_adds_one_changed_row(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        seed_database(db_session, "dev", now=NOW, fixtures_dir=write_fixtures(tmp_path))
        cheaper = deepcopy(LAPTOP)
        cheaper["offers"][0]["price"] = 26_000_000
        directory = write_fixtures(tmp_path, laptops=[cheaper])

        again = seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

        offer = db_session.exec(
            select(Offer).where(Offer.url == "https://mock-gearvn.example/p/l1")
        ).one()
        assert offer.id is not None
        assert offer.price == 26_000_000
        assert again.history_rows == 1
        latest = PriceHistoryRepository(db_session).latest(offer.id)
        assert latest is not None and latest.price == 26_000_000

    def test_rerun_updates_specs_of_an_existing_product(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        seed_database(db_session, "dev", now=NOW, fixtures_dir=write_fixtures(tmp_path))
        changed = deepcopy(LAPTOP)
        changed["specs"]["ram_gb"] = 32
        directory = write_fixtures(tmp_path, laptops=[changed])

        seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

        product = db_session.exec(select(Product).where(Product.model_code == "MOCK-L1")).one()
        assert product.specs["ram_gb"] == 32

    def test_extras_referencing_unknown_product_fail_loudly(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        extras = {**EXTRAS, "alerts": [{**EXTRAS["alerts"][0], "model_code": "MOCK-NOPE"}]}
        directory = write_fixtures(tmp_path, extras=extras)

        with pytest.raises(SeedDataError, match="MOCK-NOPE"):
            seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)


class TestResetDatabase:
    def test_reset_empties_every_table_and_restarts_ids(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        directory = write_fixtures(tmp_path)
        seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)

        reset_database(db_session)

        for model in (Product, Offer, PriceHistory, ShoppingList, PriceAlert, ScrapeRun):
            assert count(db_session, model) == 0
        seed_database(db_session, "dev", now=NOW, fixtures_dir=directory)
        first = db_session.exec(select(Product).order_by(col(Product.id))).first()
        assert first is not None and first.id == 1


class TestMain:
    """`main` chỉ kiểm đường lỗi: đường thành công sẽ commit vào DB, nên chạy bằng `make seed`."""

    @pytest.fixture(autouse=True)
    def use_test_engine(self, monkeypatch: pytest.MonkeyPatch, db_engine: Engine) -> None:
        monkeypatch.setattr(seed_module, "get_engine", lambda _url: db_engine)

    def test_invalid_seed_data_returns_exit_code_1(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(*_args: Any, **_kwargs: Any) -> None:
            raise SeedDataError("laptops.json / MOCK-X: thiếu trường")

        monkeypatch.setattr(seed_module, "seed_database", broken)

        assert main(["--fixture", "dev"]) == 1
        assert "MOCK-X" in caplog.text

    def test_unreachable_database_returns_exit_code_1_with_hint(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def down(*_args: Any, **_kwargs: Any) -> None:
            raise OperationalError("SELECT 1", None, Exception("refused"))

        monkeypatch.setattr(seed_module, "seed_database", down)

        assert main(["--fixture", "eval"]) == 1
        assert "make db-up" in caplog.text

    def test_reset_flag_wipes_before_seeding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(seed_module, "reset_database", lambda _session: calls.append("reset"))

        def stop(*_args: Any, **_kwargs: Any) -> None:
            calls.append("seed")
            raise SeedDataError("dừng trước khi commit")

        monkeypatch.setattr(seed_module, "seed_database", stop)

        assert main(["--fixture", "e2e", "--reset", "--yes"]) == 1
        assert calls == ["reset", "seed"]

    def test_reset_without_yes_is_refused_and_wipes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(seed_module, "reset_database", lambda _session: calls.append("reset"))
        monkeypatch.setattr(seed_module, "seed_database", lambda *_a, **_k: calls.append("seed"))

        assert main(["--fixture", "eval", "--reset"]) == 1
        assert calls == []
        assert "--yes" in caplog.text

    def test_failed_seed_after_reset_rolls_the_wipe_back(
        self, monkeypatch: pytest.MonkeyPatch, db_engine: Engine
    ) -> None:
        with Session(db_engine) as setup:
            marker = ShoppingList(name="Mock marker")
            setup.add(marker)
            setup.commit()
            marker_id = marker.id

        def broken(*_args: Any, **_kwargs: Any) -> None:
            raise SeedDataError("lỗi sau khi đã xóa")

        monkeypatch.setattr(seed_module, "seed_database", broken)
        try:
            assert main(["--fixture", "dev", "--reset", "--yes"]) == 1
            with Session(db_engine) as check:
                assert check.get(ShoppingList, marker_id) is not None
        finally:
            with Session(db_engine) as cleanup:
                leftover = cleanup.get(ShoppingList, marker_id)
                if leftover is not None:
                    cleanup.delete(leftover)
                    cleanup.commit()

    def test_without_reset_flag_nothing_is_wiped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(seed_module, "reset_database", lambda _session: calls.append("reset"))

        def stop(*_args: Any, **_kwargs: Any) -> None:
            raise SeedDataError("dừng trước khi commit")

        monkeypatch.setattr(seed_module, "seed_database", stop)

        assert main(["--fixture", "e2e"]) == 1
        assert calls == []

    def test_unknown_fixture_name_is_rejected_by_the_parser(self) -> None:
        with pytest.raises(SystemExit) as exit_info:
            main(["--fixture", "prod"])

        assert exit_info.value.code == 2
