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

# Cụm từ cho thấy người dùng YÊU CẦU tool ghi (đã bỏ dấu, chữ thường). Phải là động từ hành động
# đi kèm đích ("vào danh sách", "báo tôi khi…"), không chỉ chứa từ rời: "thêm … vào khoảng 20
# triệu", "tôi đang có cảnh báo nào?" là câu chỉ đọc và không được mở khóa tool ghi.
_ADD_TO_LIST: Final = re.compile(
    r"\bvao (danh sach|wishlist|shopping list)\b"
    r"|\b(them|luu|add)\b[^.?!]{0,40}\b(danh sach|wishlist|shopping list)\b"
)
_ALERT: Final = re.compile(
    r"\b(dat|tao|bat|them|cai|thiet lap|set|create)\b[^.?!]{0,15}\b(canh bao|alert)\b"
    r"|\bbao (toi|minh|em|cho (toi|minh))\b"
    r"|\bnhac (toi|minh|em)\b"
    r"|\bthong bao (cho|khi)\b|\bnotify me\b"
    r"|\b(muon|hay|giup|can)\b[^.?!]{0,15}\btheo doi gia\b"
    r"|\bkhi\b[^.?!]{0,40}\b(xuong|giam|ha)\b[^.?!]{0,30}\b(duoi|thap hon|con)\b"
)
_URL: Final = re.compile(r"https?://[^\s)\]>\"'<]+")
REMOVED_LINK: Final = "[liên kết đã loại]"
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
    dropped_text_urls: tuple[str, ...] = ()

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
    # Id sản phẩm in trong câu ("ID: 118687") trông như số tiền nhưng không phải tiền.
    identifiers = evidence.product_ids | set(answer.product_ids)
    warnings = sorted(
        amount
        for amount in extract_amounts(answer.text)
        if amount not in identifiers and not _near(amount, reference)
    )

    # Link trong văn bản cũng phải có trong kết quả tool (LLM hay viết "[Mua ngay](url bịa)").
    removed_text_urls: list[str] = []

    def vet_link(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:!?")
        if url in evidence.urls or url in evidence.live_urls:
            return match.group(0)
        removed_text_urls.append(url)
        return REMOVED_LINK + match.group(0)[len(url) :]  # giữ dấu câu cuối câu

    text = _URL.sub(vet_link, answer.text)

    cleaned = answer.model_copy(
        update={
            "text": text,
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
        dropped_text_urls=tuple(removed_text_urls),
    )
