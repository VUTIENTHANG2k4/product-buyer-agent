"""QA M0 lần hai: ca biên của định dạng lỗi chuẩn (T0.8) qua `create_app()` đầy đủ.

Ba test `xfail(strict=True)` tái hiện lỗi thật đang có trong `app/api/errors.py`; khi sửa mã,
XPASS (strict) sẽ báo lỗi và người sửa chỉ cần bỏ dấu xfail.
"""

import asyncio
import datetime
import json
import logging
from collections.abc import Iterator
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, SecretStr
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from app.api.errors import error_responses
from app.domain import errors
from app.main import FRONTEND_ORIGIN, create_app

SECRET = "gia-tri-bi-mat-khong-duoc-lo"
GENERIC_MESSAGE = "Yêu cầu không hợp lệ."


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int


class Inner(BaseModel):
    x: int


class Mid(BaseModel):
    items: list[Inner]


class Outer(BaseModel):
    mid: Mid
    tags: list[str]


class Out(BaseModel):
    n: int


class BrokenStr(Exception):
    def __str__(self) -> str:
        raise ValueError("__str__ hỏng")


class _Counter:
    calls = 0


# --- route thử nghiệm ---


def _strict(body: Strict) -> dict[str, int]:
    return {"a": body.a}


def _outer(body: Outer) -> dict[str, int]:
    return {"ok": 1}


def _echo_int(n: int) -> dict[str, int]:
    return {"n": n}


def _echo_ids(ids: Annotated[list[int], Query()]) -> dict[str, list[int]]:
    return {"ids": ids}


def _echo_name(name: str) -> dict[str, str]:
    return {"name": name}


def _http_403_without_detail() -> None:
    raise StarletteHTTPException(403)


def _http_400_detail_none() -> None:
    raise StarletteHTTPException(400, detail=None)  # type: ignore[arg-type]


def _http_401_with_headers() -> None:
    raise StarletteHTTPException(
        401, "Cần đăng nhập", headers={"WWW-Authenticate": "Bearer", "X-Request-Id": "r1"}
    )


def _http_503_retry_after() -> None:
    raise StarletteHTTPException(503, "Bảo trì", headers={"Retry-After": "30"})


def _response_invalid() -> Any:
    return {"n": SECRET}


def _broken_dependency() -> int:
    raise RuntimeError(SECRET)


def _domain_dependency() -> int:
    raise errors.ListNotFound(details={"list_id": 3})


def _use_broken_dependency(value: Annotated[int, Depends(_broken_dependency)]) -> dict[str, int]:
    return {"value": value}


def _use_domain_dependency(value: Annotated[int, Depends(_domain_dependency)]) -> dict[str, int]:
    return {"value": value}


def _broken_str() -> None:
    raise BrokenStr


def _exception_group() -> None:
    raise ExceptionGroup(SECRET, [RuntimeError("a"), ValueError("b")])


def _details_with_datetime() -> None:
    when = datetime.datetime(2026, 10, 17, 3, 0, tzinfo=datetime.UTC)
    raise errors.SiteCooldown(details={"retry_after": when})


def _details_with_set() -> None:
    raise errors.SiteCooldown(details={"sites": {"gearvn"}})


def _details_with_secret() -> None:
    raise errors.SiteCooldown(details={"token": SecretStr(SECRET)})


def _multi_method() -> dict[str, str]:
    return {"ok": "1"}


def _stream_fails_midway() -> StreamingResponse:
    def chunks() -> Iterator[bytes]:
        yield b"data: 1\n\n"
        raise RuntimeError("đứt giữa chừng")

    return StreamingResponse(chunks(), media_type="text/event-stream")


def _counting_route() -> dict[str, int]:
    _Counter.calls += 1
    raise RuntimeError(SECRET)


