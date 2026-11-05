"""QA X3: test biên cho GET /api/lists/{id}/export.csv (docs/07 §3.4)."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.enums import StockStatus
from app.services.list_export import BOM, HEADER, TOTAL_LABEL
from tests.service_support import add_offer, add_product


def new_list(client: TestClient, name: str = "Mock danh sách QA") -> int:
    response = client.post("/api/lists", json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["list_id"])


def parse(body: bytes) -> list[list[str]]:
    assert body.startswith(b"\xef\xbb\xbf")
    assert not body[3:].startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8")
    return list(csv.reader(io.StringIO(text[len(BOM) :], newline="")))


def add_item(client: TestClient, list_id: int, **body: object) -> dict[str, object]:
    response = client.post(f"/api/lists/{list_id}/items", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()
    return data


def test_csv_rows_match_get_detail_values_and_order_qa_x3(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    names = ["Mock Zeta", "Mock Alpha", "Mock Mu", "Mock Beta", "Mock Omega"]
    for index, name in enumerate(names):
        product = add_product(db_session, canonical_name=name)
        add_offer(
            db_session,
            product,
            price=1_000_000 * (index + 1),
            url=f"https://mock.example/p/{index}",
        )
        add_item(client, list_id, product_id=product.id, quantity=index + 1, note=f"n{index}")
    detail = client.get(f"/api/lists/{list_id}").json()

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[0] == list(HEADER)
    assert len(rows) == len(detail["items"]) + 2
    for position, (row, item) in enumerate(zip(rows[1:-1], detail["items"], strict=True), 1):
        offer = item["best_offer"]
        assert row == [
            str(position),
            item["name"],
            str(item["quantity"]),
            str(item["price_at_add"]),
            str(item["current_price"]),
            str(item["price_delta"]),
            str(item["quantity"] * item["current_price"]),
            offer["site"],
            offer["url"],
            item["note"],
        ]
    assert rows[-1][0] == TOTAL_LABEL
    assert int(rows[-1][6]) == detail["total_price"] == sum(int(r[6]) for r in rows[1:-1])


def test_csv_reflects_patch_and_delete_of_items_qa_x3(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    a = add_product(db_session, canonical_name="Mock A")
    add_offer(db_session, a, price=2_000_000)
    b = add_product(db_session, canonical_name="Mock B")
    add_offer(db_session, b, price=3_000_000)
    item_a = add_item(client, list_id, product_id=a.id, note="cũ")
    item_b = add_item(client, list_id, product_id=b.id)
    patched = client.patch(
        f"/api/lists/{list_id}/items/{item_a['item_id']}", json={"quantity": 4, "note": None}
    )
    assert patched.status_code == 200, patched.text
    assert client.delete(f"/api/lists/{list_id}/items/{item_b['item_id']}").status_code == 204

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert len(rows) == 3
    assert rows[1][1:3] == ["Mock A", "4"]
    assert rows[1][9] == ""
    assert rows[2] == [TOTAL_LABEL, "", "", "", "", "", "8000000", "", "", ""]


def test_injection_in_scraped_name_and_user_note_is_neutralised_end_to_end_qa_x3(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client, name="=cmd|' /C calc'!A0")
    product = add_product(db_session, canonical_name='@SUM(1+1)*cmd|" /C calc"!A0')
    add_offer(db_session, product, price=1_000_000)
    add_item(client, list_id, product_id=product.id, note='-2+3+cmd|" /C calc"!A0')

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[1][1] == '\'@SUM(1+1)*cmd|" /C calc"!A0'
    assert rows[1][9] == '\'-2+3+cmd|" /C calc"!A0'
    # Tên danh sách không có trong CSV (chỉ ở tên tệp theo id).
    assert all("cmd|' /C" not in cell for row in rows for cell in row)


def test_vietnamese_long_note_and_emoji_round_trip_through_http_qa_x3(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product = add_product(db_session, canonical_name='Màn hình Mock 27" 4K, IPS')
    add_offer(db_session, product, price=7_490_000)
    note = ('Mua cho bố 👨‍💻, "gấp"\r\nđặt trước; ' * 30)[:500]
    add_item(client, list_id, product_id=product.id, note=note)

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[1][1] == 'Màn hình Mock 27" 4K, IPS'
    assert rows[1][9] == note
    assert len(rows) == 3


def test_line_total_near_trillion_is_exact_qa_x3(client: TestClient, db_session: Session) -> None:
    list_id = new_list(client)
    product = add_product(db_session, canonical_name="Mock giá lớn")
    add_offer(db_session, product, price=999_999_999)
    add_item(client, list_id, product_id=product.id, quantity=1000)

    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[1][6] == "999999999000"
    assert rows[2][6] == "999999999000"


def test_out_of_stock_preferred_offer_falls_back_like_detail_qa_x3(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product = add_product(db_session, canonical_name="Mock dự phòng")
    add_offer(db_session, product, price=5_000_000, url="https://mock.example/p/fallback")
    preferred = add_offer(
        db_session, product, price=6_000_000, url="https://mock.example/p/preferred"
    )
    add_item(client, list_id, product_id=product.id, preferred_offer_id=preferred.id)
    preferred.stock_status = StockStatus.out_of_stock
    db_session.add(preferred)
    db_session.flush()

    detail = client.get(f"/api/lists/{list_id}").json()
    rows = parse(client.get(f"/api/lists/{list_id}/export.csv").content)

    assert rows[1][4] == str(detail["items"][0]["current_price"]) == "5000000"
    assert rows[1][8] == detail["items"][0]["best_offer"]["url"]


def test_export_after_list_deleted_is_404_qa_x3(client: TestClient) -> None:
    list_id = new_list(client)
    assert client.get(f"/api/lists/{list_id}/export.csv").status_code == 200
    assert client.delete(f"/api/lists/{list_id}").status_code == 204

    response = client.get(f"/api/lists/{list_id}/export.csv")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIST_NOT_FOUND"
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("list_id", ["0", "-1", "-9223372036854775809"])
def test_export_with_zero_or_negative_id_is_404_json_qa_x3(
    client: TestClient, list_id: str
) -> None:
    response = client.get(f"/api/lists/{list_id}/export.csv")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIST_NOT_FOUND"


@pytest.mark.parametrize("list_id", ["1.5", "1e3", "%20", "١"])
def test_export_with_malformed_id_is_422_qa_x3(client: TestClient, list_id: str) -> None:
    response = client.get(f"/api/lists/{list_id}/export.csv")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_export_rejects_write_methods_with_405_qa_x3(client: TestClient, method: str) -> None:
    list_id = new_list(client)
    response = client.request(method, f"/api/lists/{list_id}/export.csv")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["allow"]


def test_export_head_does_not_500_qa_x3(client: TestClient) -> None:
    list_id = new_list(client)
    response = client.head(f"/api/lists/{list_id}/export.csv")
    assert response.status_code in (200, 405)
    assert response.content == b""


def test_export_does_not_modify_list_updated_at_qa_x3(client: TestClient) -> None:
    list_id = new_list(client)
    before = client.get(f"/api/lists/{list_id}").json()["updated_at"]
    client.get(f"/api/lists/{list_id}/export.csv")
    assert client.get(f"/api/lists/{list_id}").json()["updated_at"] == before
