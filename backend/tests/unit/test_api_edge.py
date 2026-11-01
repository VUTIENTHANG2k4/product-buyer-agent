"""Ca biên của API nền: health khi CSDL lỗi, CORS, route lạ, phương thức sai."""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import __version__
from app.config import Settings, get_settings
from app.main import FRONTEND_ORIGIN, create_app
from app.services import health_service

DB_PASSWORD = "mat-khau-db-bi-mat"


class _BrokenEngine:
    """Engine giả: không bao giờ chạm mạng/libpq."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def connect(self) -> "_BrokenEngine":
        raise self.exc


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://u:{DB_PASSWORD}@db.invalid/x")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


# --- /api/health đi qua dependency thật, chỉ thay engine ---


def test_health_degrades_through_real_dependency_chain_when_engine_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    exc = OperationalError("connect", {}, Exception(f"password={DB_PASSWORD}"))
    monkeypatch.setattr(health_service, "get_engine", lambda url: _BrokenEngine(exc))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "db": "error",
        "llm_provider": "fake",
        "offline_mode": True,
        "version": __version__,
    }


def test_health_response_never_contains_database_url_or_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    exc = OperationalError("connect", {}, Exception(f"password={DB_PASSWORD}"))
    monkeypatch.setattr(health_service, "get_engine", lambda url: _BrokenEngine(exc))
    assert DB_PASSWORD not in client.get("/api/health").text


def test_health_passes_the_configured_database_url_to_the_engine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake_get_engine(url: str) -> _BrokenEngine:
        seen.append(url)
        return _BrokenEngine(OperationalError("connect", {}, Exception("refused")))

    monkeypatch.setattr(health_service, "get_engine", fake_get_engine)
    client.get("/api/health")
    assert seen == [f"postgresql+psycopg://u:{DB_PASSWORD}@db.invalid/x"]


def test_check_db_logs_only_the_exception_type_not_its_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = OperationalError("connect", {}, Exception(f"password={DB_PASSWORD}"))
    monkeypatch.setattr(health_service, "get_engine", lambda url: _BrokenEngine(exc))
    with caplog.at_level(logging.DEBUG):
        assert health_service.check_db("postgresql+psycopg://x/x") == "error"
    assert "OperationalError" in caplog.text
    assert DB_PASSWORD not in caplog.text


@pytest.mark.parametrize("exc", [ValueError("x"), TimeoutError(), RuntimeError("boom"), OSError()])
def test_check_db_returns_error_for_any_exception_type(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    monkeypatch.setattr(health_service, "get_engine", lambda url: _BrokenEngine(exc))
    assert health_service.check_db("postgresql+psycopg://x/x") == "error"


@pytest.mark.parametrize("url", ["", "khong-phai-url", "nodialect+driver://u:p@h/db"])
def test_check_db_returns_error_for_unparseable_url_without_touching_network(url: str) -> None:
    # create_engine ném lỗi ngay khi dựng engine (trước khi kết nối): vẫn phải là "error".
    assert health_service.check_db(url) == "error"


# --- CORS ---


def test_cors_preflight_allows_the_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]


def test_cors_simple_request_from_frontend_origin_gets_allow_header(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": FRONTEND_ORIGIN})
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "https://localhost:5173",
        "http://localhost:5173.evil.example",
        "null",
    ],
)
def test_cors_does_not_allow_other_origins(client: TestClient, origin: str) -> None:
    simple = client.get("/api/health", headers={"Origin": origin})
    preflight = client.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in simple.headers
    assert "access-control-allow-origin" not in preflight.headers
    assert preflight.status_code == 400


def test_cors_never_allows_credentials_or_wildcard_origin(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": FRONTEND_ORIGIN})
    assert response.headers["access-control-allow-origin"] != "*"
    assert "access-control-allow-credentials" not in response.headers


# --- Route lạ / phương thức sai ---


@pytest.mark.parametrize("path", ["/api/khong-ton-tai", "/health", "/api", "/api/health/extra"])
def test_unknown_path_returns_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_health_rejects_unsafe_methods_with_405(client: TestClient, method: str) -> None:
    response = client.request(method, "/api/health")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


def test_health_ignores_unknown_query_parameters(client: TestClient) -> None:
    assert client.get("/api/health?x=1&db=ok").json()["db"] in {"ok", "error"}


def test_docs_are_served_under_api_prefix_only(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_openapi_health_response_declares_all_documented_fields(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    props = schema["components"]["schemas"]["HealthResponse"]["properties"]
    assert set(props) == {"status", "db", "llm_provider", "offline_mode", "version"}


# --- Định dạng lỗi chuẩn (docs/07 §1); chi tiết hơn ở test_error_envelope.py ---


@pytest.mark.parametrize("path", ["/api/khong-ton-tai", "/api/health/extra"])
def test_unknown_path_uses_documented_error_envelope(client: TestClient, path: str) -> None:
    body = client.get(path).json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert isinstance(body["error"]["code"], str)
