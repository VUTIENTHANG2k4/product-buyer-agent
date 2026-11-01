"""T6.4: tool ghi (add_to_shopping_list, create_price_alert) và list_alerts."""

import pytest
from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.tools import MAX_RESULT_CHARS, ToolContext, build_tools
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel, AlertStatus
from app.services.alert_service import AlertService
from app.services.shopping_list_service import ShoppingListService
from tests.agent.conftest import call, size
from tests.service_support import add_offer, add_product, clock, make_settings


def lists(session: Session) -> ShoppingListService:
    return ShoppingListService(session, now=clock)


def alerts(session: Session) -> AlertService:
    return AlertService(session, make_settings(), now=clock)


# ---- add_to_shopping_list ----
async def test_add_to_shopping_list_creates_the_default_list_and_persists_the_item(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=25_000_000)

    result = await call(tools, "add_to_shopping_list", product_id=product.id, quantity=2)

    assert result["ok"] is True
    assert (result["list_name"], result["product_id"], result["quantity"]) == (
        "Danh sách mua",
        product.id,
        2,
    )
    assert (result["price_at_add"], result["current_price"]) == (25_000_000, 25_000_000)
    detail = lists(db_session).get_list(result["list_id"])
    assert [(i.item_id, i.quantity) for i in detail.items] == [(result["item_id"], 2)]
    assert detail.total_price == 50_000_000


async def test_add_to_shopping_list_uses_named_list_and_accumulates_quantity(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)

    first = await call(
        tools, "add_to_shopping_list", product_id=product.id, list_name="Mock học tập", note="a"
    )
    second = await call(
        tools, "add_to_shopping_list", product_id=product.id, list_name="Mock học tập"
    )

    assert first["list_id"] == second["list_id"] and second["quantity"] == 2
    assert len(lists(db_session).list_lists()) == 1


async def test_add_to_shopping_list_unknown_product_returns_error_and_creates_nothing(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    result = await call(tools, "add_to_shopping_list", product_id=999_999)

    assert result["ok"] is False and result["error"] == "PRODUCT_NOT_FOUND"
    assert lists(db_session).list_lists() == []


@pytest.mark.parametrize(
    "args",
    [{"product_id": 0}, {"product_id": 1, "quantity": 0}, {"product_id": 1, "quantity": 101}]
    + [{"product_id": 1, "note": "x" * 201}, {"product_id": 1, "list_name": "x" * 101}],
)
async def test_add_to_shopping_list_rejects_bad_arguments_without_writing(
    db_session: Session, tools: dict[str, BaseTool], args: dict[str, object]
) -> None:
    result = await call(tools, "add_to_shopping_list", **args)

    assert result["error"] == "VALIDATION_ERROR"
    assert lists(db_session).list_lists() == []


# ---- create_price_alert ----
async def test_create_price_alert_uses_configured_destination(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)

    result = await call(tools, "create_price_alert", product_id=product.id, target_price=25_000_000)

    assert result == {
        "ok": True,
        "alert_id": result["alert_id"],
        "product_id": product.id,
        "target_price": 25_000_000,
        "channel": "email",
        "current_best_price": 27_000_000,
    }
    (stored,) = alerts(db_session).list_alerts()
    assert (stored.destination, stored.status) == ("mock@example.com", AlertStatus.active)
    assert "destination" not in str(result)  # địa chỉ nhận không đi qua LLM


async def test_create_price_alert_has_no_destination_argument(tools: dict[str, BaseTool]) -> None:
    assert set(tools["create_price_alert"].args) == {"product_id", "target_price", "channel"}


async def test_create_price_alert_duplicate_and_unknown_product_are_error_results(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    first = await call(tools, "create_price_alert", product_id=product.id, target_price=10)

    duplicate = await call(tools, "create_price_alert", product_id=product.id, target_price=10)
    unknown = await call(tools, "create_price_alert", product_id=999_999, target_price=10)

    assert first["ok"] is True
    assert duplicate["error"] == "DUPLICATE_ALERT" and unknown["error"] == "PRODUCT_NOT_FOUND"
    assert len(alerts(db_session).list_alerts()) == 1


async def test_create_price_alert_without_configured_destination_explains_why(
    db_session: Session, tool_ctx: ToolContext
) -> None:
    ctx = ToolContext(
        session_factory=tool_ctx.session_factory,
        settings=make_settings(alert_default_email=""),
        now=clock,
    )
    tools = {tool.name: tool for tool in build_tools(ctx)}
    product = add_product(db_session)

    result = await call(tools, "create_price_alert", product_id=product.id, target_price=10)

    assert result["error"] == "VALIDATION_ERROR" and "Chưa cấu hình" in result["message"]
    assert alerts(db_session).list_alerts() == []


async def test_create_price_alert_telegram_channel_needs_a_chat_id(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    result = await call(
        tools, "create_price_alert", product_id=product.id, target_price=10, channel="telegram"
    )
    assert result["error"] == "VALIDATION_ERROR" and "telegram" in result["message"]


@pytest.mark.parametrize("price", [0, -1, 10**12 + 1])
async def test_create_price_alert_rejects_bad_target_price(
    tools: dict[str, BaseTool], price: int
) -> None:
    result = await call(tools, "create_price_alert", product_id=1, target_price=price)
    assert result["error"] == "VALIDATION_ERROR"


# ---- list_alerts ----
async def test_list_alerts_returns_compact_rows_without_destinations(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=30_000_000)
    created = alerts(db_session).create(AlertCreate(product_id=product.id or 0, target_price=25))

    result = await call(tools, "list_alerts")

    assert result["total"] == 1
    (row,) = result["alerts"]
    assert row == {
        "alert_id": created.alert_id,
        "product_id": product.id,
        "product_name": product.canonical_name,
        "target_price": 25,
        "channel": "email",
        "status": "active",
        "current_best_price": 30_000_000,
    }


async def test_list_alerts_filters_by_status_and_validates_it(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session)
    service = alerts(db_session)
    paused = service.create(AlertCreate(product_id=product.id or 0, target_price=10))
    service.update(paused.alert_id, status=AlertStatus.paused)
    service.create(AlertCreate(product_id=product.id or 0, target_price=20))

    only_paused = await call(tools, "list_alerts", status="paused")
    nothing = await call(tools, "list_alerts", status="triggered")
    bad = await call(tools, "list_alerts", status="expired")

    assert [a["alert_id"] for a in only_paused["alerts"]] == [paused.alert_id]
    assert (nothing["total"], nothing["alerts"]) == (0, [])
    assert bad["error"] == "VALIDATION_ERROR"


async def test_list_alerts_caps_rows_but_reports_the_total_within_size_limit(
    db_session: Session, tools: dict[str, BaseTool]
) -> None:
    product = add_product(db_session, canonical_name="Sản phẩm " + "dài " * 50)
    service = alerts(db_session)
    for target in range(1, 26):
        service.create(AlertCreate(product_id=product.id or 0, target_price=target))
    assert AlertChannel.email  # kênh mặc định

    result = await call(tools, "list_alerts")

    assert result["total"] == 25 and len(result["alerts"]) <= 20
    assert size(result) <= MAX_RESULT_CHARS
