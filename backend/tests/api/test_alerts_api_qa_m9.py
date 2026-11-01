"""QA M9: biên của API cảnh báo sau khi có bộ gửi thật (id ngoài miền, nơi nhận lạ)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_notifiers
from app.domain.enums import AlertChannel
from tests.api.test_alerts_api import HUGE, INT4_OVER, create_alert, error_code, priced_product


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, destination: str, subject: str, body: str) -> None:
        self.sent.append((destination, subject, body))


@pytest.mark.parametrize("alert_id", [0, -1, INT4_OVER, HUGE])
def test_alert_ids_outside_the_key_range_are_not_found_for_every_alert_route(
    client: TestClient, alert_id: int
) -> None:
    recorder = Recorder()
    client.app.dependency_overrides[get_notifiers] = lambda: {AlertChannel.email: recorder}  # type: ignore[attr-defined]

    responses = [
        client.post(f"/api/alerts/{alert_id}/test"),
        client.patch(f"/api/alerts/{alert_id}", json={"target_price": 1_000_000}),
        client.patch(f"/api/alerts/{alert_id}", json={"status": "paused"}),
        client.delete(f"/api/alerts/{alert_id}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    assert {error_code(r) for r in responses} == {"ALERT_NOT_FOUND"}
    assert recorder.sent == []


@pytest.mark.parametrize("destination", ["victim,attacker@example.com", "x;y@example.com"])
def test_an_email_destination_with_a_list_separator_is_rejected_with_422(
    client: TestClient, db_session: Session, destination: str
) -> None:
    product = priced_product(db_session)

    response = create_alert(client, product, channel="email", destination=destination)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_test_endpoint_works_for_a_paused_alert_and_leaves_it_paused(
    client: TestClient, db_session: Session
) -> None:
    recorder = Recorder()
    client.app.dependency_overrides[get_notifiers] = lambda: {AlertChannel.email: recorder}  # type: ignore[attr-defined]
    product = priced_product(db_session)
    alert_id = create_alert(client, product, destination="owner@example.com").json()["alert_id"]
    client.patch(f"/api/alerts/{alert_id}", json={"status": "paused"})

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.json() == {"sent": True, "reason": None}
    assert [destination for destination, _, _ in recorder.sent] == ["owner@example.com"]
    (listed,) = client.get("/api/alerts").json()["items"]
    assert listed["status"] == "paused"
