"""X1.10: `search_catalog` chỉ dùng điều kiện người dùng nêu (ý định của planner hoặc câu hỏi).

Hội thoại 50 (2026-11-09) "tai nghe gaming giá dưới 1 triệu": lần tìm đầu đã đủ 25 sản phẩm nhưng
Gemini gọi thêm với `has_mic=true`, rồi danh sách hãng HyperX/Razer/JBL/SteelSeries/E-Dra.
"""

import json
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.executor import LoopOutcome, ToolLoop
from app.agent.guardrail import ground_search_args
from app.agent.schemas import ToolStartEvent
from app.agent.testing import ScriptedChatModel, tool_call_message
from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category
from tests.agent.test_executor_qa_m6 import final

HEADSET_MESSAGE = "tai nghe gaming giá dưới 1 triệu"
HEADSET_INTENT = QueryIntent(
    category=Category.headset, keywords=["gaming"], price_max=1_000_000, plan_steps=["Tìm"]
)


def test_conversation_50_drops_the_invented_mic_filter_and_brand_list() -> None:
    args = {
        "category": "headset",
        "price_max": 1_000_000,
        "keywords": ["gaming"],
        "brands": ["HyperX", "Razer", "JBL", "SteelSeries", "E-Dra"],
        "spec_filters": [{"field": "has_mic", "op": "eq", "value": True}],
    }

    grounded, dropped = ground_search_args(args, HEADSET_INTENT, HEADSET_MESSAGE)

    assert grounded == {
        "category": "headset",
        "price_max": 1_000_000,
        "keywords": ["gaming"],
        "brands": [],
        "spec_filters": [],
    }
    assert dropped == [
        "hãng HyperX",
        "hãng Razer",
        "hãng JBL",
        "hãng SteelSeries",
        "hãng E-Dra",
        "has_mic eq True",
    ]


@pytest.mark.parametrize(
    ("message", "intent_brands", "brands"),
    [
        ("điện thoại Samsung dưới 10 triệu", ["Samsung"], ["Samsung"]),
        ("dien thoai samsung duoi 10 trieu", [], ["Samsung"]),  # planner quên: câu vẫn có hãng
        ("laptop ASUS hoặc Lenovo gaming", ["ASUS", "Lenovo"], ["asus", "LENOVO"]),
        ("chuột rẻ nhất", ["Logitech"], ["Logitech"]),  # lượt trước đã chọn hãng (ngữ cảnh)
    ],
)
def test_brands_named_by_the_user_or_the_intent_are_kept(
    message: str, intent_brands: list[str], brands: list[str]
) -> None:
    intent = QueryIntent(category=Category.phone, brands=intent_brands)

    grounded, dropped = ground_search_args({"brands": brands}, intent, message)

    assert grounded["brands"] == brands
    assert dropped == []


def test_a_brand_is_matched_as_a_whole_word_only() -> None:
    intent = QueryIntent(category=Category.headset)

    grounded, dropped = ground_search_args({"brands": ["HP"]}, intent, "tai nghe chụp tai")

    assert grounded["brands"] == [] and dropped == ["hãng HP"]


def test_a_spec_filter_on_a_field_from_the_intent_may_be_relaxed() -> None:
    intent = QueryIntent(
        category=Category.laptop,
        spec_filters=[SpecFilter(field="ram_gb", op="gte", value=32)],
    )
    args = {
        "spec_filters": [
            {"field": "ram_gb", "op": "gte", "value": 16},
            {"field": "refresh_hz", "op": "gte", "value": 144},
        ]
    }

    grounded, dropped = ground_search_args(args, intent, "laptop ram 32gb")

    assert grounded["spec_filters"] == [{"field": "ram_gb", "op": "gte", "value": 16}]
    assert dropped == ["refresh_hz gte 144"]


