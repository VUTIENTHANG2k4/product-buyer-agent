"""Guardrail chạy bằng code sau executor (docs/05 §5). Toàn bộ là hàm thuần, không gọi LLM.

- Id sản phẩm và link LLM nêu phải có trong kết quả tool của lượt này.
- Số tiền trong văn bản lệch giá trong kết quả tool > 1% thì cảnh báo.
- Tool ghi chỉ chạy khi câu của người dùng yêu cầu rõ ràng.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from app.agent.intent import extract_amounts
from app.agent.schemas import MAX_SUGGESTIONS, FinalAnswer, LiveItem
from app.normalize.text import fold

PRICE_TOLERANCE: Final = 0.01
_ID_KEYS: Final = frozenset({"product_id", "cheapest_product_id"})
_PRICE_KEYS: Final = frozenset(
    {
        "min_price",
        "max_price",
        "price",
        "list_price",
        "current_price",
        "price_at_add",
        "current_best_price",
        "target_price",
    }
)
LIVE_TOOL: Final = "live_search_other"

# Từ khóa cho thấy người dùng yêu cầu tool ghi (đã bỏ dấu, chữ thường).
_ADD_TO_LIST: Final = re.compile(
    r"\b(them|luu|add)\b.*\b(vao|into|to)\b|\bdanh sach (mua|cua toi)\b|\bwishlist\b"
)
_ALERT: Final = re.compile(
    r"\bbao (toi|minh|em|cho)\b|\bnhac\b|\bthong bao\b|\bcanh bao\b|\balert\b|\bnotify\b"
    r"|\btheo doi gia\b|\bkhi\b.*\b(xuong|giam|ha)\b"
)
ADD_TOOL: Final = "add_to_shopping_list"
ALERT_TOOL: Final = "create_price_alert"


def allowed_write_tools(message: str) -> frozenset[str]:
    """Tool ghi mà câu của người dùng cho phép (rỗng nếu chỉ hỏi/tìm kiếm)."""
    folded = fold(message)
    allowed: set[str] = set()
    if _ADD_TO_LIST.search(folded):
        allowed.add(ADD_TOOL)
    if _ALERT.search(folded):
        allowed.add(ALERT_TOOL)
    return frozenset(allowed)


@dataclass
class Evidence:
    """Những gì kết quả tool của lượt này đã cho thấy: id, link, giá."""

    product_ids: set[int] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    live_urls: set[str] = field(default_factory=set)
    prices: set[int] = field(default_factory=set)
    data_as_of: set[str] = field(default_factory=set)

    def add_result(self, tool: str, result: Mapping[str, Any]) -> None:
        """Gom id, link, giá từ một kết quả tool thành công (duyệt đệ quy)."""
        if result.get("ok") is False:
            return
        self._walk(result, tool)

    def _walk(self, node: Any, tool: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if isinstance(value, bool):
                    continue
                if key in _ID_KEYS and isinstance(value, int):
                    self.product_ids.add(value)
                elif key == "url" and isinstance(value, str):
                    self.urls.add(value)
                    if tool == LIVE_TOOL:
                        self.live_urls.add(value)
                elif key in _PRICE_KEYS and isinstance(value, int):
                    self.prices.add(value)
                else:
                    self._walk(value, tool)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, tool)


@dataclass(frozen=True)
class GuardrailOutcome:
    answer: FinalAnswer
    dropped_product_ids: tuple[int, ...]
    dropped_live_urls: tuple[str, ...]
    price_warnings: tuple[int, ...]

    @property
    def hallucinated(self) -> bool:
        """LLM nêu sản phẩm nhưng không id nào có trong kết quả tool."""
        return bool(self.dropped_product_ids) and not self.answer.product_ids


def _near(amount: int, known: Iterable[int]) -> bool:
    return any(abs(amount - value) <= value * PRICE_TOLERANCE for value in known if value > 0)


def apply_guardrail(
    answer: FinalAnswer, evidence: Evidence, *, user_amounts: Iterable[int] = ()
) -> GuardrailOutcome:
    """Loại id/link không có trong kết quả tool, cắt gợi ý, ghi nhận số tiền lệch.

    `user_amounts` là số tiền người dùng tự nêu (ví dụ ngưỡng "dưới 30 triệu") nên không bị coi là
    lệch dù không phải giá trong CSDL.
    """
    seen: set[int] = set()
    kept_ids: list[int] = []
    dropped_ids: list[int] = []
    for product_id in answer.product_ids:
        if product_id in seen:
            continue
        seen.add(product_id)
        (kept_ids if product_id in evidence.product_ids else dropped_ids).append(product_id)

    kept_live: list[LiveItem] = []
    dropped_urls: list[str] = []
    for item in answer.live_items:
        if item.url in evidence.live_urls:
            kept_live.append(item)
        else:
            dropped_urls.append(item.url)

    reference = [*evidence.prices, *user_amounts]
    warnings = sorted(
        amount for amount in extract_amounts(answer.text) if not _near(amount, reference)
    )

    cleaned = answer.model_copy(
        update={
            "product_ids": kept_ids,
            "live_items": kept_live,
            "follow_up_suggestions": [s.strip() for s in answer.follow_up_suggestions if s.strip()][
                :MAX_SUGGESTIONS
            ],
        }
    )
    return GuardrailOutcome(
        answer=cleaned,
        dropped_product_ids=tuple(dropped_ids),
        dropped_live_urls=tuple(dropped_urls),
        price_warnings=tuple(warnings),
    )
