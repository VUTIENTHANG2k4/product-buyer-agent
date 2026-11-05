"""API xuất CSV danh sách mua: GET /lists/{id}/export.csv (X3, docs/07 §3.4)."""

import csv
import io

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.enums import StockStatus
from app.services.list_export import BOM, HEADER, TOTAL_LABEL
from tests.service_support import add_offer, add_product


def new_list(client: TestClient, name: str = "Mock danh sách") -> int:
    response = client.post("/api/lists", json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["list_id"])


def parse(body: bytes) -> list[list[str]]:
    text = body.decode("utf-8")
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text[len(BOM) :], newline="")))


def test_export_returns_csv_attachment_with_prices_from_db(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product = add_product(db_session, canonical_name="Mock Laptop Xuất")
    add_offer(db_session, product, price=20_000_000, url="https://mock.example/p/x")
    response = client.post(
        f"/api/lists/{list_id}/items",
        json={"product_id": product.id, "quantity": 2, "note": "=cmd"},
    )
    assert response.status_code == 201, response.text

    exported = client.get(f"/api/lists/{list_id}/export.csv")

    assert exported.status_code == 200
    assert exported.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        exported.headers["content-disposition"] == f'attachment; filename="danh-sach-{list_id}.csv"'
    )
    rows = parse(exported.content)
    assert rows[0] == list(HEADER)
    assert rows[1] == [
        "1",
        "Mock Laptop Xuất",
        "2",
        "20000000",
        "20000000",
        "0",
        "40000000",
        "mockshop",
        "https://mock.example/p/x",
        "'=cmd",
    ]
    assert rows[2][0] == TOTAL_LABEL and rows[2][6] == "40000000"
    detail = client.get(f"/api/lists/{list_id}").json()
    assert int(rows[2][6]) == detail["total_price"]


def test_export_reflects_current_price_and_unavailable_items(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    cheaper = add_product(db_session, canonical_name="Mock A")
    offer = add_offer(db_session, cheaper, price=10_000_000)
    gone = add_product(db_session, canonical_name="Mock B")
    gone_offer = add_offer(db_session, gone, price=5_000_000)
    for product in (cheaper, gone):
        assert client.post(
            f"/api/lists/{list_id}/items", json={"product_id": product.id}
        ).is_success
    offer.price = 9_000_000
    gone_offer.stock_status = StockStatus.out_of_stock
    db_session.add_all([offer, gone_offer])
    db_session.flush()

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[1][1:7] == ["Mock A", "1", "10000000", "9000000", "-1000000", "9000000"]
    assert rows[2][1:9] == ["Mock B", "1", "5000000", "", "", "", "", ""]
    assert rows[3][6] == "9000000"


def test_export_of_empty_list_has_header_and_zero_total(client: TestClient) -> None:
    rows = parse(client.get(f"/api/lists/{new_list(client)}/export.csv").content)
    assert rows == [list(HEADER), [TOTAL_LABEL, "", "", "", "", "", "0", "", "", ""]]


def test_export_of_unknown_list_is_404_json(client: TestClient) -> None:
    for list_id in (999_999_999, 2**31, 2**70):
        response = client.get(f"/api/lists/{list_id}/export.csv")
        assert response.status_code == 404, list_id
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"]["code"] == "LIST_NOT_FOUND"


def test_export_with_non_numeric_id_is_422(client: TestClient) -> None:
    response = client.get("/api/lists/abc/export.csv")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
