"""T8.11: `LLM_PROVIDER=fake` trả lời xác định trên seed `e2e` (E2E và ảnh chụp giao diện)."""

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlmodel import Session

from app.agent.fake_llm import (
    CLARIFICATION,
    ShoppingFakeChatModel,
    answer_from_results,
    plan_from_text,
)
from app.agent.llm import get_chat_model
from app.agent.runner import AgentRunner
from app.agent.schemas import (
    ClarificationEvent,
    ErrorEvent,
    FinalAnswer,
    FinalEvent,
    PlanEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from app.agent.tools import ToolContext
from app.api.deps import get_agent_runner, get_session, get_session_factory
from app.config import get_settings
from app.domain.enums import Category
from app.main import create_app
from app.mock_shop.main import create_app as create_mock_shop
from app.scrapers.http.types import FetchResponse
from app.services.live_search_service import LiveSearchService
from scripts.seed import seed_database
from tests.agent.conftest import collect, names
from tests.api.test_chat_api import settle
from tests.service_support import NOW, clock, make_settings


@pytest.fixture
def fake_runner(db_session: Session, tool_ctx: ToolContext) -> Callable[[], AgentRunner]:
    """`AgentRunner` dựng đúng như API: model lấy từ `get_chat_model` với `LLM_PROVIDER=fake`."""
    seed_database(db_session, "e2e", now=NOW)
    settings = make_settings(llm_provider="fake")

    def build() -> AgentRunner:
        return AgentRunner(
            tool_ctx.session_factory,
            settings,
            planner_model=get_chat_model("planner", settings),
            executor_model=get_chat_model("executor", settings),
            now=clock,
        )

    return build


# ---- planner ----
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("laptop gaming dưới 30 triệu", Category.laptop),
        ("tìm chuot khong day", Category.mouse),
        ("Bàn phím cơ TKL switch Red", Category.keyboard),
        ("tai nghe có mic dưới 2 triệu", Category.headset),
    ],
)
def test_planner_recognises_the_category_with_or_without_diacritics(
    text: str, category: Category
) -> None:
    intent = plan_from_text(text)
    assert intent.category is category
    assert intent.needs_clarification is False


@pytest.mark.parametrize(
    ("text", "price_min", "price_max"),
    [
        ("laptop dưới 30 triệu", None, 30_000_000),
        ("laptop tối đa 25tr", None, 25_000_000),
        ("laptop trên 20 triệu", 20_000_000, None),
        ("laptop 27 triệu", None, 27_000_000),
        ("laptop gaming", None, None),
    ],
)
def test_planner_reads_the_price_range_from_the_request(
    text: str, price_min: int | None, price_max: int | None
) -> None:
    intent = plan_from_text(text)
    assert (intent.price_min, intent.price_max) == (price_min, price_max)
    assert intent.sort == "price_asc"


def test_planner_uses_only_the_current_request_when_history_is_prepended() -> None:
    body = "Các yêu cầu trước của người dùng:\n- chuột\n\nYêu cầu hiện tại:\nlaptop dưới 30 triệu"
    assert plan_from_text(body).category is Category.laptop


@pytest.mark.parametrize(
    ("text", "keyword", "price_max"),
    [
        ("loa bluetooth dưới 1 triệu", "loa bluetooth", 1_000_000),
        ("Tìm loa kéo", "loa", None),
        ("ổ cứng SSD 1TB", "ssd", None),
        ("màn hình 27 inch dưới 6 triệu", "màn hình", 6_000_000),
    ],
)
def test_planner_routes_other_categories_to_tier_two(
    text: str, keyword: str, price_max: int | None
) -> None:
    intent = plan_from_text(text)
    assert (intent.tier, intent.category, intent.keywords) == (2, Category.other, [keyword])
    assert intent.price_max == price_max and intent.needs_clarification is False


def test_tier_one_words_win_over_tier_two_words() -> None:
    assert plan_from_text("tai nghe có loa").category is Category.headset


@pytest.mark.parametrize("text", ["", "xin chào", "   "])
def test_planner_asks_back_when_no_supported_category_is_named(text: str) -> None:
    intent = plan_from_text(text)
    assert intent.needs_clarification is True
    assert intent.clarification_question == CLARIFICATION
    assert intent.category is None


# ---- executor ----
def test_executor_calls_search_catalog_with_the_analysed_intent() -> None:
    intent_line = (
        'Ý định đã phân tích: {"category":"laptop","price_max":30000000,"sort":"price_asc",'
        '"spec_filters":[{"field":"gpu_rank","op":"gte","value":40}]}'
    )
    reply = ShoppingFakeChatModel().invoke([HumanMessage(content=f"{intent_line}\nYêu cầu: x")])
    assert isinstance(reply, AIMessage)
    (call,) = reply.tool_calls
    assert call["name"] == "search_catalog"
    assert call["args"]["category"] == "laptop"
    assert call["args"]["price_max"] == 30_000_000
    assert call["args"]["spec_filters"] == [{"field": "gpu_rank", "op": "gte", "value": 40}]