async def _mixed(n: int) -> dict[str, int]:
    await asyncio.sleep(0)  # nhường event loop để các request xen kẽ nhau
    kind = n % 4
    if kind == 1:
        raise errors.ProductNotFound(f"sản phẩm {n}", details={"n": n})
    if kind == 2:
        raise RuntimeError(f"hỏng {n}")
    if kind == 3:
        raise StarletteHTTPException(418, f"ấm trà {n}")
    return {"n": n}


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    routes: list[tuple[str, Any, list[str] | None]] = [
        ("/api/_t/strict", _strict, ["POST"]),
        ("/api/_t/outer", _outer, ["POST"]),
        ("/api/_t/int", _echo_int, None),
        ("/api/_t/ids", _echo_ids, None),
        ("/api/_t/name/{name}", _echo_name, None),
        ("/api/_t/http-403", _http_403_without_detail, None),
        ("/api/_t/http-400-none", _http_400_detail_none, None),
        ("/api/_t/http-401", _http_401_with_headers, None),
        ("/api/_t/http-503", _http_503_retry_after, None),
        ("/api/_t/dep-broken", _use_broken_dependency, None),
        ("/api/_t/dep-domain", _use_domain_dependency, None),
        ("/api/_t/broken-str", _broken_str, None),
        ("/api/_t/group", _exception_group, None),
        ("/api/_t/details-datetime", _details_with_datetime, None),
        ("/api/_t/details-set", _details_with_set, None),
        ("/api/_t/details-secret", _details_with_secret, None),
        ("/api/_t/multi", _multi_method, ["GET", "PUT"]),
        ("/api/_t/stream", _stream_fails_midway, None),
        ("/api/_t/counting", _counting_route, None),
        ("/api/_t/mixed/{n}", _mixed, None),
    ]
    for path, endpoint, methods in routes:
        app.add_api_route(path, endpoint, methods=methods)
    app.add_api_route("/api/_t/invalid-response", _response_invalid, response_model=Out)
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _envelope(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["details"], dict)
    error: dict[str, Any] = body["error"]
    return error


# --- HTTPException không kèm câu riêng ---