def test_a_brand_put_in_spec_filters_is_judged_like_brands() -> None:
    intent = QueryIntent(category=Category.phone, brands=["Samsung"])
    args = {
        "spec_filters": [
            {"field": "brand", "op": "eq", "value": "Samsung"},
            {"field": "brand", "op": "in", "value": ["Samsung", "Xiaomi"]},
        ]
    }

    grounded, dropped = ground_search_args(args, intent, "điện thoại Samsung")

    assert grounded["spec_filters"] == [{"field": "brand", "op": "eq", "value": "Samsung"}]
    assert dropped == ["hãng Samsung, Xiaomi"]


@pytest.mark.parametrize(
    ("keywords", "kept"),
    [
        (["gaming"], ["gaming"]),
        (["Gaming"], ["Gaming"]),
        (["tai nghe", "gaming"], ["gaming"]),  # tên nhóm không lọc theo tên
        (["không dây"], []),  # người dùng không nói
        (["HyperX"], []),
    ],
)
def test_keywords_must_come_from_the_intent_or_the_message(
    keywords: list[str], kept: list[str]
) -> None:
    grounded, _ = ground_search_args({"keywords": keywords}, HEADSET_INTENT, HEADSET_MESSAGE)

    assert grounded["keywords"] == kept


def test_a_keyword_equal_to_an_intent_brand_is_dropped() -> None:
    intent = QueryIntent(category=Category.mouse, brands=["Logitech"], keywords=["logitech"])

    grounded, dropped = ground_search_args(
        {"keywords": ["logitech"]}, intent, "chuot logitech re nhat"
    )

    assert grounded["keywords"] == [] and dropped == ["từ khóa logitech"]


def test_malformed_arguments_are_left_for_the_tool_to_reject() -> None:
    args: dict[str, Any] = {"brands": "Samsung", "spec_filters": [42, {"field": 1}], "keywords": 3}

    grounded, dropped = ground_search_args(args, HEADSET_INTENT, HEADSET_MESSAGE)

    assert grounded == args and dropped == []


async def test_the_loop_searches_without_the_invented_filters_and_tells_the_llm(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    invented = {
        "category": "headset",
        "price_max": 1_000_000,
        "brands": ["Razer"],
        "spec_filters": [{"field": "has_mic", "op": "eq", "value": False}],
    }
    model = ScriptedChatModel(script=[tool_call_message("search_catalog", invented, "c1"), final()])
    messages: list[BaseMessage] = [HumanMessage(content=HEADSET_MESSAGE)]
    loop = ToolLoop(
        model,
        [tools["search_catalog"]],
        max_steps=4,
        allowed_writes=frozenset(),
        intent=HEADSET_INTENT,
        message=HEADSET_MESSAGE,
    )

    events = [event async for event in loop.run(messages, LoopOutcome())]

    (result_message,) = [m for m in messages if isinstance(m, ToolMessage)]
    result = json.loads(str(result_message.content))
    assert result["ok"] is True and result["total"] > 0
    assert result["ignored_filters"] == ["hãng Razer", "has_mic eq False"]
    assert "brands" not in result["applied_filters"]
    assert "spec_filters" not in result["applied_filters"]
    start = next(event for event in events if isinstance(event, ToolStartEvent))
    assert "Razer" not in start.args_summary  # người dùng thấy đúng điều kiện đã dùng


async def test_without_an_intent_the_loop_passes_arguments_through(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    args = {"category": "headset", "brands": ["Razer"]}
    model = ScriptedChatModel(script=[tool_call_message("search_catalog", args, "c1"), final()])
    messages: list[BaseMessage] = [HumanMessage(content="x")]
    loop = ToolLoop(model, [tools["search_catalog"]], max_steps=4, allowed_writes=frozenset())

    _ = [event async for event in loop.run(messages, LoopOutcome())]

    (result_message,) = [m for m in messages if isinstance(m, ToolMessage)]
    result = json.loads(str(result_message.content))
    assert result["applied_filters"]["brands"] == ["Razer"]
    assert "ignored_filters" not in result
