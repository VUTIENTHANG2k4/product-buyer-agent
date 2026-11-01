"""Model chat giả xác định cho `LLM_PROVIDER=fake` (E2E và ảnh chụp giao diện, docs/05 §2, docs/09).

Khác `ScriptedChatModel` (kịch bản định sẵn từng lượt, dùng trong test đơn vị), model này đọc câu
hỏi và trả lời theo luật cố định, nên backend thật chạy được nhiều câu hỏi khác nhau mà không cần
khóa LLM: planner nhận ra nhóm hàng + giá + GPU, executor gọi `search_catalog` một lần rồi trả
`FinalAnswer` từ kết quả tool. Nhóm ngoài tầng 1 (loa, SSD, màn hình) là tầng 2: executor gọi
`live_search_other` rồi trả `live_items` lấy nguyên từ kết quả tool. Không gọi mạng, không dùng
ngẫu nhiên. Câu hỏi không nêu nhóm hàng thì planner hỏi lại.
"""

import json
from collections.abc import Sequence
from typing import Any, Final

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda

from app.agent.intent import extract_amounts
from app.agent.schemas import FinalAnswer, LiveItem
from app.domain.dto import QueryIntent
from app.domain.enums import Category
from app.normalize.text import fold

CLARIFICATION: Final = "Bạn muốn tìm loại sản phẩm nào (laptop, chuột, bàn phím, tai nghe…)?"
INTENT_PREFIX: Final = "Ý định đã phân tích: "
CURRENT_REQUEST: Final = "Yêu cầu hiện tại:\n"
MAX_TABLE_ROWS: Final = 5

_CATEGORY_WORDS: Final = (
    (Category.laptop, ("laptop", "macbook", "may tinh xach tay")),
    (Category.mouse, ("chuot", "mouse")),
    (Category.keyboard, ("ban phim", "keyboard")),
    (Category.headset, ("tai nghe", "headset", "headphone")),
)
# Nhóm tầng 2 (không dấu) -> từ khóa tìm trực tiếp; cụm dài đứng trước.
_TIER2_QUERIES: Final = (
    ("loa bluetooth", "loa bluetooth"),
    ("loa", "loa"),
    ("ssd", "ssd"),
    ("o cung", "ổ cứng"),
    ("man hinh", "màn hình"),
)
_MAX_WORDS: Final = ("duoi", "toi da", "khong qua", "<")
_MIN_WORDS: Final = ("tren", "tu ", "it nhat", ">")


def _last_human_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def plan_from_text(text: str) -> QueryIntent:
    """`QueryIntent` từ câu hỏi (nhóm hàng, khoảng giá); GPU và bước kế hoạch do planner bổ sung."""
    request = text.rsplit(CURRENT_REQUEST, 1)[-1]
    folded = fold(request)
    category = next(
        (cat for cat, words in _CATEGORY_WORDS if any(word in folded for word in words)), None
    )
    live_query = next((query for word, query in _TIER2_QUERIES if word in folded), None)
    if category is None and live_query is None:
        return QueryIntent(needs_clarification=True, clarification_question=CLARIFICATION)

    price_min: int | None = None
    price_max: int | None = None
    amounts = extract_amounts(request)
    if amounts:
        if any(word in folded for word in _MIN_WORDS) and not any(
            word in folded for word in _MAX_WORDS
        ):
            price_min = min(amounts)
        else:
            price_max = max(amounts)
    if category is None and live_query is not None:
        return QueryIntent(
            category=Category.other,
            tier=2,
            keywords=[live_query],
            price_min=price_min,
            price_max=price_max,
        )
    return QueryIntent(
        category=category, price_min=price_min, price_max=price_max, sort="price_asc"
    )


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + " ₫"


def _tool_results(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    """Kết quả (dict JSON) của các tool trong lượt hiện tại, sau tin nhắn người dùng cuối."""
    results: list[dict[str, Any]] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage):
            try:
                parsed = json.loads(str(message.content))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                results.append(parsed)
    return list(reversed(results))


def _intent_from_turn(messages: Sequence[BaseMessage]) -> QueryIntent | None:
    for line in _last_human_text(messages).splitlines():
        if line.startswith(INTENT_PREFIX):
            try:
                return QueryIntent.model_validate_json(line[len(INTENT_PREFIX) :])
            except ValueError:
                return None
    return None