@pytest.mark.xfail(
    strict=True,
    reason="docs/07 §1: HTTPException chỉ giữ thông điệp khi khác cụm chuẩn; "
    "handler chỉ lọc cụm chuẩn cho 404/405 nên 403/400 trả 'Forbidden'/'Bad Request' tiếng Anh",
)
@pytest.mark.parametrize("path", ["/api/_t/http-403", "/api/_t/http-400-none"])
def test_http_exception_without_own_message_gets_the_vietnamese_generic_message(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    error = _envelope(response, response.status_code, f"HTTP_{response.status_code}")
    assert error["message"] == GENERIC_MESSAGE


@pytest.mark.parametrize(
    ("path", "status", "headers"),
    [
        ("/api/_t/http-401", 401, {"www-authenticate": "Bearer", "x-request-id": "r1"}),
        ("/api/_t/http-503", 503, {"retry-after": "30"}),
    ],
)
def test_http_exception_keeps_every_custom_header_next_to_the_envelope(
    client: TestClient, path: str, status: int, headers: dict[str, str]
) -> None:
    response = client.get(path)
    _envelope(response, status, f"HTTP_{status}")
    for name, value in headers.items():
        assert response.headers[name] == value


# --- Chi tiết của AppError không serialize được ---


@pytest.mark.xfail(
    strict=True,
    reason="_error_response dùng JSONResponse trần: details chứa datetime/set làm handler "
    "ném TypeError nên 409 của SiteCooldown biến thành 500; nên dùng jsonable_encoder",
)
@pytest.mark.parametrize("path", ["/api/_t/details-datetime", "/api/_t/details-set"])
def test_app_error_with_datetime_or_set_details_keeps_its_own_status(
    client: TestClient, path: str
) -> None:
    error = _envelope(client.get(path), 409, "SITE_COOLDOWN")
    assert error["details"]  # giá trị đã được chuyển thành JSON, không bị bỏ


def test_app_error_with_unserializable_details_never_breaks_the_envelope_or_leaks_secret(
    client: TestClient,
) -> None:
    response = client.get("/api/_t/details-secret")
    assert response.status_code in {409, 500}
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert SECRET not in response.text


# --- 500 ---


def test_response_validation_error_is_a_standard_500_that_hides_the_payload(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        response = client.get("/api/_t/invalid-response")
    error = _envelope(response, 500, "INTERNAL_ERROR")
    assert error["message"] == errors.InternalError.default_message
    assert SECRET not in response.text
    assert "ResponseValidationError" in caplog.text


def test_exception_whose_str_raises_still_returns_500_and_can_be_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        response = client.get("/api/_t/broken-str")
    _envelope(response, 500, "INTERNAL_ERROR")
    assert "BrokenStr" in caplog.text


def test_exception_group_is_a_standard_500_without_leaking_its_message(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        response = client.get("/api/_t/group")
    _envelope(response, 500, "INTERNAL_ERROR")
    assert SECRET not in response.text
    assert "ExceptionGroup" in caplog.text


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [("/api/_t/dep-broken", 500, "INTERNAL_ERROR"), ("/api/_t/dep-domain", 404, "LIST_NOT_FOUND")],
)
def test_error_raised_inside_a_dependency_goes_through_the_same_handlers(
    client: TestClient, path: str, status: int, code: str
) -> None:
    response = client.get(path)
    error = _envelope(response, status, code)
    assert SECRET not in response.text
    if status == 404:
        assert error["details"] == {"list_id": 3}


def test_error_after_the_response_started_is_reraised_not_followed_by_a_second_response(
    app: FastAPI,
) -> None:
    async def run() -> list[Message]:
        sent: list[Message] = []

        requested = False

        async def receive() -> Message:
            # Sau thân request, chờ vô hạn như máy khách còn mở: StreamingResponse nghe
            # `http.disconnect` bằng vòng lặp, trả về ngay sẽ làm vòng lặp quay mãi.
            nonlocal requested
            if not requested:
                requested = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()
            raise AssertionError("không tới được")

        async def send(message: Message) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/_t/stream",
            "raw_path": b"/api/_t/stream",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
        }
        with pytest.raises(RuntimeError, match="đứt giữa chừng"):
            await app(scope, receive, send)  # type: ignore[arg-type]
        return sent

    sent = asyncio.run(run())
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert [m["status"] for m in starts] == [200]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert body == b"data: 1\n\n"
    assert b"INTERNAL_ERROR" not in body


# --- CORS và phương thức ---


def test_preflight_to_a_failing_route_is_answered_by_cors_without_running_the_route(
    client: TestClient,
) -> None:
    _Counter.calls = 0
    response = client.options(
        "/api/_t/counting",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert _Counter.calls == 0


def test_method_not_allowed_lists_every_method_of_a_multi_method_route(
    client: TestClient,
) -> None:
    for method in ("POST", "DELETE", "OPTIONS"):
        response = client.request(method, "/api/_t/multi")
        _envelope(response, 405, "METHOD_NOT_ALLOWED")
        assert {m.strip() for m in response.headers["allow"].split(",")} == {"GET", "PUT"}


def test_head_to_an_unknown_path_is_404_with_an_empty_body(client: TestClient) -> None:
    response = client.head("/api/khong-ton-tai")
    assert response.status_code == 404
    assert response.content == b""


# --- 422 ---


def test_nested_body_errors_are_all_reported_with_dotted_paths_and_no_input_echo(
    client: TestClient,
) -> None:
    payload = {"mid": {"items": [{"x": 1}, {"x": SECRET}, {}]}, "tags": ["a", 1, None]}
    response = client.post("/api/_t/outer", json=payload)
    error = _envelope(response, 422, "VALIDATION_ERROR")
    found = {(e["field"], e["type"]) for e in error["details"]["errors"]}
    assert found == {
        ("mid.items.1.x", "int_parsing"),
        ("mid.items.2.x", "missing"),
        ("tags.1", "string_type"),
        ("tags.2", "string_type"),
    }
    assert SECRET not in response.text


def test_extra_forbidden_field_is_reported_by_name_with_its_type(client: TestClient) -> None:
    response = client.post("/api/_t/strict", json={"a": 1, "b": SECRET})
    error = _envelope(response, 422, "VALIDATION_ERROR")
    (item,) = error["details"]["errors"]
    assert (item["in"], item["field"], item["type"]) == ("body", "b", "extra_forbidden")
    assert SECRET not in response.text


def test_wrong_content_type_or_non_object_body_is_a_422_at_the_body_root(
    client: TestClient,
) -> None:
    cases = [
        {"content": '{"a": 1}', "headers": {"Content-Type": "text/plain"}},
        {"content": "[1, 2]", "headers": {"Content-Type": "application/json"}},
        {"data": {"a": "1"}},
    ]
    for kwargs in cases:
        error = _envelope(client.post("/api/_t/strict", **kwargs), 422, "VALIDATION_ERROR")
        (item,) = error["details"]["errors"]
        assert (item["in"], item["field"], item["type"]) == (
            "body",
            "",
            "model_attributes_type",
        )


@pytest.mark.parametrize(
    "content", [b'{"a": "\xff"}', b"[" * 100_000], ids=["invalid-utf8", "absurdly-deep-json"]
)
def test_undecodable_body_is_a_400_envelope_not_a_server_error(
    client: TestClient, content: bytes
) -> None:
    response = client.post(
        "/api/_t/strict", content=content, headers={"Content-Type": "application/json"}
    )
    _envelope(response, 400, "HTTP_400")


def test_repeated_scalar_query_parameter_uses_the_last_value(client: TestClient) -> None:
    assert client.get("/api/_t/int?n=1&n=2").json() == {"n": 2}
    error = _envelope(client.get("/api/_t/int?n=2&n=x"), 422, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["field"] == "n"


def test_repeated_list_query_parameter_reports_the_index_of_the_bad_item(
    client: TestClient,
) -> None:
    assert client.get("/api/_t/ids?ids=1&ids=2").json() == {"ids": [1, 2]}
    error = _envelope(client.get("/api/_t/ids?ids=1&ids=2&ids=x"), 422, "VALIDATION_ERROR")
    (item,) = error["details"]["errors"]
    assert (item["in"], item["field"], item["type"]) == ("query", "ids.2", "int_parsing")


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/api/_t/name/tiếng-việt", "tiếng-việt"),
        ("/api/_t/name/%E1%BA%A1", "ạ"),
        ("/api/_t/name/%zz", "%zz"),
        ("/api/_t/name/%E1%BA", "�"),
    ],
)
def test_unicode_and_broken_percent_encoding_in_a_path_never_cause_a_server_error(
    client: TestClient, path: str, name: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"name": name}


@pytest.mark.parametrize("path", ["/api/kh%C3%B4ng-c%C3%B3", "/api/%E1%BA", "//api//health"])
def test_unknown_unicode_or_malformed_path_is_the_not_found_envelope(
    client: TestClient, path: str
) -> None:
    error = _envelope(client.get(path), 404, "NOT_FOUND")
    assert error["message"] == errors.NotFound.default_message


def _echo_int_path(pid: int) -> dict[str, int]:
    return {"pid": pid}


def test_path_integer_with_unicode_digits_or_absurd_length_is_a_422(client: TestClient) -> None:
    app = create_app()
    app.add_api_route("/api/_t/p/{pid}", _echo_int_path)
    with TestClient(app) as local:
        for path, error_type in [
            ("/api/_t/p/%D9%A1%D9%A2", "int_parsing"),
            ("/api/_t/p/" + "9" * 5000, "int_parsing_size"),
        ]:
            error = _envelope(local.get(path), 422, "VALIDATION_ERROR")
            (item,) = error["details"]["errors"]
            assert (item["in"], item["field"], item["type"]) == ("path", "pid", error_type)


# --- Song song ---


async def test_concurrent_mixed_requests_each_get_their_own_correct_envelope(
    app: FastAPI,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        responses = await asyncio.gather(*(http.get(f"/api/_t/mixed/{n}") for n in range(40)))

    for n, response in enumerate(responses):
        kind = n % 4
        if kind == 0:
            assert (response.status_code, response.json()) == (200, {"n": n})
        elif kind == 1:
            error = _envelope(response, 404, "PRODUCT_NOT_FOUND")
            assert (error["message"], error["details"]) == (f"sản phẩm {n}", {"n": n})
        elif kind == 2:
            error = _envelope(response, 500, "INTERNAL_ERROR")
            assert f"hỏng {n}" not in response.text
        else:
            error = _envelope(response, 418, "HTTP_418")
            assert error["message"] == f"ấm trà {n}"


# --- OpenAPI ---


def test_route_level_responses_keep_the_app_level_standard_error_schemas() -> None:
    app = create_app()

    @app.get("/api/_t/o/{pid}", responses=error_responses(404))
    def route(pid: int) -> dict[str, int]:
        return {"pid": pid}

    with TestClient(app) as local:
        schema = local.get("/api/openapi.json").json()
    responses = schema["paths"]["/api/_t/o/{pid}"]["get"]["responses"]
    ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for status in ("404", "422", "500"):
        assert responses[status]["content"]["application/json"]["schema"] == ref
    assert "HTTPValidationError" not in json.dumps(schema)


def test_error_responses_helper_describes_unknown_statuses_and_accepts_none() -> None:
    assert error_responses() == {}
    declared = error_responses(418)
    assert declared[418]["description"] == "Lỗi"
    assert declared[418]["model"].__name__ == "ErrorResponse"
