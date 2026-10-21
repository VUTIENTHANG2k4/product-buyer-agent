"""API danh sách mua: /lists và /lists/{id}/items (docs/07 §3.4)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import Offer, Product
from app.domain.catalog import MAX_QUANTITY
from tests.service_support import add_offer, add_product

INT4_OVER = 2**31
HUGE = 2**70


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def new_list(client: TestClient, name: str = "Mock danh sách") -> int:
    response = client.post("/api/lists", json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["list_id"])


def product_with_offer(session: Session, price: int = 20_000_000) -> tuple[Product, Offer]:
    product = add_product(session)
    return product, add_offer(session, product, price=price)


def add_item(client: TestClient, list_id: int, product: Product, **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/lists/{list_id}/items", json={"product_id": product.id, **body})
    assert response.status_code == 201, response.text
    item: dict[str, Any] = response.json()
    return item


# ---- danh sách ----
def test_create_list_returns_201_with_empty_summary(client: TestClient) -> None:
    response = client.post("/api/lists", json={"name": "  Máy   đồ án "})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Máy đồ án"
    assert (body["item_count"], body["total_price"]) == (0, 0)


@pytest.mark.parametrize(
    "payload",
    [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"name": "a\x00b"}, {"name": 5}],
)
def test_create_list_rejects_bad_names(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/api/lists", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_lists_are_listed_with_item_count_and_total_price(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session, 20_000_000)
    add_item(client, list_id, product, quantity=2)

    items = client.get("/api/lists").json()["items"]

    assert [(row["list_id"], row["item_count"], row["total_price"]) for row in items] == [
        (list_id, 1, 40_000_000)
    ]


def test_list_detail_shows_price_delta_against_the_price_at_add(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session, 20_000_000)
    add_item(client, list_id, product)
    add_offer(db_session, product, price=18_000_000, url="https://mock.example/cheaper")

    detail = client.get(f"/api/lists/{list_id}").json()

    (item,) = detail["items"]
    assert item["price_at_add"] == 20_000_000
    assert item["current_price"] == 18_000_000
    assert item["price_delta"] == -2_000_000
    assert detail["total_price"] == 18_000_000


def test_rename_list(client: TestClient) -> None:
    list_id = new_list(client, "Cũ")

    response = client.patch(f"/api/lists/{list_id}", json={"name": "Mới"})

    assert response.status_code == 200
    assert response.json()["name"] == "Mới"
    assert client.get(f"/api/lists/{list_id}").json()["name"] == "Mới"


def test_delete_list_returns_204_without_body_and_removes_it(client: TestClient) -> None:
    list_id = new_list(client)

    response = client.delete(f"/api/lists/{list_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/lists/{list_id}").status_code == 404


@pytest.mark.parametrize("list_id", ["999999", "0", "-1", str(INT4_OVER), str(HUGE)])
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("patch", "", {"name": "x"}),
        ("delete", "", None),
        ("post", "/items", {"product_id": 1}),
        ("patch", "/items/1", {"quantity": 2}),
        ("delete", "/items/1", None),
    ],
)
def test_unknown_or_out_of_range_list_id_is_404_list_not_found(
    client: TestClient, list_id: str, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"/api/lists/{list_id}{suffix}", json=body)

    assert response.status_code == 404
    assert error_code(response) == "LIST_NOT_FOUND"


def test_non_numeric_list_id_is_validation_error(client: TestClient) -> None:
    assert client.get("/api/lists/abc").status_code == 422


# ---- mục ----
def test_add_item_returns_201_with_current_price(client: TestClient, db_session: Session) -> None:
    list_id = new_list(client)
    product, offer = product_with_offer(db_session, 25_000_000)

    item = add_item(client, list_id, product, quantity=2, note="cho đồ án")

    assert (item["quantity"], item["note"]) == (2, "cho đồ án")
    assert item["price_at_add"] == item["current_price"] == 25_000_000
    assert item["best_offer"]["offer_id"] == offer.id


def test_adding_the_same_product_again_increases_quantity(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)
    add_item(client, list_id, product, quantity=1)

    again = add_item(client, list_id, product, quantity=3)

    assert again["quantity"] == 4
    assert len(client.get(f"/api/lists/{list_id}").json()["items"]) == 1


@pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY + 1])
def test_add_item_rejects_quantity_outside_range(
    client: TestClient, db_session: Session, quantity: int
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)

    response = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "quantity": quantity}
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_adding_quantity_beyond_the_limit_by_accumulation_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)
    add_item(client, list_id, product, quantity=MAX_QUANTITY)

    response = client.post(f"/api/lists/{list_id}/items", json={"product_id": product.id})

    assert response.status_code == 422


@pytest.mark.parametrize("product_id", [999_999, 0, INT4_OVER, HUGE])
def test_add_item_with_unknown_product_is_404(client: TestClient, product_id: int) -> None:
    list_id = new_list(client)

    response = client.post(f"/api/lists/{list_id}/items", json={"product_id": product_id})

    assert response.status_code == 404
    assert error_code(response) == "PRODUCT_NOT_FOUND"


@pytest.mark.parametrize("note", ["x" * 501, "a\x00b"])
def test_add_item_rejects_a_note_that_is_too_long_or_has_nul(
    client: TestClient, db_session: Session, note: str
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)

    response = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "note": note}
    )

    assert response.status_code == 422


def test_add_item_with_preferred_offer_uses_its_price(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session, 20_000_000)
    pricier = add_offer(db_session, product, price=26_000_000, url="https://mock.example/pricier")

    item = add_item(client, list_id, product, preferred_offer_id=pricier.id)

    assert item["price_at_add"] == 26_000_000
    assert item["preferred_offer_id"] == pricier.id


@pytest.mark.parametrize("bad_offer", [999_999, INT4_OVER, HUGE])
def test_add_item_with_unknown_preferred_offer_is_validation_error(
    client: TestClient, db_session: Session, bad_offer: int
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)

    response = client.post(
        f"/api/lists/{list_id}/items",
        json={"product_id": product.id, "preferred_offer_id": bad_offer},
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_patch_item_changes_quantity_note_and_preferred_offer(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session, 20_000_000)
    other = add_offer(db_session, product, price=22_000_000, url="https://mock.example/other")
    item_id = add_item(client, list_id, product)["item_id"]

    response = client.patch(
        f"/api/lists/{list_id}/items/{item_id}",
        json={"quantity": 3, "note": "màu đen", "preferred_offer_id": other.id},
    )

    assert response.status_code == 200
    item = response.json()
    assert (item["quantity"], item["note"], item["preferred_offer_id"]) == (3, "màu đen", other.id)
    assert item["current_price"] == 22_000_000
    assert item["price_at_add"] == 20_000_000


def test_patch_item_null_clears_note_and_preferred_offer_while_absent_keeps_them(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, offer = product_with_offer(db_session)
    item_id = add_item(client, list_id, product, note="giữ", preferred_offer_id=offer.id)["item_id"]
    url = f"/api/lists/{list_id}/items/{item_id}"

    kept = client.patch(url, json={"quantity": 2}).json()
    cleared = client.patch(url, json={"note": None, "preferred_offer_id": None}).json()

    assert (kept["note"], kept["preferred_offer_id"]) == ("giữ", offer.id)
    assert (cleared["note"], cleared["preferred_offer_id"]) == (None, None)
    assert cleared["quantity"] == 2


def test_patch_item_rejects_a_preferred_offer_of_another_product_and_changes_nothing(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)
    _, foreign_offer = product_with_offer(db_session)
    item_id = add_item(client, list_id, product)["item_id"]

    response = client.patch(
        f"/api/lists/{list_id}/items/{item_id}",
        json={"quantity": 9, "preferred_offer_id": foreign_offer.id},
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    stored = client.get(f"/api/lists/{list_id}").json()["items"][0]
    assert (stored["quantity"], stored["preferred_offer_id"]) == (1, None)


@pytest.mark.parametrize("payload", [{"quantity": 0}, {"quantity": None}, {"quantity": "many"}])
def test_patch_item_rejects_bad_quantity(
    client: TestClient, db_session: Session, payload: dict[str, Any]
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)
    item_id = add_item(client, list_id, product)["item_id"]

    response = client.patch(f"/api/lists/{list_id}/items/{item_id}", json=payload)

    assert response.status_code == 422


def test_patch_and_delete_item_of_another_list_is_404(
    client: TestClient, db_session: Session
) -> None:
    first = new_list(client, "Một")
    second = new_list(client, "Hai")
    product, _ = product_with_offer(db_session)
    item_id = add_item(client, first, product)["item_id"]

    patched = client.patch(f"/api/lists/{second}/items/{item_id}", json={"quantity": 2})
    deleted = client.delete(f"/api/lists/{second}/items/{item_id}")

    assert patched.status_code == deleted.status_code == 404
    assert error_code(patched) == "LIST_NOT_FOUND"


def test_delete_item_returns_204_and_updates_the_total(
    client: TestClient, db_session: Session
) -> None:
    list_id = new_list(client)
    product, _ = product_with_offer(db_session)
    item_id = add_item(client, list_id, product)["item_id"]

    response = client.delete(f"/api/lists/{list_id}/items/{item_id}")

    assert response.status_code == 204
    assert client.get(f"/api/lists/{list_id}").json()["items"] == []
    assert client.get("/api/lists").json()["items"][0]["total_price"] == 0
