"""QA M6: tool với đầu vào biên (id ngoài miền, NUL, bộ lọc lạ) và giới hạn 4.000 ký tự."""

import json
from typing import Any

import pytest
from langchain_core.tools import BaseTool
from sqlmodel import Session, text

from app.agent.tools.base import MAX_RESULT_CHARS, clip, limit_size, size_of
from tests.agent.conftest import call
from tests.service_support import add_offer, add_product

NUL = chr(0)
HUGE = 2**31  # vượt INTEGER của khóa chính (id)


def stays_in_bounds(result: dict[str, Any]) -> bool:
    return result["ok"] is False and result["error"] == "VALIDATION_ERROR"


# ---- id ngoài miền INTEGER của khóa chính phải bị từ chối gọn (BUG-M6-5) ----
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_product_detail", {"product_id": HUGE}),
        ("get_product_detail", {"product_id": 10**30}),
        ("get_product_detail", {"product_id": 2**63}),
        ("get_price_history", {"product_id": HUGE, "days": 30}),
        ("compare_products", {"product_ids": [1, HUGE]}),
        ("add_to_shopping_list", {"product_id": HUGE}),
        ("create_price_alert", {"product_id": HUGE, "target_price": 1_000}),
    ],
)
async def test_product_id_beyond_bigint_is_a_validation_error_not_a_system_error(
    db_session: Session, tools: dict[str, BaseTool], tool: str, args: dict[str, Any]
) -> None:
    result = await call(tools, tool, **args)
    assert stays_in_bounds(result) and "product_id" in result["message"]


@pytest.mark.parametrize("product_id", [0, -1, 2**31 - 1])
async def test_edge_product_ids_give_not_found_or_validation_never_a_crash(
    db_session: Session, tools: dict[str, BaseTool], product_id: int
) -> None:
    result = await call(tools, "get_product_detail", product_id=product_id)
    assert result["ok"] is False
    assert result["error"] in ("VALIDATION_ERROR", "PRODUCT_NOT_FOUND")


# ---- NUL và chuỗi lạ ----
@pytest.mark.parametrize(
    "args",
    [
        {"brands": ["Mock" + NUL]},
        {"spec_filters": [{"field": "gpu_model", "op": "eq", "value": "RTX" + NUL}]},
        {"spec_filters": [{"field": "gpu" + NUL, "op": "eq", "value": "RTX"}]},
        {"spec_filters": [{"field": "x'; DROP TABLE product;--", "op": "gte", "value": 1}]},
        {"spec_filters": [{"field": "é" * 5000, "op": "gte", "value": 1}]},
        {"spec_filters": [{"field": "f", "op": "contains_any", "value": []}]},
        {"spec_filters": [{"field": "f", "op": "in", "value": ["a", NUL]}]},
    ],
)
async def test_search_catalog_survives_hostile_filter_strings(
    db_session: Session, tools: dict[str, BaseTool], args: dict[str, Any]
) -> None:
    add_offer(db_session, add_product(db_session))

    result = await call(tools, "search_catalog", category="laptop", **args)

    assert result["ok"] is True or stays_in_bounds(result), result
    assert db_session.execute(text("SELECT count(*) FROM product")).scalar_one() >= 1


@pytest.mark.parametrize(
    "args",
    [{"list_name": "Mua" + NUL}, {"note": "ghi chú" + NUL}, {"list_name": "x" * 101}],
)
async def test_add_to_shopping_list_rejects_bad_text_with_an_error_result(
    db_session: Session, tools: dict[str, BaseTool], args: dict[str, Any]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)

    result = await call(tools, "add_to_shopping_list", product_id=product.id, **args)

    assert result["ok"] is False and result["error"] in ("VALIDATION_ERROR", "VALIDATION_FAILED")
    assert db_session.execute(text("SELECT count(*) FROM shopping_list")).scalar_one() == 0


# ---- giới hạn tham số ----
@pytest.mark.parametrize("limit", [0, 21, -1, 100])
async def test_search_catalog_limit_outside_1_to_20_is_rejected(
    db_session: Session, tools: dict[str, BaseTool], limit: int
) -> None:
    assert stays_in_bounds(await call(tools, "search_catalog", category="laptop", limit=limit))


