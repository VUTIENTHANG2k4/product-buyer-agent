"""T6.3: Planner với ScriptedChatModel, prompt snapshot, QueryIntent chặt hơn."""

import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agent.planner import Planner, build_messages, render_planner_prompt
from app.agent.testing import ScriptedChatModel
from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category
from app.domain.errors import LlmUnavailable

SNAPSHOT = Path(__file__).parent / "snapshots" / "planner_prompt.md"


def good_intent(**fields: Any) -> dict[str, Any]:
    return {
        "category": "laptop",
        "tier": 1,
        "price_max": 30_000_000,
        "spec_filters": [{"field": "gpu_rank", "op": "gte", "value": 40}],
        "plan_steps": ["Tìm laptop", "Lọc giá và GPU"],
        **fields,
    }


async def test_plan_returns_postprocessed_intent() -> None:
    model = ScriptedChatModel(script=[good_intent(price_max=30)])  # sai đơn vị tiền
    intent = await Planner(model).plan("laptop gaming dưới 30 triệu RTX 4060")

    assert intent.category is Category.laptop
    assert intent.price_max == 30_000_000
    assert intent.spec_filters == [SpecFilter(field="gpu_rank", op="gte", value=40)]
    assert len(model.calls) == 1


async def test_request_contains_system_prompt_and_user_message() -> None:
    model = ScriptedChatModel(script=[good_intent()])
    await Planner(model).plan("  laptop dưới 30 triệu  ")

    system, human = model.calls[0]
    assert isinstance(system, SystemMessage) and system.content == render_planner_prompt()
    assert isinstance(human, HumanMessage) and human.content == "laptop dưới 30 triệu"


async def test_history_is_included_but_limited_to_the_last_three_messages() -> None:
    model = ScriptedChatModel(script=[good_intent()])
    history = ["một", "hai", "ba", "bốn"]

    await Planner(model).plan("so sánh 2 máy rẻ nhất", history)

    body = str(model.calls[0][1].content)
    assert "- hai\n- ba\n- bốn" in body and "một" not in body
    assert body.endswith("Yêu cầu hiện tại:\nso sánh 2 máy rẻ nhất")


async def test_unknown_field_triggers_one_retry_with_the_error_in_the_prompt() -> None:
    model = ScriptedChatModel(script=[good_intent(max_price=30_000_000), good_intent()])

    intent = await Planner(model).plan("laptop dưới 30 triệu")

    assert intent.price_max == 30_000_000
    assert len(model.calls) == 2
    retry_message = str(model.calls[1][-1].content)
    assert retry_message.startswith("Kết quả trước không hợp lệ")
    assert "max_price" in retry_message


@pytest.mark.parametrize(
    "bad",
    [
        good_intent(price_min=50_000_000),  # khoảng giá ngược
        good_intent(limit=50),
        good_intent(price_max="ba mươi triệu"),
        good_intent(spec_filters=[{"field": "ram_gb", "op": "gte", "value": "16", "extra": 1}]),
    ],
)
async def test_two_invalid_answers_raise_llm_unavailable(bad: dict[str, Any]) -> None:
    model = ScriptedChatModel(script=[bad, bad])

    with pytest.raises(LlmUnavailable, match="ý định hợp lệ") as caught:
        await Planner(model).plan("laptop")

    assert isinstance(caught.value.__cause__, ValueError)
    assert len(model.calls) == 2


async def test_provider_error_is_not_retried_and_becomes_llm_unavailable() -> None:
    model = ScriptedChatModel(script=[TimeoutError("quá hạn"), good_intent()])

    with pytest.raises(LlmUnavailable) as caught:
        await Planner(model).plan("laptop")

    assert caught.value.details == {"stage": "planner"}
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert len(model.calls) == 1


async def test_clarification_intent_passes_through_with_a_question() -> None:
    model = ScriptedChatModel(script=[{"needs_clarification": True}])

    intent = await Planner(model).plan("tìm cái nào rẻ rẻ")

    assert intent.needs_clarification and intent.clarification_question


async def test_overlong_message_is_truncated_before_sending() -> None:
    model = ScriptedChatModel(script=[good_intent()])
    await Planner(model).plan("a" * 5000)
    assert len(str(model.calls[0][1].content)) == 1000


# ---- QueryIntent / SpecFilter chặt hơn ----
def test_query_intent_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="max_price"):
        QueryIntent.model_validate({"max_price": 1})


def test_spec_filter_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate({"field": "ram_gb", "op": "gte", "value": 1, "unit": "GB"})


def test_assignment_is_validated() -> None:
    intent = QueryIntent(price_min=10, price_max=20)
    with pytest.raises(ValidationError):
        intent.price_min = 30
    with pytest.raises(ValidationError):
        intent.limit = 99


def test_json_schema_forbids_additional_properties() -> None:
    schema = QueryIntent.model_json_schema()
    assert schema["additionalProperties"] is False


# ---- prompt ----
def test_prompt_renders_gpu_table_from_code_and_has_no_placeholder() -> None:
    prompt = render_planner_prompt()
    assert "{{" not in prompt
    assert "  - RTX 4060 = 40" in prompt
    assert prompt.index("RTX 3050 = 20") < prompt.index("RTX 4090 = 80")


def test_prompt_covers_the_rules_of_docs_05() -> None:
    prompt = render_planner_prompt()
    for phrase in ("30000000", "±10%", "gpu_rank", "needs_clarification", "dữ liệu cần phân tích"):
        assert phrase in prompt


def test_build_messages_without_history_sends_message_as_is() -> None:
    messages = build_messages("laptop", [])
    assert messages[1].content == "laptop"


def test_prompt_matches_snapshot() -> None:
    """Đổi prompt có chủ ý: chạy lại với UPDATE_SNAPSHOTS=1 rồi xem diff của file snapshot."""
    rendered = render_planner_prompt() + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(rendered, encoding="utf-8", newline="\n")
    expected = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert rendered == expected
