"""Guardrail chạy bằng code sau executor (docs/05 §5). Toàn bộ là hàm thuần, không gọi LLM.

- Id sản phẩm và link LLM nêu phải có trong kết quả tool của lượt này.
- Số tiền trong văn bản lệch giá trong kết quả tool > 1% thì cảnh báo.
- Tool ghi chỉ chạy khi câu của người dùng yêu cầu rõ ràng.
"""

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from app.agent.intent import MIN_AMOUNT_VND, extract_amounts
from app.agent.schemas import MAX_SUGGESTIONS, FinalAnswer, LiveItem
from app.agent.tools.base import Result, error_result
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
    r"|\b(them|luu|add)\b[^.?!]{0,80}\b(danh sach|wishlist|shopping list)\b"
)
_ALERT: Final = re.compile(
    r"\b(dat|tao|bat|them|cai|thiet lap|set|create)\b[^.?!]{0,15}\b(canh bao|alert)\b"
    r"|\b(bao|nhac) (toi|minh|em|cho (toi|minh))\b[^.?!]{0,40}\b(khi|neu|if|when)\b"
    r"|\bthong bao\b[^.?!]{0,30}\b(khi|neu)\b|\bnotify me\b"
    r"|\b(muon|hay|giup|can)\b[^.?!]{0,15}\btheo doi gia\b"
    r"|\bkhi\b[^.?!]{0,40}\b(xuong|giam|ha)\b[^.?!]{0,30}\b(duoi|thap hon|con)\b"
)
# Từ phủ định đứng ngay trước động từ yêu cầu ("đừng thêm …", "không cần đặt cảnh báo", "khỏi
# thêm", "không nghĩ nên thêm"): cụm đó là lời từ chối, không phải yêu cầu. Chỉ xét trong cùng
# mệnh đề và khi từ phủ định cách động từ tối đa 2 từ, nên "không quá 30 triệu và đặt cảnh báo"
# (phủ định thuộc về giá) không bị chặn nhầm. Gắn với cuối cửa sổ (`$`).
_NEGATION: Final = re.compile(
    r"\b(dung(?! (?:quen|ngai)\b)|khong|ko|chang|khoi|thoi|chua|do not|don'?t|no need|never)"
    r"\b(?: \w+){0,2} ?$"
)
_NEGATION_WINDOW: Final = 40
_CLAUSE_LOOKBACK: Final = 200  # xem lại tối đa ngần này ký tự để tìm động từ của mệnh đề
# Động từ yêu cầu; phủ định được xét ngay trước động từ GẦN NHẤT của mệnh đề, vì cụm khớp có thể
# bắt đầu muộn ("đừng thêm <tên sản phẩm dài> vào danh sách" khớp từ "vào danh sách").
_VERB: Final = re.compile(
    r"\b(them|luu|add|dat|tao|bat|cai|thiet lap|set|create|bao|nhac|thong bao|notify)\b"
)
_SENTENCE_END: Final = ".?!,;"  # dấu ngắt câu/mệnh đề: phủ định ở mệnh đề trước không lan sang sau
# Có cả "www." không scheme (markdown dạng GFM tự biến thành link) và scheme viết hoa.
_URL: Final = re.compile(r"(?:https?://|www\.)[^\s)\]>\"'<]+", re.IGNORECASE)
_URL_TRAILING: Final = ".,;:!?*_~`"  # dấu câu / markdown dính sau link ("**https://…**")
REMOVED_LINK: Final = "[liên kết đã loại]"
ADD_TOOL: Final = "add_to_shopping_list"
ALERT_TOOL: Final = "create_price_alert"


def allowed_write_tools(message: str) -> frozenset[str]:
    """Tool ghi mà câu của người dùng cho phép (rỗng nếu chỉ hỏi/tìm kiếm)."""
    folded = " ".join(fold(message).split())  # gộp khoảng trắng/xuống dòng giữa các từ
    allowed: set[str] = set()
    if _requested(_ADD_TO_LIST, folded):
        allowed.add(ADD_TOOL)
    if _requested(_ALERT, folded):
        allowed.add(ALERT_TOOL)
    return frozenset(allowed)


def _requested(pattern: re.Pattern[str], folded: str) -> bool:
    """Có cụm yêu cầu khớp `pattern` mà không bị từ phủ định đứng ngay trước trong cùng câu."""
    for match in pattern.finditer(folded):
        start = match.start()
        lo = max(0, start - _CLAUSE_LOOKBACK)
        segment = folded[lo:start]
        cut = max(segment.rfind(mark) for mark in _SENTENCE_END)
        lo, segment = lo + cut + 1, segment[cut + 1 :]  # chỉ giữ mệnh đề chứa cụm khớp
        verbs = list(_VERB.finditer(segment))
        # Cụm khớp tự bắt đầu bằng động từ thì phủ định phải đứng ngay trước nó; chỉ khi cụm bắt đầu
        # muộn ("vào danh sách") mới lùi về động từ gần nhất của mệnh đề.
        anchor = lo + verbs[-1].start() if verbs and not _VERB.match(folded, start) else start
        window = folded[max(lo, anchor - _NEGATION_WINDOW) : anchor]
        if not _NEGATION.search(window):
            return True
    return False


def check_write_args(
    tool: str, args: Mapping[str, Any], user_amounts: Collection[int]
) -> Result | None:
    """Lỗi cho LLM thử lại nếu tham số tool ghi sai thang tiền, None nếu hợp lệ.

    `create_price_alert` với `target_price` < 10.000 VND, hoặc bằng số người dùng nêu chia cho
    1.000 / 1.000.000 ("25 triệu" mà LLM gửi 25), sẽ không bao giờ kích hoạt nên bị từ chối.
    """
    if tool != ALERT_TOOL:
        return None
    price = args.get("target_price")
    if isinstance(price, bool) or not isinstance(price, int):
        return None  # sai kiểu: tool tự báo lỗi tham số
    scaled = next((price * f for f in (1_000_000, 1_000) if price * f in user_amounts), None)
    if price < MIN_AMOUNT_VND or scaled is not None:
        hint = f" (người dùng nêu {scaled})" if scaled is not None else ""
        return error_result(
            "INVALID_TARGET_PRICE",
            f"target_price tính bằng VND đầy đủ, ví dụ 25 triệu = 25000000{hint}; "
            "hãy gọi lại với số đúng",
        )
    return None


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
    known = evidence.urls | evidence.live_urls

    def vet_link(match: re.Match[str]) -> str:
        raw = match.group(0)
        if raw in known:  # link hợp lệ có thể tự kết thúc bằng "_" hoặc "."
            return raw
        url = raw.rstrip(_URL_TRAILING)
        if url in known:
            return raw
        removed_text_urls.append(url)
        return REMOVED_LINK + match.group(0)[len(url) :]  # giữ dấu câu cuối câu

    # NUL làm PostgreSQL từ chối lưu tin nhắn/sự kiện (lượt kẹt ở `running`): bỏ khỏi văn bản.
    text = _URL.sub(vet_link, answer.text.replace(chr(0), ""))

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
