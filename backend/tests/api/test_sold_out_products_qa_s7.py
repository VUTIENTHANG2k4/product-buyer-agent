"""QA lượt việc nhỏ 7 (T6.7): sản phẩm hết hàng ở mọi trang đi qua danh sách mua, cảnh báo, so sánh.

Seed T6.7 thêm hai sản phẩm như vậy; các endpoint dưới đây không được lỗi 500 khi `min_price` rỗng.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import Product
from app.domain.enums import StockStatus
from tests.service_support import add_offer, add_product


def sold_out_product(session: Session) -> Product:
    product = add_product(session)
    add_offer(
        session, product, price=17_990_000, stock_status=StockStatus.out_of_stock, site="gearvn"
    )
    add_offer(
        session,
        product,
        price=18_290_000,
        stock_status=StockStatus.out_of_stock,
        site="fptshop",
        url="https://mock.example/p/sold-out-2",
    )
    return product


def in_stock_product(session: Session, price: int = 20_000_000) -> Product:
    product = add_product(session)
    add_offer(session, product, price=price)
    return product


def new_list(client: TestClient) -> int:
    response = client.post("/api/lists", json={"name": "Mock hết hàng"})
    assert response.status_code == 201, response.text
    return int(response.json()["list_id"])


def test_detail_of_a_product_sold_out_everywhere_has_null_prices_and_lists_its_offers(
    client: TestClient, db_session: Session
) -> None:
    product = sold_out_product(db_session)

    response = client.get(f"/api/products/{product.id}")

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert (body["min_price"], body["max_price"]) == (None, None)
    assert [o["effective_price"] for o in body["offers"]] == [17_990_000, 18_290_000]


def test_a_sold_out_product_can_be_added_to_a_list_and_the_list_detail_has_no_price(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    sold_out = sold_out_product(db_session)
    available = in_stock_product(db_session, 20_000_000)

    for product in (sold_out, available):
        added = client.post(f"/api/lists/{list_id}/items", json={"product_id": product.id})
        assert added.status_code == 201, added.text

    detail = client.get(f"/api/lists/{list_id}")

    assert detail.status_code == 200, detail.text
    items = {item["product_id"]: item for item in detail.json()["items"]}
    assert items[sold_out.id]["current_price"] is None
    assert items[available.id]["current_price"] == 20_000_000
    assert detail.json()["total_price"] == 20_000_000
    summary = client.get("/api/lists").json()["items"]
    assert [(row["item_count"], row["total_price"]) for row in summary] == [(2, 20_000_000)]


def test_an_alert_can_be_created_for_a_product_sold_out_everywhere_and_has_no_current_price(
    client: TestClient, db_session: Session
) -> None:
    product = sold_out_product(db_session)

    response = client.post(
        "/api/alerts", json={"product_id": product.id, "target_price": 15_000_000}
    )

    assert response.status_code == 201, response.text
    assert response.json()["current_best_price"] is None
    listed = client.get("/api/alerts")
    assert listed.status_code == 200, listed.text
    assert [a["current_best_price"] for a in listed.json()["items"]] == [None]


def test_compare_ranks_only_buyable_offers_so_a_cheaper_sold_out_product_never_wins(
    client: TestClient, db_session: Session
) -> None:
    sold_out = sold_out_product(db_session)
    available = in_stock_product(db_session, 30_000_000)

    response = client.post("/api/compare", json={"product_ids": [sold_out.id, available.id]})

    assert response.status_code == 200, response.text
    assert response.json()["cheapest_product_id"] == available.id