def _live_answer(live: dict[str, Any]) -> FinalAnswer:
    """`FinalAnswer` tầng 2: `live_items` copy nguyên từ `items` của `live_search_other`."""
    items: list[dict[str, Any]] = list(live.get("items", []))[:MAX_TABLE_ROWS]
    skipped = [str(entry["site"]) for entry in live.get("sites_skipped", [])]
    note = f" (bỏ qua: {', '.join(skipped)})" if skipped else ""
    if not items:
        return FinalAnswer(
            text=f"Chưa tìm thấy kết quả trực tiếp phù hợp{note}. Bạn thử đổi từ khóa nhé."
        )
    priced = [item for item in items if item.get("price") is not None]
    cheapest = min(priced, key=lambda item: int(item["price"])) if priced else None
    text = f"Kết quả tìm trực tiếp, chưa chuẩn hóa thông số: {len(items)} kết quả{note}."
    if cheapest is not None:
        text += f" Rẻ nhất là **{cheapest['title']}**, giá {_vnd(int(cheapest['price']))}."
    return FinalAnswer(
        text=text,
        live_items=[
            LiveItem(
                site=str(item["site"]),
                title=str(item["title"]),
                price=item.get("price"),
                url=str(item["url"]),
                scraped_at=item.get("scraped_at"),
            )
            for item in items
        ],
        follow_up_suggestions=["Nới khoảng giá", "Tìm từ khóa khác"],
    )


def answer_from_results(results: Sequence[dict[str, Any]]) -> FinalAnswer:
    """`FinalAnswer` chỉ dùng id/giá có trong kết quả `search_catalog` (không bịa gì thêm)."""
    live = next((result for result in results if result.get("label") == "unnormalized"), None)
    if live is not None:
        return _live_answer(live)
    search = next((result for result in results if "items" in result), None)
    items: list[dict[str, Any]] = list(search["items"]) if search else []
    if not items:
        return FinalAnswer(
            text="Không tìm thấy sản phẩm phù hợp trong dữ liệu hiện có. Bạn thử nới điều kiện nhé."
        )
    shown = items[:MAX_TABLE_ROWS]
    cheapest = shown[0]
    best = cheapest["best_offer"]
    text = (
        f"Có {search['total'] if search else len(items)} sản phẩm phù hợp. "
        f"Rẻ nhất là **{cheapest['name']}**, giá {_vnd(int(best['price']))} tại {best['site']}."
    )
    return FinalAnswer(
        text=text,
        product_ids=[int(item["product_id"]) for item in shown],
        follow_up_suggestions=["So sánh 2 sản phẩm rẻ nhất", "Đặt cảnh báo giá"],
    )


class ShoppingFakeChatModel(BaseChatModel):
    """Planner (qua `with_structured_output`) và executor (qua `bind_tools`) dùng chung một lớp."""

    @property
    def _llm_type(self) -> str:
        return "shopping-fake-chat-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ShoppingFakeChatModel":
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        if schema is QueryIntent:
            return RunnableLambda(lambda messages: plan_from_text(_last_human_text(messages)))
        if schema is FinalAnswer:
            return RunnableLambda(lambda messages: answer_from_results(_tool_results(messages)))
        raise NotImplementedError(f"Model giả không hỗ trợ đầu ra {schema!r}")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        results = _tool_results(messages)
        if results:
            call = {
                "name": FinalAnswer.__name__,
                "args": answer_from_results(results).model_dump(),
                "id": "call_final",
            }
        else:
            intent = _intent_from_turn(messages)
            args: dict[str, Any]
            if intent is not None and intent.tier == 2 and intent.keywords:
                args = {
                    "query": " ".join(intent.keywords),
                    "price_min": intent.price_min,
                    "price_max": intent.price_max,
                    "limit_per_site": 5,
                }
                call = {"name": "live_search_other", "args": args, "id": "call_live"}
            elif intent is None or intent.tier != 1 or intent.category is None:
                answer = FinalAnswer(text="Bản demo chỉ tìm laptop, chuột, bàn phím và tai nghe.")
                call = {"name": FinalAnswer.__name__, "args": answer.model_dump(), "id": "f1"}
            else:
                args = {
                    "category": intent.category.value,
                    "price_min": intent.price_min,
                    "price_max": intent.price_max,
                    "brands": intent.brands,
                    "sites": [site.value for site in intent.sites],
                    "spec_filters": [spec.model_dump() for spec in intent.spec_filters],
                    "sort": intent.sort,
                    "limit": intent.limit,
                }
                call = {"name": "search_catalog", "args": args, "id": "call_search"}
        message = AIMessage(content="", tool_calls=[call])
        return ChatResult(generations=[ChatGeneration(message=message)])
