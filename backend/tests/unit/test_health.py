import contextlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api.deps import get_db_status
from app.config import Settings, get_settings
from app.main import create_app
from app.services.health_service import DbStatus


def _client(db: DbStatus, settings: Settings | None = None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db_status] = lambda: db
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_db_ok() -> Iterator[TestClient]:
    yield from _client("ok")


@pytest.fixture
def client_db_error() -> Iterator[TestClient]:
    yield from _client("error")


def test_health_returns_documented_schema_when_db_ok(client_db_ok: TestClient) -> None:
    response = client_db_ok.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "llm_provider": "fake",
        "offline_mode": True,
        "version": __version__,
    }


def test_health_is_degraded_with_http_200_when_db_unreachable(
    client_db_error: TestClient,
) -> None:
    response = client_db_error.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"


def test_health_reflects_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("SCRAPER_OFFLINE_ONLY", "false")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with contextlib.closing(_client("ok", settings)) as clients:
        body = next(clients).get("/api/health").json()
    assert body["llm_provider"] == "gemini"
    assert body["offline_mode"] is False


def test_openapi_is_served_under_api_prefix(client_db_ok: TestClient) -> None:
    schema = client_db_ok.get("/api/openapi.json").json()
    assert "/api/health" in schema["paths"]
