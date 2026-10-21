"""API cảnh báo giá: /alerts (docs/07 §3.5)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import Product
from tests.service_support import add_offer, add_product

INT4_OVER = 2**31
HUGE = 2**70


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def priced_product(session: Session, price: int = 27_000_000) -> Product:
    product = add_product(session)
    add_offer(session, product, price=price)
    return product


def create_alert(
    client: TestClient, product: Product, target: int = 25_000_000, **extra: Any
) -> Any:
    return client.post(
        "/api/alerts", json={"product_id": product.id, "target_price": target, **extra}
    )


# ---- tạo / xem ----
def test_create_alert_uses_the_configured_default_channel_and_destination(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session, 27_000_000)

    response = create_alert(client, product)

    assert response.status_code == 201
    alert = response.json()
    assert alert["status"] == "active"
    assert (alert["channel"], alert["destination"]) == ("email", "mock@example.com")
    assert alert["target_price"] == 25_000_000
    assert alert["current_best_price"] == 27_000_000
    assert alert["product_name"] == product.canonical_name


def test_create_alert_with_explicit_destination_is_normalised(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session)

    response = create_alert(client, product, channel="email", destination="  Me@Example.COM ")

    assert response.json()["destination"] == "me@example.com"


def test_duplicate_alert_is_409_naming_the_existing_one(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session)
    first = create_alert(client, product).json()

    response = create_alert(client, product)

    assert response.status_code == 409
    assert error_code(response) == "DUPLICATE_ALERT"
    assert response.json()["error"]["details"]["alert_id"] == first["alert_id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"target_price": 1},
        {"product_id": 1},
        {"product_id": 1, "target_price": 0},
        {"product_id": 1, "target_price": -5},
        {"product_id": 1, "target_price": 2**63},
        {"product_id": 1, "target_price": "25000000"},
        {"product_id": 1, "target_price": 2.5},
        {"product_id": 1, "target_price": 100, "channel": "sms"},
        {"product_id": 1, "target_price": 100, "destination": "   "},
    ],
)
def test_create_alert_rejects_bad_bodies(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/api/alerts", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


@pytest.mark.parametrize("product_id", [999_999, 0, INT4_OVER, HUGE])
def test_create_alert_for_unknown_product_is_404(client: TestClient, product_id: int) -> None:
    response = client.post("/api/alerts", json={"product_id": product_id, "target_price": 100})

    assert response.status_code == 404
    assert error_code(response) == "PRODUCT_NOT_FOUND"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"channel": "telegram"}, "kênh telegram"),  # chưa cấu hình TELEGRAM_CHAT_ID
        ({"destination": "không-phải-email"}, "email"),
        ({"destination": "a\x00@b.vn"}, "không hợp lệ"),
        ({"destination": "x" * 400 + "@b.vn"}, "quá dài"),
    ],
)
def test_create_alert_with_missing_or_invalid_destination_is_validation_error(
    client: TestClient, db_session: Session, extra: dict[str, Any], message: str
) -> None:
    product = priced_product(db_session)

    response = create_alert(client, product, **extra)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert message in response.json()["error"]["message"]


def test_alerts_are_listed_newest_first_and_filtered_by_status(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session)
    first = create_alert(client, product, 25_000_000).json()
    second = create_alert(client, product, 24_000_000).json()
    client.patch(f"/api/alerts/{first['alert_id']}", json={"status": "paused"})

    everything = client.get("/api/alerts").json()["items"]
    paused = client.get("/api/alerts", params={"status": "paused"}).json()["items"]
    active = client.get("/api/alerts", params={"status": "active"}).json()["items"]

    assert [a["alert_id"] for a in everything] == [second["alert_id"], first["alert_id"]]
    assert [a["alert_id"] for a in paused] == [first["alert_id"]]
    assert [a["alert_id"] for a in active] == [second["alert_id"]]


def test_alerts_rejects_unknown_status_filter(client: TestClient) -> None:
    assert client.get("/api/alerts", params={"status": "sleeping"}).status_code == 422


# ---- sửa / xóa ----
def test_patch_alert_changes_target_and_pauses(client: TestClient, db_session: Session) -> None:
    product = priced_product(db_session)
    alert_id = create_alert(client, product).json()["alert_id"]

    response = client.patch(
        f"/api/alerts/{alert_id}", json={"target_price": 23_000_000, "status": "paused"}
    )

    assert response.status_code == 200
    assert (response.json()["target_price"], response.json()["status"]) == (23_000_000, "paused")


def test_patch_alert_to_a_duplicate_threshold_is_409(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session)
    create_alert(client, product, 25_000_000)
    other = create_alert(client, product, 24_000_000).json()["alert_id"]

    response = client.patch(f"/api/alerts/{other}", json={"target_price": 25_000_000})

    assert response.status_code == 409
    assert error_code(response) == "DUPLICATE_ALERT"


@pytest.mark.parametrize(
    "payload",
    [{"status": "triggered"}, {"status": "deleted"}, {"target_price": 0}, {"target_price": 2**63}],
)
def test_patch_alert_rejects_values_the_user_may_not_set(
    client: TestClient, db_session: Session, payload: dict[str, Any]
) -> None:
    product = priced_product(db_session)
    alert_id = create_alert(client, product).json()["alert_id"]

    response = client.patch(f"/api/alerts/{alert_id}", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_delete_alert_returns_204_and_it_is_gone(client: TestClient, db_session: Session) -> None:
    product = priced_product(db_session)
    alert_id = create_alert(client, product).json()["alert_id"]

    response = client.delete(f"/api/alerts/{alert_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/alerts").json()["items"] == []


@pytest.mark.parametrize("alert_id", ["999999", "0", "-1", str(INT4_OVER), str(HUGE)])
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [("patch", "", {"status": "paused"}), ("delete", "", None), ("post", "/test", None)],
)
def test_unknown_or_out_of_range_alert_id_is_404_alert_not_found(
    client: TestClient, alert_id: str, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"/api/alerts/{alert_id}{suffix}", json=body)

    assert response.status_code == 404
    assert error_code(response) == "ALERT_NOT_FOUND"


# ---- gửi thử ----
def test_alert_test_reports_that_nothing_was_sent_until_notifications_exist(
    client: TestClient, db_session: Session
) -> None:
    product = priced_product(db_session)
    alert_id = create_alert(client, product).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["reason"]
