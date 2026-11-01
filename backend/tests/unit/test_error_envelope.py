"""Mọi lỗi của API có dạng {"error": {"code", "message", "details"}} (docs/07 §1–2)."""

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message, Receive, Scope, Send

from app.api.errors import UnhandledErrorMiddleware
from app.domain import errors
from app.main import FRONTEND_ORIGIN, create_app

SECRET = "chuoi-bi-mat-khong-duoc-lo"


class Item(BaseModel):
    name: str
    price: int = Field(ge=0)


def _raise_domain_error() -> None:
    raise errors.ProductNotFound("Không tìm thấy sản phẩm 999", details={"product_id": 999})


def _raise_teapot() -> None:
    raise StarletteHTTPException(418, "Tôi là ấm trà", headers={"X-Test": "1"})


def _raise_http_error_with_structured_detail() -> None:
    # Cố ý truyền `detail` không phải chuỗi (kiểu khai báo của Starlette là str).
    raise StarletteHTTPException(400, detail={"loi": SECRET})  # type: ignore[arg-type]


def _raise_non_standard_status() -> None:
    raise StarletteHTTPException(499, "Máy khách đã đóng kết nối")


def _raise_custom_not_found() -> None:
    raise StarletteHTTPException(404, "Không tìm thấy sản phẩm 5")


def _raise_not_modified() -> None:
    raise StarletteHTTPException(304, headers={"ETag": "abc"})


def _raise_no_content() -> None:
    raise StarletteHTTPException(204)


def _raise_unexpected() -> None:
    raise RuntimeError(SECRET)


def _query_route(n: int = Query(1, ge=1)) -> dict[str, int]:
    return {"n": n}


def _body_route(item: Item) -> dict[str, str]:
    return {"name": item.name}


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    app.add_api_route("/api/_t/domain", _raise_domain_error)
    app.add_api_route("/api/_t/teapot", _raise_teapot)
    app.add_api_route("/api/_t/structured", _raise_http_error_with_structured_detail)
    app.add_api_route("/api/_t/custom-404", _raise_custom_not_found)
    app.add_api_route("/api/_t/non-standard", _raise_non_standard_status)
    app.add_api_route("/api/_t/not-modified", _raise_not_modified)
    app.add_api_route("/api/_t/no-content", _raise_no_content)
    app.add_api_route("/api/_t/boom", _raise_unexpected)
    app.add_api_route("/api/_t/query", _query_route)
    app.add_api_route("/api/_t/body", _body_route, methods=["POST"])
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], dict)
    error: dict[str, Any] = body["error"]
    return error


# --- Lỗi miền ---


def test_domain_error_becomes_the_standard_envelope_with_its_status_and_details(
    client: TestClient,
) -> None:
    error = _error(client.get("/api/_t/domain"), 404, "PRODUCT_NOT_FOUND")
    assert error["message"] == "Không tìm thấy sản phẩm 999"
    assert error["details"] == {"product_id": 999}


# --- Route lạ / sai phương thức / HTTPException ---


@pytest.mark.parametrize("path", ["/api/khong-ton-tai", "/health", "/api/health/extra"])
def test_unknown_path_is_not_found_in_vietnamese(client: TestClient, path: str) -> None:
    error = _error(client.get(path), 404, "NOT_FOUND")
    assert error["message"] == errors.NotFound.default_message
    assert error["details"] == {}


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_wrong_method_is_method_not_allowed_and_keeps_the_allow_header(
    client: TestClient, method: str
) -> None:
    response = client.request(method, "/api/health")
    error = _error(response, 405, "METHOD_NOT_ALLOWED")
    assert error["message"] == errors.MethodNotAllowed.default_message
    assert "GET" in response.headers["allow"]


def test_other_http_exception_uses_http_status_code_and_keeps_headers(client: TestClient) -> None:
    response = client.get("/api/_t/teapot")
    error = _error(response, 418, "HTTP_418")
    assert error["message"] == "Tôi là ấm trà"
    assert response.headers["x-test"] == "1"


def test_status_code_outside_the_http_standard_still_gets_an_envelope(client: TestClient) -> None:
    error = _error(client.get("/api/_t/non-standard"), 499, "HTTP_499")
    assert error["message"] == "Máy khách đã đóng kết nối"


def test_not_found_raised_with_a_specific_detail_keeps_that_message(client: TestClient) -> None:
    error = _error(client.get("/api/_t/custom-404"), 404, "NOT_FOUND")
    assert error["message"] == "Không tìm thấy sản phẩm 5"


@pytest.mark.parametrize(
    ("path", "status"), [("/api/_t/not-modified", 304), ("/api/_t/no-content", 204)]
)
def test_statuses_that_forbid_a_body_are_sent_without_one(
    client: TestClient, path: str, status: int
) -> None:
    response = client.get(path)
    assert response.status_code == status
    assert response.content == b""
    assert "application/json" not in response.headers.get("content-type", "")


def test_not_modified_keeps_its_headers(client: TestClient) -> None:
    assert client.get("/api/_t/not-modified").headers["etag"] == "abc"


def test_http_exception_with_non_string_detail_gets_a_generic_message(client: TestClient) -> None:
    response = client.get("/api/_t/structured")
    error = _error(response, 400, "HTTP_400")
    assert error["message"].strip()
    assert SECRET not in response.text


