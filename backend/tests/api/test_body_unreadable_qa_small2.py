"""QA lượt việc nhỏ 2 (T7.7a): thân yêu cầu không đọc được → 422 `VALIDATION_ERROR`."""

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.domain.errors import ChallengeFailed
from app.main import create_app

JSON = {"Content-Type": "application/json"}
RUN_ID = str(uuid.uuid4())

# (phương thức, đường dẫn) nhận thân JSON. Kiểm tra thân diễn ra trước khi chạy handler, nên
# id không tồn tại cũng phải ra 422 chứ không phải 404.
BODY_ENDPOINTS = [
    ("POST", "/api/lists"),
    ("PATCH", "/api/lists/1"),
    ("POST", "/api/lists/1/items"),
    ("PATCH", "/api/lists/1/items/1"),
    ("POST", "/api/compare"),
    ("POST", "/api/alerts"),
    ("PATCH", "/api/alerts/1"),
    ("POST", "/api/chat"),
    ("POST", "/api/admin/scrape-runs"),
    ("POST", f"/api/admin/scrape-runs/{RUN_ID}/challenge"),
]
ENDPOINT_IDS = [f"{method} {url.split('/api')[1][:22]}" for method, url in BODY_ENDPOINTS]

UNREADABLE = {
    "invalid_utf8_in_value": b'{"name": "' + bytes([0xFF, 0xFE]) + b'"}',
    "invalid_utf8_lone_continuation": b'{"name": "\x80"}',
    "truncated_utf8_sequence": b'{"name": "\xe1\xbb"}',
    "overlong_utf8": b'{"name": "\xc0\xaf"}',
    "integer_5000_digits": b'{"name": 1' + b"9" * 5000 + b"}",
    "negative_integer_5000_digits": b'{"name": -' + b"9" * 5000 + b"}",
}


def assert_validation_error(response: Any) -> dict[str, Any]:
    assert response.status_code == 422, f"{response.status_code}: {response.text[:300]}"
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert set(error) == {"code", "message", "details"}
    assert error["details"]["errors"], "phải có ít nhất một mục lỗi"
    for marker in ("Traceback", 'File "', "There was an error", "UnicodeDecodeError", "codec"):
        assert marker not in response.text
    return dict(error)


@pytest.mark.parametrize(("method", "url"), BODY_ENDPOINTS, ids=ENDPOINT_IDS)
@pytest.mark.parametrize("body", UNREADABLE.values(), ids=UNREADABLE.keys())
def test_unreadable_body_is_a_machine_readable_422_on_every_body_endpoint(
    client: TestClient, method: str, url: str, body: bytes
) -> None:
    response = client.request(method, url, content=body, headers=JSON)

    error = assert_validation_error(response)
    assert any(item["in"] == "body" for item in error["details"]["errors"])


@pytest.mark.parametrize("name", ["invalid_utf8_in_value", "integer_5000_digits"])
def test_unreadable_body_carries_a_vietnamese_message_and_stable_type(
    client: TestClient, name: str
) -> None:
    response = client.post("/api/lists", content=UNREADABLE[name], headers=JSON)

    (item,) = assert_validation_error(response)["details"]["errors"]
    assert item == {
        "in": "body",
        "field": "",
        "message": "Thân yêu cầu không đọc được (không phải JSON hợp lệ).",
        "type": "body_unreadable",
    }


def test_unreadable_body_never_echoes_the_offending_bytes(client: TestClient) -> None:
    body = b'{"name": "SECRET-MARKER-' + bytes([0xFF]) + b'"}'

    response = client.post("/api/lists", content=body, headers=JSON)

    assert response.status_code == 422
    assert "SECRET-MARKER" not in response.text


# ---------------------------------------------------------------- lồng sâu, thân khổng lồ
@pytest.mark.parametrize("depth", [1_000, 100_000])
@pytest.mark.parametrize("opener", ["[", '{"a":'])
def test_deeply_nested_json_is_422_not_500_and_never_crashes_the_server(
    client: TestClient, depth: int, opener: str
) -> None:
    body = (opener * depth).encode()

    response = client.post("/api/lists", content=body, headers=JSON)

    assert_validation_error(response)
    assert client.get("/api/health").status_code == 200  # tiến trình vẫn sống


def test_deeply_nested_but_closed_json_is_422_not_500(client: TestClient) -> None:
    depth = 100_000
    body = ("[" * depth + "]" * depth).encode()

    response = client.post("/api/compare", content=body, headers=JSON)

    assert_validation_error(response)


def test_a_5000_digit_number_in_a_money_field_is_422_with_validation_code(
    client: TestClient,
) -> None:
    body = b'{"product_id": 1, "target_price": ' + b"9" * 5000 + b"}"

    response = client.post("/api/alerts", content=body, headers=JSON)

    assert_validation_error(response)


def test_a_5000_digit_number_in_an_array_item_is_422(client: TestClient) -> None:
    body = b'{"product_ids": [1, ' + b"9" * 5000 + b"]}"

    assert_validation_error(client.post("/api/compare", content=body, headers=JSON))


