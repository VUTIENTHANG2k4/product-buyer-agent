"""T9.2: POST /alerts/{id}/test gửi thật qua notifier (đã thay bằng bộ gửi giả)."""

from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_notifiers
from app.db.models import PriceAlert
from app.domain.enums import AlertChannel, AlertStatus
from app.services.notifier.base import NotificationFailed, Notifier
from tests.api.test_alerts_api import create_alert, priced_product
from tests.service_support import make_settings


class RecordingNotifier:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str, str]] = []

    def send(self, destination: str, subject: str, body: str) -> None:
        if self.error:
            raise NotificationFailed(self.error)
        self.sent.append((destination, subject, body))


def use_notifiers(client: TestClient, notifiers: Mapping[AlertChannel, Notifier]) -> None:
    client.app.dependency_overrides[get_notifiers] = lambda: notifiers  # type: ignore[attr-defined]


def test_test_endpoint_sends_to_the_alert_destination_and_reports_sent(
    client: TestClient, db_session: Session
) -> None:
    email = RecordingNotifier()
    use_notifiers(client, {AlertChannel.email: email})
    product = priced_product(db_session)
    alert_id = create_alert(client, product, target=25_000_000).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code == 200
    assert response.json() == {"sent": True, "reason": None}
    ((destination, subject, body),) = email.sent
    assert destination == "mock@example.com"
    assert subject == "Thông báo thử từ Product Buyer Agent"
    assert product.canonical_name in body and "25.000.000 ₫" in body


def test_test_endpoint_does_not_change_the_alert(client: TestClient, db_session: Session) -> None:
    use_notifiers(client, {AlertChannel.email: RecordingNotifier()})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    client.post(f"/api/alerts/{alert_id}/test")

    db_session.expire_all()
    alert = db_session.get_one(PriceAlert, alert_id)
    assert (alert.status, alert.last_notified_price, alert.last_notified_at) == (
        AlertStatus.active,
        None,
        None,
    )


def test_test_endpoint_reports_the_failure_reason_instead_of_a_500(
    client: TestClient, db_session: Session
) -> None:
    use_notifiers(client, {AlertChannel.email: RecordingNotifier("Telegram từ chối (HTTP 401)")})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code == 200
    assert response.json() == {"sent": False, "reason": "Telegram từ chối (HTTP 401)"}


def test_test_endpoint_uses_the_notifier_of_the_alert_channel(
    client: TestClient, db_session: Session
) -> None:
    email, telegram = RecordingNotifier(), RecordingNotifier()
    use_notifiers(client, {AlertChannel.email: email, AlertChannel.telegram: telegram})
    body: dict[str, Any] = {"channel": "telegram", "destination": "@MockChat"}
    alert_id = create_alert(client, priced_product(db_session), **body).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.json()["sent"] is True
    assert email.sent == [] and [sent[0] for sent in telegram.sent] == ["@MockChat"]


def test_test_endpoint_reports_a_missing_channel(client: TestClient, db_session: Session) -> None:
    use_notifiers(client, {AlertChannel.telegram: RecordingNotifier()})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.json() == {"sent": False, "reason": "Kênh email chưa được cấu hình trong .env"}


def test_default_dependency_builds_notifiers_from_settings() -> None:
    settings = make_settings(smtp_host="smtp.mock.example", alert_email_from="a@mock.example")

    assert set(get_notifiers(settings)) == {AlertChannel.email}