# --- Dữ liệu sai (422) ---


def test_invalid_query_parameter_lists_the_field_and_error_type(client: TestClient) -> None:
    error = _error(client.get("/api/_t/query?n=0"), 422, "VALIDATION_ERROR")
    assert error["message"] == errors.ValidationFailed.default_message
    (item,) = error["details"]["errors"]
    assert {k: item[k] for k in ("in", "field", "type")} == {
        "in": "query",
        "field": "n",
        "type": "greater_than_equal",
    }
    assert isinstance(item["message"], str) and item["message"]
    assert set(item) == {"in", "field", "message", "type"}


def test_validation_error_never_echoes_the_rejected_value(client: TestClient) -> None:
    response = client.get(f"/api/_t/query?n={SECRET}")
    error = _error(response, 422, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["type"] == "int_parsing"
    assert SECRET not in response.text


def test_invalid_body_reports_each_field_with_its_dotted_path(client: TestClient) -> None:
    response = client.post("/api/_t/body", json={"name": [1], "price": -1})
    error = _error(response, 422, "VALIDATION_ERROR")
    found = {(e["in"], e["field"]) for e in error["details"]["errors"]}
    assert found == {("body", "name"), ("body", "price")}


@pytest.mark.parametrize(
    ("content", "error_type"),
    [("{khong-phai-json", "json_invalid"), ("", "missing")],
)
def test_unparseable_or_missing_body_is_reported_at_the_body_root(
    client: TestClient, content: str, error_type: str
) -> None:
    response = client.post(
        "/api/_t/body", content=content, headers={"Content-Type": "application/json"}
    )
    error = _error(response, 422, "VALIDATION_ERROR")
    (item,) = error["details"]["errors"]
    assert (item["in"], item["field"], item["type"]) == ("body", "", error_type)


# --- Lỗi không lường trước (500) ---


def test_unexpected_exception_returns_internal_error_without_leaking_details(
    client: TestClient,
) -> None:
    response = client.get("/api/_t/boom")
    error = _error(response, 500, "INTERNAL_ERROR")
    assert error["message"] == errors.InternalError.default_message
    assert error["details"] == {}
    assert SECRET not in response.text
    assert "Traceback" not in response.text


def test_internal_error_response_still_carries_the_cors_header(client: TestClient) -> None:
    response = client.get("/api/_t/boom", headers={"Origin": FRONTEND_ORIGIN})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_unexpected_exception_is_logged_with_its_type_and_the_request(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        client.get("/api/_t/boom")
    (record,) = [r for r in caplog.records if r.name == "app.api.errors"]
    assert record.levelno == logging.ERROR
    assert "RuntimeError" in record.getMessage()
    assert "/api/_t/boom" in record.getMessage()
    assert record.exc_info is not None


# --- Middleware (ASGI) ---


async def _no_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def test_middleware_answers_500_json_when_the_app_fails_before_responding() -> None:
    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError(SECRET)

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await UnhandledErrorMiddleware(failing)(
        {"type": "http", "method": "GET", "path": "/x"}, _no_receive, send
    )

    assert sent[0]["status"] == 500
    body = json.loads(b"".join(m.get("body", b"") for m in sent[1:]))
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert SECRET not in json.dumps(body)


async def test_middleware_reraises_when_the_response_has_already_started() -> None:
    async def half_done(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("giữa chừng")

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    with pytest.raises(RuntimeError, match="giữa chừng"):
        await UnhandledErrorMiddleware(half_done)(
            {"type": "http", "method": "GET", "path": "/x"}, _no_receive, send
        )
    assert [m["type"] for m in sent] == ["http.response.start"]


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_middleware_does_not_wrap_non_http_scopes(scope_type: str) -> None:
    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("không phải http")

    async def send(message: Message) -> None:
        raise AssertionError("không được gửi gì")

    with pytest.raises(RuntimeError, match="không phải http"):
        await UnhandledErrorMiddleware(failing)({"type": scope_type}, _no_receive, send)


async def test_middleware_lets_cancellation_through() -> None:
    async def cancelled(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError

    async def send(message: Message) -> None:
        raise AssertionError("không được gửi gì")

    with pytest.raises(asyncio.CancelledError):
        await UnhandledErrorMiddleware(cancelled)(
            {"type": "http", "method": "GET", "path": "/x"}, _no_receive, send
        )


# --- OpenAPI ---


def test_routes_with_parameters_document_the_standard_422_not_the_framework_default(
    client: TestClient,
) -> None:
    schema = client.get("/api/openapi.json").json()
    ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path in ("/api/_t/query", "/api/_t/body"):
        operation = next(iter(schema["paths"][path].values()))
        assert operation["responses"]["422"]["content"]["application/json"]["schema"] == ref
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_openapi_documents_the_shared_error_schema() -> None:
    with TestClient(create_app()) as plain:
        schema = plain.get("/api/openapi.json").json()
    components = schema["components"]["schemas"]
    assert set(components["ErrorResponse"]["properties"]) == {"error"}
    assert set(components["ErrorDetail"]["properties"]) == {"code", "message", "details"}
    health_500 = schema["paths"]["/api/health"]["get"]["responses"]["500"]
    assert health_500["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