@pytest.mark.parametrize("limit", [1, 20])
async def test_search_catalog_limit_boundaries_are_accepted(
    db_session: Session, tools: dict[str, BaseTool], limit: int
) -> None:
    for _ in range(21):
        add_offer(db_session, add_product(db_session))

    result = await call(tools, "search_catalog", category="laptop", limit=limit)

    # 20 mục dài hơn 4.000 ký tự nên có thể bị bớt (truncated); tổng thật vẫn là 21.
    assert result["ok"] is True and result["total"] == 21
    assert len(result["items"]) == limit or result.get("truncated") is True
    assert 1 <= len(result["items"]) <= limit


async def test_zero_price_ceiling_is_a_valid_empty_search_that_reports_the_filter(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    add_offer(db_session, add_product(db_session))

    result = await call(tools, "search_catalog", category="laptop", price_max=0)

    assert (result["ok"], result["total"], result["items"]) == (True, 0, [])
    assert result["applied_filters"]["price_max"] == 0


@pytest.mark.parametrize("ids", [[1, 1], [1], [1, 2, 3, 4, 5, 6], [], [0, 5]])
async def test_compare_products_rejects_wrong_id_lists_with_an_error_result(
    db_session: Session, tools: dict[str, BaseTool], ids: list[int]
) -> None:
    result = await call(tools, "compare_products", product_ids=ids)
    assert result["ok"] is False


@pytest.mark.parametrize("target", [0, -5, 10**12 + 1, "hai mươi triệu", 2.5, None])
async def test_create_price_alert_rejects_nonsense_thresholds(
    db_session: Session, tools: dict[str, BaseTool], target: Any
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)

    result = await call(tools, "create_price_alert", product_id=product.id, target_price=target)

    assert stays_in_bounds(result)
    assert db_session.execute(text("SELECT count(*) FROM price_alert")).scalar_one() == 0


# ---- giới hạn 4.000 ký tự của limit_size ----
def _items(count: int, width: int) -> dict[str, Any]:
    return {
        "ok": True,
        "total": count,
        "items": [{"product_id": i, "name": "Chuột Mock " + "ệ" * width} for i in range(count)],
    }


@pytest.mark.parametrize("count", [1, 2, 5, 9, 17, 33, 60])
@pytest.mark.parametrize("width", [10, 120, 700])
def test_limit_size_result_always_fits_and_keeps_a_prefix(count: int, width: int) -> None:
    original = _items(count, width)

    result = limit_size(original, ("items",))

    if size_of(original) <= MAX_RESULT_CHARS:
        assert result is original
        return
    assert size_of(result) <= MAX_RESULT_CHARS
    if result.get("ok") is False:
        assert result["error"] == "RESULT_TOO_LARGE"
    else:
        assert result["truncated"] is True
        assert result["items"] == original["items"][: len(result["items"])]
        assert result["total"] == count  # tổng thật vẫn được giữ


def test_limit_size_boundary_is_exact() -> None:
    base = {"ok": True, "items": [{"v": ""}]}
    pad = MAX_RESULT_CHARS - size_of(base)
    exact = {"ok": True, "items": [{"v": "x" * pad}]}
    over = {"ok": True, "items": [{"v": "x" * (pad + 1)}]}

    assert size_of(exact) == MAX_RESULT_CHARS and limit_size(exact, ("items",)) is exact
    trimmed = limit_size(over, ("items",))
    assert size_of(trimmed) <= MAX_RESULT_CHARS and trimmed.get("truncated") is True


def test_limit_size_with_unknown_list_key_gives_the_compact_error() -> None:
    huge = {"ok": True, "items": ["x" * 5000]}
    assert limit_size(huge, ("nope",))["error"] == "RESULT_TOO_LARGE"


def test_limit_size_does_not_mutate_its_input() -> None:
    original = _items(40, 300)
    snapshot = json.dumps(original, ensure_ascii=False)
    limit_size(original, ("items",))
    assert json.dumps(original, ensure_ascii=False) == snapshot


@pytest.mark.parametrize(
    ("raw", "limit", "expected_len"),
    [("", 5, 0), ("abcde", 5, 5), ("abcdef", 5, 5), ("ab  cdefgh", 5, 3), ("x" * 1000, 1, 1)],
)
def test_clip_never_exceeds_its_limit(raw: str, limit: int, expected_len: int) -> None:
    clipped = clip(raw, limit)
    assert len(clipped) == expected_len and len(clipped) <= limit
