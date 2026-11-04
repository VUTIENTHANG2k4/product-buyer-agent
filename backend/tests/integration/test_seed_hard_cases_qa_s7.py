"""QA lượt việc nhỏ 7 (T6.7): 4 sản phẩm "ca khó" của seed nhìn từ catalog, tìm kiếm và API.

Hai sản phẩm thiếu thông số bắt buộc (`incomplete_specs`) và hai sản phẩm hết hàng ở mọi trang.
Module giữ một transaction seed `eval` suốt module (xem `test_seed_data.py`): test cần `db_session`
riêng (seed lại, ghi dữ liệu) nằm ở module khác.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.api.deps import get_catalog_service, get_compare_service, get_session
from app.config import Settings, get_settings
from app.db.models import Offer, Product
from app.db.repositories import ProductQuery, ProductRepository
from app.domain.catalog import CatalogFilters
from app.domain.dto import SpecFilter
from app.domain.enums import Category, StockStatus
from app.main import create_app
from app.normalize.extract import specs_confidence
from app.normalize.specs import REQUIRED_FIELDS
from app.services.catalog_service import CatalogService
from app.services.compare_service import CompareService
from scripts.eval_core import Constraint, ProductFacts, satisfies
from scripts.seed import FIXTURE_DIR, load_catalog, seed_database
from tests.integration.test_seed_data import SEARCH_CASES, build_query
from tests.service_support import make_settings

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

ACER_NOSPEC = "MOCK-ACER-NOSPEC"
AKKO_NOSPEC = "MOCK-AKKO-5075-NOSPEC"
MSI_SOLDOUT = "MOCK-MSI-SOLDOUT"
LOGITECH_SOLDOUT = "MOCK-LOG-G203-SOLDOUT"
INCOMPLETE = {ACER_NOSPEC, AKKO_NOSPEC}
SOLD_OUT = {MSI_SOLDOUT, LOGITECH_SOLDOUT}
HARD_CASES = INCOMPLETE | SOLD_OUT


@pytest.fixture(scope="module")
def seeded(db_engine: Engine) -> Iterator[Session]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        seed_database(session, "eval", now=NOW)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="module")
def client(seeded: Session) -> Iterator[TestClient]:
    app = create_app()
    settings: Settings = make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: seeded
    app.dependency_overrides[get_catalog_service] = lambda: CatalogService(seeded)
    app.dependency_overrides[get_compare_service] = lambda: CompareService(seeded)
    with TestClient(app) as test_client:
        yield test_client


def product_of(session: Session, model_code: str) -> Product:
    return session.exec(select(Product).where(Product.model_code == model_code)).one()


def pid(session: Session, model_code: str) -> int:
    product_id = product_of(session, model_code).id
    assert product_id is not None
    return product_id


# ---------------------------------------------------------------- khai báo trong fixture
def test_the_hard_cases_are_exactly_the_flagged_or_sold_out_products_of_the_catalog() -> None:
    catalog = load_catalog(FIXTURE_DIR)

    flagged = {item.product.model_code for item in catalog if item.product.incomplete_specs}
    sold_out = {
        item.product.model_code
        for item in catalog
        if all(offer.stock_status is StockStatus.out_of_stock for offer in item.product.offers)
    }

    assert flagged == INCOMPLETE
    assert sold_out == SOLD_OUT


def test_no_hard_case_is_tagged_for_the_e2e_profile_and_the_e2e_catalog_is_complete() -> None:
    catalog = load_catalog(FIXTURE_DIR)

    e2e = [item for item in catalog if item.product.e2e]
    tagged = {item.product.model_code for item in e2e}

    assert tagged.isdisjoint(HARD_CASES)
    assert e2e and all(not item.product.incomplete_specs for item in e2e)
    assert all(
        any(o.stock_status is not StockStatus.out_of_stock for o in item.product.offers)
        for item in e2e
    )


def test_incomplete_flag_is_only_set_when_a_required_field_is_really_missing() -> None:
    for item in load_catalog(FIXTURE_DIR):
        missing = [f for f in REQUIRED_FIELDS[item.category] if not item.specs.get(f)]
        assert bool(missing) == item.product.incomplete_specs, item.product.canonical_name


# ---------------------------------------------------------------- specs_confidence trong DB
def test_incomplete_products_are_stored_with_a_low_but_consistent_specs_confidence(
    seeded: Session,
) -> None:
    acer = product_of(seeded, ACER_NOSPEC)
    akko = product_of(seeded, AKKO_NOSPEC)

    assert acer.specs_confidence == specs_confidence(Category.laptop, acer.specs)
    assert 0.2 < acer.specs_confidence < 0.3  # 2 trong 4 trường bắt buộc
    assert akko.specs_confidence == 0.0  # 0 trong 2 trường bắt buộc
    assert "gpu_model" not in acer.specs and "storage_gb" not in acer.specs
    assert "switch_type" not in akko.specs and "connection" not in akko.specs


def test_sold_out_products_have_complete_specs_and_full_confidence(seeded: Session) -> None:
    for code in SOLD_OUT:
        product = product_of(seeded, code)
        assert product.specs_confidence == 1.0, code
        assert all(product.specs.get(f) for f in REQUIRED_FIELDS[product.category]), code


# ---------------------------------------------------------------- tìm kiếm
@pytest.mark.parametrize("code", sorted(SOLD_OUT))
def test_a_product_sold_out_everywhere_is_hidden_from_default_search_even_by_exact_name(
    seeded: Session, code: str
) -> None:
    product = product_of(seeded, code)
    page = ProductRepository(seeded).search(ProductQuery(text=code, limit=100))
    by_name = ProductRepository(seeded).search(
        ProductQuery(text=product.canonical_name, category=product.category, limit=100)
    )

    assert page.total == 0 and by_name.total == 0


@pytest.mark.parametrize("code", sorted(SOLD_OUT))
def test_a_product_sold_out_everywhere_is_listed_when_out_of_stock_is_included(
    seeded: Session, code: str
) -> None:
    product = product_of(seeded, code)
    offers = seeded.exec(select(Offer).where(Offer.product_id == product.id)).all()
    prices = sorted(offer.price for offer in offers)

    result = CatalogService(seeded).search(
        CatalogFilters(q=code, include_out_of_stock=True, limit=10)
    )

    assert [item.product_id for item in result.items] == [product.id]
    item = result.items[0]
    assert (item.min_price, item.max_price, item.offers_count) == (prices[0], prices[-1], 2)
    assert item.in_stock is False
    assert item.best_offer.stock_status is StockStatus.out_of_stock


def test_sold_out_products_are_hidden_for_every_eval_search_case(seeded: Session) -> None:
    hidden = {pid(seeded, code) for code in SOLD_OUT}
    leaked = [
        case["id"]
        for case in SEARCH_CASES
        for hit in ProductRepository(seeded).search(build_query(case)).items
        if hit.product.id in hidden
    ]

    assert leaked == []


@pytest.mark.parametrize("case", SEARCH_CASES, ids=lambda case: case["id"])
def test_every_search_result_satisfies_the_constraints_of_its_eval_case(
    seeded: Session, case: dict[str, Any]
) -> None:
    """Sản phẩm thiếu thông số (Acer/Akko ca khó) mà lọt vào kết quả sẽ làm câu eval chấm hỏng."""
    parsed = [Constraint.model_validate(c) for c in case["expected"].get("constraints", [])]
    hits = ProductRepository(seeded).search(build_query(case)).items
    offers_sites = {
        hit.product.id: {
            offer.site.value
            for offer in seeded.exec(select(Offer).where(Offer.product_id == hit.product.id))
            if offer.is_active and offer.stock_status is not StockStatus.out_of_stock
        }
        for hit in hits
    }
    failing = [
        hit.product.canonical_name
        for hit in hits
        if not all(
            satisfies(
                ProductFacts(
                    product_id=hit.product.id or 0,
                    brand=hit.product.brand,
                    min_price=hit.min_price,
                    sites=frozenset(offers_sites[hit.product.id]),
                    specs=hit.product.specs,
                ),
                constraint,
            )
            for constraint in parsed
        )
    ]

    assert failing == []


def test_the_incomplete_laptop_is_still_found_by_a_search_without_spec_filters(
    seeded: Session,
) -> None:
    acer = pid(seeded, ACER_NOSPEC)

    page = ProductRepository(seeded).search(
        ProductQuery(category=Category.laptop, price_max=15_000_000, limit=100)
    )

    assert acer in {hit.product.id for hit in page.items}


def test_the_incomplete_laptop_is_excluded_by_a_filter_on_a_spec_it_lacks(seeded: Session) -> None:
    acer = pid(seeded, ACER_NOSPEC)
    for spec_filter in (
        SpecFilter(field="gpu_rank", op="gte", value=1),
        SpecFilter(field="storage_gb", op="gte", value=1),
    ):
        page = ProductRepository(seeded).search(
            ProductQuery(category=Category.laptop, spec_filters=[spec_filter], limit=100)
        )

        assert acer not in {hit.product.id for hit in page.items}, spec_filter


# ---------------------------------------------------------------- API
def test_get_product_sold_out_everywhere_returns_null_prices_and_all_its_offers(
    client: TestClient, seeded: Session
) -> None:
    for code, category in ((MSI_SOLDOUT, "laptop"), (LOGITECH_SOLDOUT, "mouse")):
        response = client.get(f"/api/products/{pid(seeded, code)}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["category"] == category
        assert (body["min_price"], body["max_price"]) == (None, None)
        assert len(body["offers"]) == 2
        assert {offer["stock_status"] for offer in body["offers"]} == {"out_of_stock"}
        assert all(offer["effective_price"] > 0 for offer in body["offers"])
        assert body["specs_confidence"] == 1.0 and body["specs"]


def test_get_product_incomplete_specs_returns_low_confidence_and_a_real_price(
    client: TestClient, seeded: Session
) -> None:
    body = client.get(f"/api/products/{pid(seeded, ACER_NOSPEC)}").json()

    assert body["min_price"] == 14_490_000 == body["max_price"]
    assert body["specs_confidence"] < 0.5
    assert body["specs"]["ram_gb"] == 8
    assert "gpu_model" not in body["specs"]


def test_price_history_of_a_product_sold_out_everywhere_is_still_available(
    client: TestClient, seeded: Session
) -> None:
    response = client.get(f"/api/products/{pid(seeded, LOGITECH_SOLDOUT)}/price-history")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {series["site"] for series in body["series"]} == {"gearvn", "anphat"}
    assert body["min_price"] == 299_000


def test_list_endpoint_does_not_return_a_sold_out_product_by_default(
    client: TestClient, seeded: Session
) -> None:
    sold_out_laptop = pid(seeded, MSI_SOLDOUT)
    sold_out_mouse = pid(seeded, LOGITECH_SOLDOUT)

    ids: set[int] = set()
    searches: list[dict[str, Any]] = [
        {"category": "laptop", "page_size": 100},
        {"category": "mouse", "brand": "Logitech", "page_size": 100, "sort": "price_asc"},
        {"q": "Mock", "page_size": 100},
    ]
    for params in searches:
        response = client.get("/api/products", params=params)
        assert response.status_code == 200, response.text
        ids |= {item["product_id"] for item in response.json()["items"]}

    assert sold_out_laptop not in ids and sold_out_mouse not in ids


def test_cheapest_logitech_mouse_ignores_the_cheaper_sold_out_one(
    client: TestClient, seeded: Session
) -> None:
    items = client.get(
        "/api/products",
        params={"category": "mouse", "brand": "Logitech", "sort": "price_asc", "page_size": 5},
    ).json()["items"]

    assert items[0]["product_id"] != pid(seeded, LOGITECH_SOLDOUT)
    assert items[0]["min_price"] > 319_000
    assert items[0]["in_stock"] is True


def test_compare_a_sold_out_laptop_with_an_in_stock_one_picks_the_in_stock_as_cheapest(
    client: TestClient, seeded: Session
) -> None:
    in_stock = pid(seeded, ACER_NOSPEC)
    sold_out = pid(seeded, MSI_SOLDOUT)

    response = client.post("/api/compare", json={"product_ids": [sold_out, in_stock]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cheapest_product_id"] == in_stock
    assert [p["product_id"] for p in body["products"]] == [sold_out, in_stock]
    assert body["products"][0]["min_price"] is None
    assert "gpu_model" in body["differing_fields"]


def test_compare_two_products_without_any_buyable_offer_has_no_cheapest(
    client: TestClient, seeded: Session
) -> None:
    mouse = pid(seeded, LOGITECH_SOLDOUT)
    other_sold_out = pid(seeded, MSI_SOLDOUT)

    response = client.post("/api/compare", json={"product_ids": [mouse, other_sold_out]})

    assert response.status_code == 200, response.text
    assert response.json()["cheapest_product_id"] is None
