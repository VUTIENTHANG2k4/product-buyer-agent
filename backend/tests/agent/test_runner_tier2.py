"""T10.3: kịch bản tầng 2 ("loa bluetooth dưới 1 triệu") với ScriptedChatModel và service giả."""

from typing import Any

from sqlmodel import Session, select

from app.agent.executor import FINAL_TOOL
from app.agent.runner import AgentRunner
from app.agent.schemas import FinalEvent, PlanEvent, ToolEndEvent, ToolStartEvent
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.agent.tools import ToolContext
from app.db.models import Product
from app.domain.enums import SiteKey
from app.domain.live_search import LiveSearchResult
from tests.agent.conftest import collect, names
from tests.agent.test_tool_live_search import StubLiveSearch, item
from tests.service_support import clock, make_settings

SPEAKER_INTENT: dict[str, Any] = {
    "category": "other",
    "tier": 2,
    "keywords": ["loa bluetooth"],
    "price_max": 1_000_000,
    "plan_steps": ["Tìm trực tiếp loa bluetooth", "Lọc dưới 1 triệu"],
}
SEARCH = tool_call_message(
    "live_search_other", {"query": "loa bluetooth", "price_max": 1_000_000}, "c1"
)


def found_two() -> LiveSearchResult:
    return LiveSearchResult(
        items=[item(SiteKey.gearvn, 1, 590_000), item(SiteKey.fptshop, 2, 890_000)],
        sites_searched=[SiteKey.gearvn, SiteKey.fptshop],
        sites_skipped=[],
        from_cache=False,
    )


def live_dict(n: int, site: SiteKey, price: int) -> dict[str, Any]:
    shown = item(site, n, price)
    return {
        "site": shown.site.value,
        "title": shown.title,
        "price": shown.price,
        "url": shown.url,
        "scraped_at": shown.scraped_at.isoformat(),
    }


def runner_with(
    tool_ctx: ToolContext, executor_script: list[Any], live: StubLiveSearch
) -> AgentRunner:
    return AgentRunner(
        tool_ctx.session_factory,
        make_settings(),
        planner_model=ScriptedChatModel(script=[SPEAKER_INTENT]),
        executor_model=ScriptedChatModel(script=executor_script),
        now=clock,
        live_search=live,  # type: ignore[arg-type]
    )


async def test_tier_two_question_streams_plan_live_tool_and_live_items(
    db_session: Session, tool_ctx: ToolContext
) -> None:
    live = StubLiveSearch(found_two())
    answer = tool_call_message(
        FINAL_TOOL,
        {
            "text": "Kết quả tìm trực tiếp, chưa chuẩn hóa thông số: 2 loa.",
            "live_items": [
                live_dict(1, SiteKey.gearvn, 590_000),
                live_dict(2, SiteKey.fptshop, 890_000),
            ],
        },
        "f1",
    )
    runner = runner_with(tool_ctx, [SEARCH, answer], live)

    events = await collect(runner, "loa bluetooth dưới 1 triệu")

    assert names(events) == ["plan", "tool_start", "tool_end", "final"]
    plan, start, end, final = events
    assert isinstance(plan, PlanEvent) and plan.intent.tier == 2
    assert isinstance(start, ToolStartEvent) and start.tool == "live_search_other"
    assert isinstance(end, ToolEndEvent) and end.summary == "Tìm trực tiếp: 2 kết quả từ 2 trang"
    assert isinstance(final, FinalEvent)
    assert [i.url for i in final.live_items] == [
        "https://shop.example/gearvn/loa-1",
        "https://shop.example/fptshop/loa-2",
    ]
    assert final.table == []
    assert live.calls[0]["price_max"] == 1_000_000
    assert db_session.exec(select(Product)).first() is None  # tầng 2 không ghi Product


async def test_live_items_the_tool_never_returned_are_dropped_by_the_guardrail(
    tool_ctx: ToolContext,
) -> None:
    live = StubLiveSearch(found_two())
    fabricated = {**live_dict(9, SiteKey.gearvn, 100_000), "url": "https://evil.example/loa"}
    answer = tool_call_message(
        FINAL_TOOL,
        {"text": "Có 2 loa.", "live_items": [live_dict(1, SiteKey.gearvn, 590_000), fabricated]},
        "f1",
    )

    events = await collect(runner_with(tool_ctx, [SEARCH, answer], live), "loa bluetooth")

    final = events[-1]
    assert isinstance(final, FinalEvent)
    assert [i.url for i in final.live_items] == ["https://shop.example/gearvn/loa-1"]


async def test_tier_two_without_a_service_still_answers_without_inventing_results(
    tool_ctx: ToolContext,
) -> None:
    runner = AgentRunner(
        tool_ctx.session_factory,
        make_settings(),
        planner_model=ScriptedChatModel(script=[SPEAKER_INTENT]),
        executor_model=ScriptedChatModel(
            script=[
                SEARCH,
                tool_call_message(FINAL_TOOL, {"text": "Chưa tìm được nhóm này."}, "f1"),
            ]
        ),
        now=clock,
    )

    events = await collect(runner, "loa bluetooth dưới 1 triệu")

    end = next(e for e in events if isinstance(e, ToolEndEvent))
    final = events[-1]
    assert end.summary == "Tìm trực tiếp chưa khả dụng"
    assert isinstance(final, FinalEvent) and final.live_items == []
