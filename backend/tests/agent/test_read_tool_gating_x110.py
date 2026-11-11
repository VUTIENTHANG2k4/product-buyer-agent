"""X1.10: `compare_products`, `get_product_detail`, `get_price_history` chỉ có khi người dùng hỏi.

Eval P01 (2026-11-09, ×10): sau khi `search_catalog` đã đủ kết quả, Gemini vẫn gọi thêm
`get_product_detail` ×2, `compare_products`, `get_price_history` ở ~70% lần chạy (p50 30 s thay vì
15 s); dặn trong prompt không đổi gì. Không đưa ba tool đó cho LLM thì nó không gọi được.
"""

from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from app.agent.executor import FINAL_TOOL, LoopOutcome, ToolLoop
from app.agent.guardrail import READ_ON_REQUEST_TOOLS, allowed_read_tools
from app.agent.testing import ScriptedChatModel, tool_call_message
from tests.agent.test_executor_qa_m6 import Driven, Fake, final

COMPARE = "compare_products"
DETAIL = "get_product_detail"
HISTORY = "get_price_history"
NONE: frozenset[str] = frozenset()
ALL = READ_ON_REQUEST_TOOLS


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # câu tìm kiếm trong eval: không mở tool nào
        ("điện thoại Samsung dưới 10 triệu", NONE),
        ("laptop core i7 ram 32gb ssd 1tb", NONE),
        ("phím cơ không dây hotswap tầm 2 triệu", NONE),
        ("tai nghe gaming giá dưới 1 triệu", NONE),
        ("tìm giúp tôi các laptop gaming dưới 30 triệu có card RTX 4060", NONE),
        ("laptop ASUS hoặc Lenovo gaming dưới 28 triệu", NONE),
        ("chuot logitech re nhat", NONE),
        ("iPhone nào rẻ nhất", NONE),
        ("laptop gaming trên GearVN dưới 30 triệu", NONE),
        ("máy tính trên 20 triệu", NONE),
        ("chuột màu đỏ dưới 500k", NONE),
        # câu hỏi tiếp theo trong eval
        ("so sánh 2 máy rẻ nhất", frozenset({COMPARE})),
        ("so sanh 2 may re nhat", frozenset({COMPARE})),
        ("cái đầu tiên giá dạo này thế nào", ALL),
        ("chi tiết cái thứ 3", ALL),
        ("chi tiet cai thu 3", ALL),
        # cách nói khác
        ("máy nào tốt hơn?", frozenset({COMPARE})),
        ("Asus TUF vs Lenovo LOQ khác nhau gì", frozenset({COMPARE})),
        ("cho xem thông số của Legion 5", frozenset({DETAIL})),
        ("cấu hình con Legion 5 thế nào", frozenset({DETAIL})),
        ("lịch sử giá của Legion 5", frozenset({HISTORY})),
        ("giá Legion 5 gần đây có giảm không", frozenset({HISTORY})),
        ("máy thứ hai còn bảo hành bao lâu", ALL),
        # phủ định trước động từ
        ("tai nghe dưới 1 triệu, không cần so sánh", NONE),
        ("đừng xem chi tiết, chỉ cần danh sách", NONE),
    ],
)
def test_read_tools_are_allowed_only_when_the_message_asks(
    message: str, expected: frozenset[str]
) -> None:
    assert allowed_read_tools(message) == expected


async def run_loop(script: list[Any], tools: list[Fake], hidden: frozenset[str]) -> Driven:
    model = ScriptedChatModel(script=script)
    messages: list[BaseMessage] = [HumanMessage(content="điện thoại Samsung dưới 10 triệu")]
    outcome = LoopOutcome()
    loop = ToolLoop(
        model,
        [fake.tool for fake in tools],
        max_steps=6,
        allowed_writes=frozenset(),
        hidden_tools=hidden,
    )
    events = [event async for event in loop.run(messages, outcome)]
    return Driven(events, outcome, messages, model)


async def test_hidden_read_tools_are_not_offered_to_the_llm() -> None:
    tools = [Fake("search_catalog"), Fake(DETAIL), Fake(COMPARE), Fake(HISTORY)]

    run = await run_loop([final()], tools, ALL)

    assert run.model.bound_tool_names == ["search_catalog", FINAL_TOOL]


async def test_a_hidden_tool_called_anyway_is_refused_without_running() -> None:
    search, detail = Fake("search_catalog"), Fake(DETAIL)
    script = [
        tool_call_message("search_catalog", {"n": 1}, "c1"),
        tool_call_message(DETAIL, {"product_id": 7}, "c2"),
        final(),
    ]

    run = await run_loop(script, [search, detail], ALL)

    assert len(search.calls) == 1 and detail.calls == []
    assert run.error_codes() == ["TOOL_NOT_REQUESTED"]
    assert run.outcome.stop_reason == "final"
    assert DETAIL not in run.outcome.calls_by_tool


async def test_tools_the_user_asked_for_stay_available() -> None:
    compare = Fake(COMPARE)
    script = [tool_call_message(COMPARE, {"n": 1}, "c1"), final()]

    run = await run_loop(script, [Fake("search_catalog"), compare], frozenset({DETAIL, HISTORY}))

    assert COMPARE in run.model.bound_tool_names
    assert len(compare.calls) == 1 and run.error_codes() == []
