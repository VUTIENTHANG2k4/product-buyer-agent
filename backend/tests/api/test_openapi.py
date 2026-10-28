"""OpenAPI là nguồn sự thật cho kiểu TS (docs/07 §1, T7.5): đủ route, mô tả, khớp bản chốt."""

import json
from typing import Any

import pytest

from scripts.dump_openapi import DEFAULT_OUT, build_openapi, render

# Mọi endpoint ở docs/07 §3 (method, đường dẫn thật).
DOCUMENTED = {
    ("get", "/api/health"),
    ("post", "/api/chat"),
    ("get", "/api/chat/{run_id}/events"),
    ("get", "/api/chat/{run_id}"),
    ("get", "/api/conversations"),
    ("get", "/api/conversations/{conversation_id}/messages"),
    ("get", "/api/products"),
    ("get", "/api/products/{product_id}"),
    ("get", "/api/products/{product_id}/price-history"),
    ("post", "/api/compare"),
    ("get", "/api/categories"),
    ("get", "/api/lists"),
    ("post", "/api/lists"),
    ("get", "/api/lists/{list_id}"),
    ("patch", "/api/lists/{list_id}"),
    ("delete", "/api/lists/{list_id}"),
    ("post", "/api/lists/{list_id}/items"),
    ("patch", "/api/lists/{list_id}/items/{item_id}"),
    ("delete", "/api/lists/{list_id}/items/{item_id}"),
    ("get", "/api/alerts"),
    ("post", "/api/alerts"),
    ("patch", "/api/alerts/{alert_id}"),
    ("delete", "/api/alerts/{alert_id}"),
    ("post", "/api/alerts/{alert_id}/test"),
    ("get", "/api/admin/sources"),
    ("get", "/api/admin/scrape-runs"),
    ("get", "/api/admin/scrape-runs/{run_id}"),
    ("post", "/api/admin/scrape-runs"),
    ("get", "/api/admin/scrape-runs/{run_id}/challenge"),
    ("post", "/api/admin/scrape-runs/{run_id}/challenge"),
    ("delete", "/api/admin/scrape-runs/{run_id}/challenge"),
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return build_openapi()


def operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    methods = {"get", "post", "put", "patch", "delete"}
    return [
        (method, path, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if method in methods
    ]


def test_every_documented_endpoint_exists_and_nothing_undocumented_is_exposed(
    schema: dict[str, Any],
) -> None:
    exposed = {(method, path) for method, path, _ in operations(schema)}

    assert exposed == DOCUMENTED


def test_every_operation_has_a_summary_and_a_unique_operation_id(schema: dict[str, Any]) -> None:
    ops = operations(schema)

    assert all(op.get("summary", "").strip() for _, _, op in ops)
    ids = [op["operationId"] for _, _, op in ops]
    assert len(ids) == len(set(ids))


def test_every_operation_declares_the_standard_error_bodies(schema: dict[str, Any]) -> None:
    for method, path, op in operations(schema):
        for status in ("422", "500"):
            body = op["responses"][status]["content"]["application/json"]["schema"]
            assert body == {"$ref": "#/components/schemas/ErrorResponse"}, (method, path, status)
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_every_success_response_has_a_typed_body_unless_it_has_none_by_design(
    schema: dict[str, Any],
) -> None:
    for method, path, op in operations(schema):
        success = {s: r for s, r in op["responses"].items() if s.startswith("2")}
        assert len(success) == 1, (method, path)
        ((status, response),) = success.items()
        if status == "204":
            assert "content" not in response, (method, path)
        elif path.endswith("/events"):
            assert "text/event-stream" in response["content"], (method, path)
        else:
            assert response["content"]["application/json"]["schema"], (method, path)


def test_background_endpoints_answer_202(schema: dict[str, Any]) -> None:
    assert "202" in schema["paths"]["/api/chat"]["post"]["responses"]
    assert "202" in schema["paths"]["/api/admin/scrape-runs"]["post"]["responses"]


def test_money_and_ids_are_integers_in_the_contract(schema: dict[str, Any]) -> None:
    schemas = schema["components"]["schemas"]

    for model, field in [
        ("ProductSummary", "min_price"),
        ("ProductSummary", "product_id"),
        ("AlertView", "target_price"),
        ("ShoppingListSummary", "total_price"),
    ]:
        assert schemas[model]["properties"][field]["type"] == "integer", (model, field)


def test_committed_snapshot_matches_the_app_so_generated_types_are_current(
    schema: dict[str, Any],
) -> None:
    committed = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))

    assert committed == schema, (
        "frontend/openapi.json lệch với API hiện tại: chạy `make gen-api` rồi commit "
        "frontend/openapi.json và frontend/src/api/types.gen.ts"
    )


def test_rendering_is_stable_and_keeps_vietnamese_text(schema: dict[str, Any]) -> None:
    text = render(schema)

    assert text == render(build_openapi())
    assert text.endswith("}\n")
    assert "Kiểm tra sức khỏe hệ thống" in text  # không bị escape thành \uXXXX