# ---------------------------------------------------------------- thân rỗng, Content-Type sai
@pytest.mark.parametrize(("method", "url"), BODY_ENDPOINTS, ids=ENDPOINT_IDS)
def test_empty_body_is_422_on_every_body_endpoint(
    client: TestClient, method: str, url: str
) -> None:
    response = client.request(method, url, content=b"", headers=JSON)

    assert_validation_error(response)


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", ""])
@pytest.mark.parametrize("url", ["/api/lists", "/api/alerts", "/api/chat", "/api/compare"])
def test_wrong_content_type_with_unreadable_bytes_is_still_a_clean_4xx(
    client: TestClient, url: str, content_type: str
) -> None:
    headers = {"Content-Type": content_type} if content_type else {}

    response = client.post(url, content=UNREADABLE["invalid_utf8_in_value"], headers=headers)

    assert 400 <= response.status_code < 500
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) == {"error"}
    assert "Traceback" not in response.text


def test_charset_parameter_does_not_make_invalid_utf8_readable(client: TestClient) -> None:
    headers = {"Content-Type": "application/json; charset=latin-1"}

    response = client.post(
        "/api/lists", content=UNREADABLE["invalid_utf8_in_value"], headers=headers
    )

    assert response.status_code in (200, 201, 422)
    assert "Traceback" not in response.text


def test_chat_does_not_start_a_run_when_the_body_is_unreadable(client: TestClient) -> None:
    response = client.post("/api/chat", content=UNREADABLE["invalid_utf8_in_value"], headers=JSON)

    assert_validation_error(response)
    assert "run_id" not in response.text


# ---------------------------------------------------------------- HTTP 400 khác giữ nguyên
def make_app_with_routes() -> TestClient:
    app = create_app()

    @app.get("/x-http-400")
    def http_400() -> None:
        raise HTTPException(status_code=400, detail="Tự đặt")

    @app.get("/x-http-400-english-phrase")
    def http_400_phrase() -> None:
        raise HTTPException(status_code=400)

    @app.get("/x-app-400")
    def app_400() -> None:
        raise ChallengeFailed()

    @app.get("/x-http-400-similar")
    def http_400_similar() -> None:
        raise HTTPException(status_code=400, detail="There was an error parsing the body.")

    @app.get("/x-http-422")
    def http_422() -> None:
        raise HTTPException(status_code=422, detail="There was an error parsing the body")

    return TestClient(app)


def test_a_custom_http_400_keeps_its_code_and_message() -> None:
    response = make_app_with_routes().get("/x-http-400")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HTTP_400"
    assert response.json()["error"]["message"] == "Tự đặt"


def test_a_bare_http_400_gets_the_generic_vietnamese_message() -> None:
    response = make_app_with_routes().get("/x-http-400-english-phrase")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HTTP_400"
    assert response.json()["error"]["message"] == "Yêu cầu không hợp lệ."


def test_challenge_failed_stays_400_challenge_failed() -> None:
    response = make_app_with_routes().get("/x-app-400")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHALLENGE_FAILED"


def test_a_400_whose_detail_only_resembles_the_framework_text_is_not_rewritten() -> None:
    response = make_app_with_routes().get("/x-http-400-similar")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HTTP_400"


def test_a_non_400_status_with_the_framework_text_is_not_rewritten() -> None:
    response = make_app_with_routes().get("/x-http-422")

    assert response.status_code == 422
    assert response.json()["error"]["code"] != "VALIDATION_ERROR" or (
        response.json()["error"]["details"].get("errors") is None
    )


def test_valid_json_with_wrong_types_still_reports_the_field_not_body_unreadable(
    client: TestClient,
) -> None:
    response = client.post("/api/alerts", json={"product_id": "x", "target_price": 1})

    error = assert_validation_error(response)
    assert all(item["type"] != "body_unreadable" for item in error["details"]["errors"])
    assert error["details"]["errors"][0]["field"] == "product_id"


def test_syntactically_invalid_json_keeps_the_json_invalid_type(client: TestClient) -> None:
    response = client.post("/api/lists", content=b"{", headers=JSON)

    error = assert_validation_error(response)
    assert error["details"]["errors"][0]["type"] == "json_invalid"


@pytest.mark.parametrize(
    ("url", "field"), [("/api/lists", "name"), ("/api/chat", "message"), ("/api/lists/1", "name")]
)
def test_raw_cesu8_surrogate_bytes_never_reach_500(
    client: TestClient, url: str, field: str
) -> None:
    """`json.loads(bytes)` giải mã bằng `surrogatepass`: chuỗi thay thế đơn lẻ lọt qua tầng JSON."""
    body = b'{"' + field.encode() + b'": "' + bytes.fromhex("eda080") + b'"}'

    response = client.request(
        "PATCH" if url.endswith("/1") else "POST", url, content=body, headers=JSON
    )

    assert 400 <= response.status_code < 500
    assert set(response.json()) == {"error"}
    assert "Traceback" not in response.text
