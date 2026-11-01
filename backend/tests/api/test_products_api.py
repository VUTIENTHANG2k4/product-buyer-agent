"""API danh mục: GET /products, /products/{id}, price-history, POST /compare, GET /categories."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import PriceHistory
from app.domain.enums import Category, PriceType, SiteKey, StockStatus
from tests.service_support import NOW, add_offer, add_product

INT4_OVER = 2**31
HUGE = 2**70


def laptop(session: Session, name: str, price: int, **specs: Any) -> int:
    product = add_product(
        session,
        canonical_name=name,
        brand="MockBrand",
        specs={"gpu_rank": 40, "ram_gb": 16, "is_gaming": True, **specs},
    )
    add_offer(session, product, price=price)
    assert product.id is not None
    return product.id


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# ---- GET /products ----
def test_products_returns_envelope_with_pagination_and_cheapest_first(
    client: TestClient, db_session: Session
) -> None:
    cheap = laptop(db_session, "Mock Laptop A", 20_000_000)
    laptop(db_session, "Mock Laptop B", 30_000_000)
    laptop(db_session, "Mock Laptop C", 25_000_000)

    body = client.get("/api/products", params={"page": 1, "page_size": 2}).json()

    assert body["total"] == 3
    assert (body["page"], body["page_size"]) == (1, 2)
    assert [item["min_price"] for item in body["items"]] == [20_000_000, 25_000_000]
    assert body["items"][0]["product_id"] == cheap
    assert body["stale"] is False
    assert body["data_as_of"] is not None


def test_products_second_page_continues_after_the_first(
    client: TestClient, db_session: Session
) -> None:
    for index, price in enumerate([20_000_000, 25_000_000, 30_000_000]):
        laptop(db_session, f"Mock Laptop {index}", price)

    body = client.get("/api/products", params={"page": 2, "page_size": 2}).json()

    assert [item["min_price"] for item in body["items"]] == [30_000_000]
    assert body["total"] == 3


def test_products_filters_by_category_text_price_brand_and_site(
    client: TestClient, db_session: Session
) -> None:
    keep = add_product(db_session, canonical_name="Mock Zephyr 15", brand="Zeta")
    add_offer(db_session, keep, price=22_000_000, site=SiteKey.gearvn, url="https://g.example/1")
    other = add_product(db_session, canonical_name="Mock Other 15", brand="Other")
    add_offer(db_session, other, price=22_000_000)
    mouse = add_product(db_session, category=Category.mouse, canonical_name="Mock Zephyr Mouse")
    add_offer(db_session, mouse, price=500_000, url="https://m.example/1")

    body = client.get(
        "/api/products",
        params=[
            ("category", "laptop"),
            ("q", "zephyr"),
            ("price_min", "20000000"),
            ("price_max", "25000000"),
            ("brand", "zeta"),
            ("site", "gearvn"),
        ],
    ).json()

    assert [item["product_id"] for item in body["items"]] == [keep.id]


def test_products_filters_by_spec_with_operator_suffix(
    client: TestClient, db_session: Session
) -> None:
    strong = laptop(db_session, "Mock Strong", 30_000_000, gpu_rank=50)
    laptop(db_session, "Mock Weak", 20_000_000, gpu_rank=20)

    body = client.get(
        "/api/products", params={"category": "laptop", "spec.gpu_rank__gte": "40"}
    ).json()

    assert [item["product_id"] for item in body["items"]] == [strong]


def test_products_spec_list_values_split_on_commas(client: TestClient, db_session: Session) -> None:
    wireless = add_product(
        db_session,
        category=Category.mouse,
        canonical_name="Mock Wireless Mouse",
        specs={"connection": ["wireless_2_4", "bluetooth"]},
    )
    add_offer(db_session, wireless, price=600_000)
    wired = add_product(
        db_session,
        category=Category.mouse,
        canonical_name="Mock Wired Mouse",
        specs={"connection": ["wired"]},
    )
    add_offer(db_session, wired, price=300_000, url="https://m.example/wired")

    body = client.get(
        "/api/products",
        params={"category": "mouse", "spec.connection__contains_any": "bluetooth,wireless_2_4"},
    ).json()

    assert [item["product_id"] for item in body["items"]] == [wireless.id]


def test_products_sort_updated_desc_puts_latest_scrape_first(
    client: TestClient, db_session: Session
) -> None:
    older = add_product(db_session, canonical_name="Mock Older")
    add_offer(db_session, older, price=10_000_000, scraped_at=NOW - timedelta(days=2))
    newer = add_product(db_session, canonical_name="Mock Newer")
    add_offer(db_session, newer, price=40_000_000, scraped_at=NOW)

    body = client.get("/api/products", params={"sort": "updated_desc"}).json()

    assert [item["product_id"] for item in body["items"]] == [newer.id, older.id]


def test_products_marks_data_older_than_a_day_as_stale(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session, canonical_name="Mock Old Data")
    add_offer(db_session, product, price=10_000_000, scraped_at=NOW - timedelta(hours=30))

    body = client.get("/api/products").json()

    assert body["stale"] is True


def test_products_hides_out_of_stock_offers(client: TestClient, db_session: Session) -> None:
    product = add_product(db_session, canonical_name="Mock Sold Out")
    add_offer(db_session, product, price=10_000_000, stock_status=StockStatus.out_of_stock)

    assert client.get("/api/products").json()["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"page_size": "101"},
        {"page_size": "0"},
        {"page": "0"},
        {"page": "10001"},
        {"sort": "cheapest"},
        {"category": "toaster"},
        {"site": "shopee"},
        {"price_min": "-1"},
        {"price_max": str(2**63)},
        {"q": "x" * 201},
        {"spec.gpu_rank__gte": "40"},  # thiếu category
        {"category": "laptop", "spec.nope__gte": "1"},
        {"category": "laptop", "spec.gpu_rank__contains": "4"},  # toán tử không hợp kiểu
        {"category": "laptop", "spec.gpu_rank__gte": "bốn"},
        {"category": "laptop", "spec.is_gaming": "maybe"},
        {"category": "laptop", "spec.cpu_vendor": "arm"},  # ngoài enum
        {"category": "mouse", "spec.connection__contains_any": ","},
    ],
)
def test_products_rejects_bad_parameters_with_validation_error(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get("/api/products", params=params)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_products_with_nul_in_text_filters_does_not_crash(client: TestClient) -> None:
    response = client.get("/api/products", params=[("q", "a\x00b"), ("brand", "x\x00y")])

    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---- GET /products/{id} ----
def test_product_detail_returns_specs_and_all_offers(
    client: TestClient, db_session: Session
) -> None:
    product_id = laptop(db_session, "Mock Detail", 21_000_000, ram_gb=32)
    product = add_product(db_session, canonical_name="Mock Two Offers")
    add_offer(db_session, product, price=30_000_000)
    add_offer(db_session, product, price=28_000_000, site=SiteKey.gearvn, url="https://g.example/2")

    detail = client.get(f"/api/products/{product_id}").json()
    two = client.get(f"/api/products/{product.id}").json()

    assert detail["name"] == "Mock Detail"
    assert detail["specs"]["ram_gb"] == 32
    assert detail["min_price"] == 21_000_000
    assert [offer["effective_price"] for offer in two["offers"]] == [28_000_000, 30_000_000]


@pytest.mark.parametrize("product_id", ["999999", "0", "-5", str(INT4_OVER), str(HUGE)])
def test_product_detail_unknown_or_out_of_range_id_is_404(
    client: TestClient, product_id: str
) -> None:
    response = client.get(f"/api/products/{product_id}")

    assert response.status_code == 404
    assert error_code(response) == "PRODUCT_NOT_FOUND"


def test_product_detail_non_numeric_id_is_validation_error(client: TestClient) -> None:
    assert client.get("/api/products/abc").status_code == 422


# ---- GET /products/{id}/price-history ----
def test_price_history_groups_points_by_site_with_min_and_max(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session, canonical_name="Mock History")
    offer = add_offer(db_session, product, price=27_000_000)
    assert offer.id is not None
    for days_ago, price in [(10, 29_000_000), (3, 27_000_000)]:
        db_session.add(
            PriceHistory(
                offer_id=offer.id,
                price=price,
                price_type=PriceType.regular,
                scraped_at=NOW - timedelta(days=days_ago),
            )
        )
    db_session.flush()

    body = client.get(f"/api/products/{product.id}/price-history", params={"days": 30}).json()

    assert body["min_price"] == 27_000_000
    assert body["max_price"] == 29_000_000
    assert [series["site"] for series in body["series"]] == ["mockshop"]
    assert [point["price"] for point in body["series"][0]["points"]] == [29_000_000, 27_000_000]


@pytest.mark.parametrize("days", ["0", "181", "abc"])
def test_price_history_rejects_days_outside_range(
    client: TestClient, db_session: Session, days: str
) -> None:
    product_id = laptop(db_session, "Mock History Range", 20_000_000)

    response = client.get(f"/api/products/{product_id}/price-history", params={"days": days})

    assert response.status_code == 422


def test_price_history_of_unknown_product_is_404(client: TestClient) -> None:
    response = client.get(f"/api/products/{INT4_OVER}/price-history")

    assert response.status_code == 404
    assert error_code(response) == "PRODUCT_NOT_FOUND"


# ---- POST /compare ----
def test_compare_returns_differences_and_cheapest(client: TestClient, db_session: Session) -> None:
    first = laptop(db_session, "Mock Compare A", 25_000_000, ram_gb=16)
    second = laptop(db_session, "Mock Compare B", 22_000_000, ram_gb=32)

    body = client.post("/api/compare", json={"product_ids": [first, second]}).json()

    assert [product["product_id"] for product in body["products"]] == [first, second]
    assert body["differing_fields"] == ["ram_gb"]
    assert body["cheapest_product_id"] == second


@pytest.mark.parametrize(
    "payload",
    [
        {"product_ids": [1]},
        {"product_ids": [1, 2, 3, 4, 5, 6]},
        {"product_ids": []},
        {"product_ids": ["a", "b"]},
        {},
    ],
)
def test_compare_rejects_wrong_number_of_products(
    client: TestClient, payload: dict[str, Any]
) -> None:
    response = client.post("/api/compare", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_compare_duplicate_ids_is_validation_error(client: TestClient, db_session: Session) -> None:
    product_id = laptop(db_session, "Mock Compare Dup", 20_000_000)

    response = client.post("/api/compare", json={"product_ids": [product_id, product_id]})

    assert response.status_code == 422


@pytest.mark.parametrize("missing", [999_999, INT4_OVER, HUGE])
def test_compare_with_a_missing_product_is_404_naming_it(
    client: TestClient, db_session: Session, missing: int
) -> None:
    product_id = laptop(db_session, "Mock Compare Exists", 20_000_000)

    response = client.post("/api/compare", json={"product_ids": [product_id, missing]})

    assert response.status_code == 404
    assert error_code(response) == "PRODUCT_NOT_FOUND"
    assert response.json()["error"]["details"]["product_ids"] == [missing]


# ---- GET /categories ----
def test_categories_lists_tiers_counts_and_filter_fields(
    client: TestClient, db_session: Session
) -> None:
    laptop(db_session, "Mock Count A", 20_000_000)
    laptop(db_session, "Mock Count B", 21_000_000)
    inactive = add_product(db_session, canonical_name="Mock No Offers")
    add_offer(db_session, inactive, price=10_000_000, is_active=False)

    items = {item["key"]: item for item in client.get("/api/categories").json()["items"]}

    assert set(items) == {"laptop", "mouse", "keyboard", "headset", "phone", "other"}
    assert items["laptop"]["tier"] == 1
    assert items["laptop"]["product_count"] == 2
    assert items["mouse"]["product_count"] == 0
    assert items["other"]["tier"] == 2
    assert items["other"]["filter_fields"] == []
    fields = {field["name"]: field for field in items["laptop"]["filter_fields"]}
    assert fields["gpu_rank"] == {
        "name": "gpu_rank",
        "kind": "integer",
        "ops": ["eq", "gte", "lte"],
        "choices": None,
    }
    assert fields["storage_type"]["choices"]
    connection = {f["name"]: f for f in items["keyboard"]["filter_fields"]}["connection"]
    assert connection["kind"] == "list"
    assert connection["ops"] == ["contains", "contains_any"]


def test_categories_filter_fields_are_accepted_by_products_endpoint(client: TestClient) -> None:
    """Mọi trường/toán tử mà /categories công bố đều dùng được ở /products."""
    categories = client.get("/api/categories").json()["items"]
    for category in categories:
        for field in category["filter_fields"]:
            for op in field["ops"]:
                value = {"integer": "1", "number": "1.5", "boolean": "true"}.get(field["kind"], "x")
                if field["choices"]:
                    value = field["choices"][0]
                if op in ("in", "contains_any"):
                    value = f"{value},{value}"
                params = {"category": category["key"], f"spec.{field['name']}__{op}": value}

                response = client.get("/api/products", params=params)

                assert response.status_code == 200, (params, response.text)