def test_executor_calls_live_search_other_for_a_tier_two_intent() -> None:
    intent_line = (
        'Ý định đã phân tích: {"category":"other","tier":2,"keywords":["loa bluetooth"],'
        '"price_max":1000000}'
    )
    turn = f"{intent_line}\nYêu cầu: x"
    reply = ShoppingFakeChatModel().invoke([HumanMessage(content=turn)])
    assert isinstance(reply, AIMessage)
    (call,) = reply.tool_calls
    assert call["name"] == "live_search_other"
    assert call["args"] == {
        "query": "loa bluetooth",
        "price_min": None,
        "price_max": 1_000_000,
        "limit_per_site": 5,
    }


def test_live_answer_copies_items_from_the_tool_result_and_labels_them() -> None:
    item = {
        "site": "mockshop",
        "title": "Loa Bluetooth Sony Mock Boom B3",
        "price": 890_000,
        "url": "http://localhost:8100/p/sony-mock-boom-b3-mk-lo002",
        "scraped_at": "2026-10-20T12:00:00+00:00",
    }
    unpriced = {
        **item,
        "title": "Loa Xiaomi Mock",
        "price": None,
        "url": "http://localhost:8100/p/x",
    }
    result = {
        "ok": True,
        "items": [item, unpriced],
        "sites_searched": ["mockshop"],
        "sites_skipped": [{"site": "gearvn", "reason": "chế độ ngoại tuyến"}],
        "from_cache": False,
        "label": "unnormalized",
    }

    answer = answer_from_results([result])

    assert [live.model_dump() for live in answer.live_items] == [item, unpriced]
    assert answer.product_ids == []
    assert "chưa chuẩn hóa thông số" in answer.text
    assert "890.000 ₫" in answer.text and "gearvn" in answer.text


def test_live_answer_without_items_says_nothing_was_found() -> None:
    result = {"ok": True, "items": [], "sites_skipped": [], "label": "unnormalized"}

    answer = answer_from_results([result])

    assert answer.live_items == [] and "Chưa tìm thấy" in answer.text


@pytest.mark.parametrize("turn", ["không có dòng ý định", "Ý định đã phân tích: không phải json"])
def test_executor_without_a_usable_intent_answers_without_tools(turn: str) -> None:
    reply = ShoppingFakeChatModel().invoke([HumanMessage(content=turn)])
    assert isinstance(reply, AIMessage)
    (call,) = reply.tool_calls
    assert call["name"] == "FinalAnswer"
    assert call["args"]["product_ids"] == []


def test_answer_with_no_items_says_so_and_lists_no_products() -> None:
    answer = answer_from_results([{"ok": True, "total": 0, "items": []}])
    assert isinstance(answer, FinalAnswer)
    assert answer.product_ids == [] and "Không tìm thấy" in answer.text


def test_answer_only_uses_ids_and_prices_found_in_the_tool_result() -> None:
    items = [
        {
            "product_id": 7 + n,
            "name": f"Mock {n}",
            "best_offer": {"site": "gearvn", "price": 20_000_000 + n},
        }
        for n in range(8)
    ]
    answer = answer_from_results([{"ok": True, "total": 8, "items": items}])
    assert answer.product_ids == [7, 8, 9, 10, 11]
    assert "20.000.000 ₫" in answer.text and "gearvn" in answer.text


def test_tool_messages_of_previous_turns_are_ignored() -> None:
    old = ToolMessage(content='{"items": [{"product_id": 1}]}', tool_call_id="x", name="t")
    turn = HumanMessage(content='Ý định đã phân tích: {"category":"mouse"}')
    reply = ShoppingFakeChatModel().invoke([old, turn])
    assert isinstance(reply, AIMessage)
    assert reply.tool_calls[0]["name"] == "search_catalog"


# ---- cả lượt qua AgentRunner trên seed e2e ----
async def test_laptop_question_streams_plan_tool_and_a_table_from_the_database(
    fake_runner: Callable[[], AgentRunner],
) -> None:
    events = await collect(fake_runner(), "laptop gaming dưới 40 triệu, RTX 4050 trở lên")

    assert names(events) == ["plan", "tool_start", "tool_end", "final"]
    plan, start, end, final = events
    assert isinstance(plan, PlanEvent) and plan.intent.category is Category.laptop
    assert plan.intent.price_max == 40_000_000
    assert any(spec.field == "gpu_rank" for spec in plan.intent.spec_filters)
    assert len(plan.steps) >= 2
    assert isinstance(start, ToolStartEvent) and start.tool == "search_catalog"
    assert isinstance(end, ToolEndEvent) and end.ok
    assert isinstance(final, FinalEvent)
    assert 1 <= len(final.table) <= 5
    prices = [row.min_price for row in final.table if row.min_price is not None]
    assert len(prices) == len(final.table)
    assert prices == sorted(prices)
    assert all(price <= 40_000_000 for price in prices)
    assert final.suggestions == ["So sánh 2 sản phẩm rẻ nhất", "Đặt cảnh báo giá"]
    assert final.data_as_of == NOW


