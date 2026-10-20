"""T6.4: hợp đồng chung của 8 tool (docs/05 §3) và hàm nền."""

import json
import re
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from sqlmodel import Session

from app.agent.tools import TOOL_NAMES, WRITE_TOOLS, ToolContext
from app.agent.tools.base import (
    MAX_RESULT_CHARS,
    clip,
    error_result,
    limit_size,
    run_in_session,
    size_of,
)
from app.agent.tools.get_price_history import MAX_POINTS_PER_SITE, downsample
from app.domain.catalog import PricePointView
from app.domain.enums import PriceType
from app.domain.errors import ProductNotFound
from tests.agent.conftest import call
from tests.service_support import NOW

DOCS = Path(__file__).resolve().parents[3] / "docs" / "05-agent-design.md"


def test_tool_names_and_order_match_the_docs_table() -> None:
    rows = re.findall(r"^\| \d \| `(\w+)` \|", DOCS.read_text(encoding="utf-8"), re.MULTILINE)
    assert list(TOOL_NAMES) == rows
    assert len(TOOL_NAMES) == 8


def test_only_the_two_write_tools_are_marked_as_writers() -> None:
    assert {"add_to_shopping_list", "create_price_alert"} == WRITE_TOOLS


def test_every_tool_has_a_description_and_documented_arguments(
    tools: dict[str, BaseTool],
) -> None:
    assert list(tools) == list(TOOL_NAMES)
    for name, tool in tools.items():
        assert 20 < len(tool.description) < 500, name
        for field, spec in tool.args.items():
            assert spec.get("description"), f"{name}.{field} thiếu mô tả"


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tool_descriptions_require_an_explicit_user_request(
    tools: dict[str, BaseTool], name: str
) -> None:
    assert "ONLY call when the user explicitly asks" in tools[name].description


@pytest.mark.parametrize("name", [n for n in TOOL_NAMES if n not in WRITE_TOOLS])
def test_read_tool_descriptions_do_not_ask_for_writes(
    tools: dict[str, BaseTool], name: str
) -> None:
    assert "explicitly asks" not in tools[name].description


async def test_tool_call_dict_returns_a_tool_message_with_json_content(
    seeded: Session, tools: dict[str, BaseTool]
) -> None:
    message = await tools["search_catalog"].ainvoke(
        {
            "name": "search_catalog",
            "args": {"category": "laptop", "limit": 2},
            "id": "c1",
            "type": "tool_call",
        }
    )
    assert isinstance(message, ToolMessage) and message.tool_call_id == "c1"
    parsed = json.loads(str(message.content))
    assert parsed["ok"] is True and len(parsed["items"]) == 2


async def test_invalid_arguments_return_a_short_validation_error_for_the_llm(
    tools: dict[str, BaseTool],
) -> None:
    result = await call(tools, "search_catalog", category="laptop", limit=99)
    assert result["ok"] is False and result["error"] == "VALIDATION_ERROR"
    assert "limit" in result["message"]
    assert len(json.dumps(result)) < 400


# ---- hàm nền ----
def test_clip_keeps_short_text_and_marks_cut_text() -> None:
    assert clip("abc", 5) == "abc"
    assert clip("a" * 20, 10) == "a" * 9 + "…"
    assert len(clip("x" * 500)) == 120


def test_limit_size_returns_same_object_when_small() -> None:
    small = {"ok": True, "items": [1, 2, 3]}
    assert limit_size(small, ("items",)) is small


def test_limit_size_drops_trailing_items_and_flags_truncation() -> None:
    big = {"ok": True, "items": [{"text": "x" * 300, "n": i} for i in range(40)]}

    result = limit_size(big, ("items",))

    assert size_of(result) <= MAX_RESULT_CHARS
    assert result["truncated"] is True
    assert 0 < len(result["items"]) < 40
    assert [item["n"] for item in result["items"]] == list(range(len(result["items"])))
    assert len(big["items"]) == 40  # đầu vào không bị sửa


def test_limit_size_trims_the_longest_list_first() -> None:
    result = limit_size({"a": ["x" * 200] * 10, "b": ["y" * 200] * 30}, ("a", "b"), limit=7000)
    assert len(result["a"]) == 10 and len(result["b"]) < 30


def test_limit_size_gives_up_with_a_short_error_when_lists_cannot_shrink_enough() -> None:
    result = limit_size({"ok": True, "items": [], "blob": "z" * 5000}, ("items",))
    assert result == error_result("RESULT_TOO_LARGE", "Kết quả quá lớn, hãy thu hẹp yêu cầu")


def test_downsample_keeps_first_and_last_and_the_limit() -> None:
    points = [
        PricePointView(t=NOW, price=1000 + i, price_type=PriceType.regular) for i in range(100)
    ]

    sampled = downsample(points)

    assert len(sampled) == MAX_POINTS_PER_SITE
    assert sampled[0].price == 1000 and sampled[-1].price == 1099
    assert [p.price for p in sampled] == sorted(p.price for p in sampled)
    assert downsample(points[:10]) == points[:10]


async def test_run_in_session_turns_domain_errors_into_error_results(
    tool_ctx: ToolContext,
) -> None:
    def work(session: Session) -> dict[str, object]:
        raise ProductNotFound(details={"product_id": 7})

    result = await run_in_session(tool_ctx, work)

    assert result == {
        "ok": False,
        "error": "PRODUCT_NOT_FOUND",
        "message": ProductNotFound.default_message,
    }


async def test_run_in_session_lets_system_errors_escape(tool_ctx: ToolContext) -> None:
    def work(session: Session) -> dict[str, object]:
        raise RuntimeError("hỏng thật")

    with pytest.raises(RuntimeError, match="hỏng thật"):
        await run_in_session(tool_ctx, work)
