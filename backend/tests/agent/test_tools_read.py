"""T6.4: 5 tool chỉ đọc trên seed `dev` (docs/05 §3, tool 1-5)."""

from datetime import timedelta
from typing import Any

from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.tools import MAX_RESULT_CHARS
from app.agent.tools.live_search_other import NOT_ENABLED_REASON
from app.db.models import Offer
from app.domain.enums import Category
from tests.agent.conftest import call, size
from tests.factories import make_price_history
from tests.service_support import NOW, add_offer, add_product

SEARCH_KEYS = {
    "product_id",
    "name",
    "brand",
    "category",
    "key_specs",
    "min_price",
    "max_price",
    "best_offer",
    "offers_count",
}


# ---- search_catalog ----
async def test_search_catalog_follows_the_documented_shape(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(
        tools,
        "search_catalog",
        category="laptop",
        price_max=30_000_000,
        spec_filters=[{"field": "gpu_rank", "op": "gte", "value": 40}],
        sort="price_asc",
        limit=5,
    )

    assert result["ok"] is True
    assert set(result) >= {"total", "items", "stale", "data_as_of", "applied_filters"}
    assert result["total"] >= 3 and 0 < len(result["items"]) <= 5
    assert result["stale"] is False and result["data_as_of"].startswith("2026-10-20")
    assert result["applied_filters"]["price_max"] == 30_000_000
    prices = [item["min_price"] for item in result["items"]]
    assert prices == sorted(prices) and prices[-1] <= 30_000_000
    for item in result["items"]:
        assert set(item) == SEARCH_KEYS
        assert set(item["best_offer"]) == {"site", "price", "price_type", "url", "scraped_at"}
        assert item["category"] == "laptop" and len(item["key_specs"]) <= 6
    assert size(result) <= MAX_RESULT_CHARS


async def test_search_catalog_with_twenty_results_stays_within_the_size_limit(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(tools, "search_catalog", category="laptop", limit=20)

    assert size(result) <= MAX_RESULT_CHARS
    assert result["total"] >= 20 and len(result["items"]) >= 5
    if len(result["items"]) < 20:
        assert result["truncated"] is True


async def test_search_catalog_filters_by_site_and_brand(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(tools, "search_catalog", category="laptop", sites=["gearvn"], limit=5)

    assert result["items"]
    assert all(item["best_offer"]["site"] == "gearvn" for item in result["items"])


async def test_search_catalog_without_matches_is_an_ok_empty_result(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(tools, "search_catalog", category="laptop", price_max=1_000)
    assert (result["ok"], result["total"], result["items"]) == (True, 0, [])
    assert result["data_as_of"] is None and result["stale"] is False


async def test_search_catalog_flags_stale_data(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    add_offer(db_session, add_product(db_session), scraped_at=NOW - timedelta(hours=30))

    result = await call(tools, "search_catalog", category="laptop")

    assert result["stale"] is True


async def test_search_catalog_rejects_tier_two_categories_and_bad_filters(
    tools: dict[str, BaseTool],
) -> None:
    other = await call(tools, "search_catalog", category="other")
    bad_op = await call(
        tools,
        "search_catalog",
        category="laptop",
        spec_filters=[{"field": "ram_gb", "op": "gte", "value": "nhiều"}],
    )
    no_category = await call(tools, "search_catalog")
    unknown_arg_field = await call(
        tools,
        "search_catalog",
        category="laptop",
        spec_filters=[{"field": "ram_gb", "op": "gte", "value": 8, "unit": "GB"}],
    )

    for result in (other, bad_op, no_category, unknown_arg_field):
        assert result["ok"] is False and result["error"] == "VALIDATION_ERROR"


async def test_search_catalog_hides_out_of_stock_only_products(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session, category=Category.mouse, specs={})
    add_offer(db_session, product, stock_status="out_of_stock")

    result = await call(tools, "search_catalog", category="mouse")

    assert result["total"] == 0


# ---- live_search_other ----
async def test_live_search_other_is_a_documented_placeholder_until_tier_two(
    tools: dict[str, BaseTool],
) -> None:
    result = await call(tools, "live_search_other", query="loa bluetooth", price_max=1_000_000)

    assert result["ok"] is True and result["items"] == []
    assert result["sites_searched"] == [] and result["from_cache"] is False
    assert result["label"] == "unnormalized" and result["reason"] == NOT_ENABLED_REASON
    assert {s["site"] for s in result["sites_skipped"]} == {"viettelstore", "nguyenkim"}
    assert all(s["reason"] == NOT_ENABLED_REASON for s in result["sites_skipped"])


async def test_live_search_other_validates_arguments(tools: dict[str, BaseTool]) -> None:
    for args in ({"query": ""}, {"query": "x" * 201}, {"query": "loa", "limit_per_site": 11}):
        result = await call(tools, "live_search_other", **args)
        assert result["error"] == "VALIDATION_ERROR"


# ---- compare_products ----
async def _two_laptops(tools: dict[str, BaseTool]) -> list[int]:
    found = await call(tools, "search_catalog", category="laptop", sort="price_asc", limit=2)
    return [item["product_id"] for item in found["items"]]


async def test_compare_products_returns_differences_and_cheapest(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    ids = await _two_laptops(tools)

    result = await call(tools, "compare_products", product_ids=ids)

    assert result["ok"] is True
    assert [p["product_id"] for p in result["products"]] == ids
    assert result["cheapest_product_id"] in ids
    for field in result["differing_fields"]:
        values = {str(p["specs"].get(field)) for p in result["products"]}
        assert len(values) > 1
    assert all(len(p["offers"]) <= 3 for p in result["products"])
    assert size(result) <= MAX_RESULT_CHARS


async def test_compare_five_products_stays_within_the_size_limit(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    found = await call(tools, "search_catalog", category="laptop", limit=5)
    ids = [item["product_id"] for item in found["items"]]

    result = await call(tools, "compare_products", product_ids=ids)

    assert size(result) <= MAX_RESULT_CHARS
    assert len(result["products"]) >= 2


async def test_compare_products_error_cases(seeded: Session, tools: dict[str, BaseTool]) -> None:
    ids = await _two_laptops(tools)

    unknown = await call(tools, "compare_products", product_ids=[ids[0], 999_999])
    single = await call(tools, "compare_products", product_ids=[ids[0]])
    six = await call(tools, "compare_products", product_ids=list(range(1, 7)))
    duplicate = await call(tools, "compare_products", product_ids=[ids[0], ids[0]])

    assert unknown["error"] == "PRODUCT_NOT_FOUND"
    assert single["error"] == "VALIDATION_ERROR" and six["error"] == "VALIDATION_ERROR"
    assert duplicate["error"] == "VALIDATION_ERROR"


# ---- get_product_detail ----
async def test_get_product_detail_has_specs_and_offers(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    (product_id,) = (await _two_laptops(tools))[:1]

    result = await call(tools, "get_product_detail", product_id=product_id)

    assert result["ok"] is True and result["product_id"] == product_id
    assert result["specs"]["gpu_rank"] is not None or "ram_gb" in result["specs"]
    assert 0 < len(result["offers"]) <= 8
    assert {"offer_id", "site", "price", "stock_status", "url", "scraped_at"} <= set(
        result["offers"][0]
    )
    assert result["min_price"] <= result["max_price"]


async def test_get_product_detail_clips_long_web_names_and_unknown_id(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session, canonical_name="Laptop " + "rất dài " * 60)
    add_offer(db_session, product)

    result = await call(tools, "get_product_detail", product_id=product.id)
    unknown = await call(tools, "get_product_detail", product_id=999_999)
    zero = await call(tools, "get_product_detail", product_id=0)

    assert len(result["name"]) <= 120 and result["name"].endswith("…")
    assert unknown["error"] == "PRODUCT_NOT_FOUND"
    assert zero["error"] == "VALIDATION_ERROR"


async def test_get_product_detail_many_offers_fit_the_limit(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    for i in range(15):
        add_offer(db_session, product, price=20_000_000 + i, title="t" * 300)

    result = await call(tools, "get_product_detail", product_id=product.id)

    assert len(result["offers"]) == 8 and size(result) <= MAX_RESULT_CHARS


# ---- get_price_history ----
async def test_get_price_history_groups_by_site_with_min_max(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    (product_id,) = (await _two_laptops(tools))[:1]

    result = await call(tools, "get_price_history", product_id=product_id, days=30)

    assert result["ok"] is True and result["days"] == 30
    assert result["series"]
    for series in result["series"]:
        assert series["point_count"] >= len(series["points"]) > 0
        assert set(series["points"][0]) == {"t", "price"}
    prices = [p["price"] for s in result["series"] for p in s["points"]]
    assert result["min_price"] <= min(prices) and result["max_price"] >= max(prices)
    assert size(result) <= MAX_RESULT_CHARS


async def test_get_price_history_downsamples_long_series(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    offer: Offer = add_offer(db_session, product)
    assert offer.id is not None
    for day in range(120):
        db_session.add(
            make_price_history(
                offer.id, price=20_000_000 + day, scraped_at=NOW - timedelta(days=120 - day)
            )
        )
    db_session.flush()

    result = await call(tools, "get_price_history", product_id=product.id, days=180)

    (series,) = result["series"]
    assert series["point_count"] == 120 and len(series["points"]) == 30
    assert series["points"][0]["price"] == 20_000_000
    assert series["points"][-1]["price"] == 20_000_119
    assert size(result) <= MAX_RESULT_CHARS


async def test_get_price_history_errors(db_session: Session, tools: dict[str, BaseTool]) -> None:
    product = add_product(db_session)

    assert (await call(tools, "get_price_history", product_id=999_999))["error"] == (
        "PRODUCT_NOT_FOUND"
    )
    for days in (0, 181):
        result = await call(tools, "get_price_history", product_id=product.id, days=days)
        assert result["error"] == "VALIDATION_ERROR"
    empty: dict[str, Any] = await call(tools, "get_price_history", product_id=product.id)
    assert (empty["series"], empty["min_price"], empty["max_price"]) == ([], None, None)