async def test_every_supported_category_returns_a_table(
    fake_runner: Callable[[], AgentRunner],
) -> None:
    runner = fake_runner()
    for message in ("chuột không dây", "bàn phím cơ", "tai nghe có mic"):
        events = await collect(runner, message)
        final = events[-1]
        assert isinstance(final, FinalEvent), message
        assert final.table, message


async def test_vague_question_asks_back_without_calling_any_tool(
    fake_runner: Callable[[], AgentRunner],
) -> None:
    events = await collect(fake_runner(), "tôi muốn mua đồ")
    assert names(events) == ["plan", "clarification"]
    assert isinstance(events[1], ClarificationEvent) and events[1].question == CLARIFICATION


async def test_search_with_no_match_ends_with_an_empty_table_and_no_error(
    fake_runner: Callable[[], AgentRunner],
) -> None:
    events = await collect(fake_runner(), "laptop dưới 10.000.000")
    final = events[-1]
    assert not any(isinstance(event, ErrorEvent) for event in events)
    assert isinstance(final, FinalEvent) and final.table == []
    assert "Không tìm thấy" in final.text


async def test_odd_input_does_not_crash_the_run(fake_runner: Callable[[], AgentRunner]) -> None:
    runner = fake_runner()
    for message in ("<script>alert(1)</script> laptop", "laptop " + "x" * 900, "Đà Nẵng 🙂 chuột"):
        events = await collect(runner, message)
        assert events[-1].name in {"final", "clarification"}, message


def test_post_chat_with_the_fake_provider_ends_with_a_table(
    db_session: Session, fake_runner: Callable[[], AgentRunner]
) -> None:
    """Đúng đường E2E: POST /chat → chạy nền → GET /chat/{run_id} có `final.table` từ CSDL."""
    bind = db_session.get_bind()

    def factory() -> Session:
        return Session(bind=bind, join_transaction_mode="create_savepoint")

    runner = fake_runner()
    settings = make_settings(llm_provider="fake")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_agent_runner] = lambda: runner
    with TestClient(app) as client:
        accepted = client.post("/api/chat", json={"message": "laptop gaming dưới 40 triệu"})
        assert accepted.status_code == 202
        settle(client)
        body = client.get(f"/api/chat/{accepted.json()['run_id']}").json()

    assert body["status"] == "succeeded"
    assert body["final"]["table"], body
    assert body["final"]["table"][0]["offers"][0]["site"] in {"gearvn", "fptshop", "anphat"}


# ---- tầng 2 trọn vẹn: planner giả → live_search_other → service → mock-shop (ASGI) ----
class MockShopAsgiFetcher:
    """PageFetcher gọi mock-shop trong tiến trình; chỉ test dùng, không mạng."""

    def __init__(self) -> None:
        self._transport = httpx.ASGITransport(app=create_mock_shop(captcha_after=10**6))

    async def get(self, url: str) -> FetchResponse:
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.get(url)
        return FetchResponse(
            url=url, final_url=str(response.url), status=response.status_code, text=response.text
        )


async def test_speaker_question_returns_live_items_found_in_the_mock_shop(
    tool_ctx: ToolContext,
) -> None:
    settings = make_settings(llm_provider="fake", scraper_offline_only=True)
    runner = AgentRunner(
        tool_ctx.session_factory,
        settings,
        planner_model=get_chat_model("planner", settings),
        executor_model=get_chat_model("executor", settings),
        now=clock,
        live_search=LiveSearchService(
            tool_ctx.session_factory, settings, MockShopAsgiFetcher(), clock
        ),
    )

    events = await collect(runner, "loa bluetooth dưới 1 triệu")

    assert names(events) == ["plan", "tool_start", "tool_end", "final"]
    plan, start, end, final = events
    assert isinstance(plan, PlanEvent) and (plan.intent.tier, plan.intent.category) == (
        2,
        Category.other,
    )
    assert isinstance(start, ToolStartEvent) and start.tool == "live_search_other"
    assert isinstance(end, ToolEndEvent) and end.ok
    assert isinstance(final, FinalEvent)
    assert [live.title for live in final.live_items] == [
        "Loa Bluetooth Edifier Mock Mini M1",
        "Loa Bluetooth Sony Mock Boom B3",
    ]
    assert [live.price for live in final.live_items] == [590_000, 890_000]
    assert all(live.site == "mockshop" for live in final.live_items)
    assert final.table == []
    assert "chưa chuẩn hóa thông số" in final.text and "590.000 ₫" in final.text
