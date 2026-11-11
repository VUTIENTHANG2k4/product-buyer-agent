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
from app.agent.tools.search_catalog import KEYWORD_SPECS
from app.domain.dto import QueryIntent
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
# Cụm từ cho thấy người dùng HỎI so sánh / chi tiết / diễn biến giá (đã bỏ dấu). Không khớp thì
# executor không đưa ba tool đó cho LLM (X1.10: Gemini gọi thêm chúng ở ~70% lượt P01 dù kết quả
# tìm đã đủ, p50 30 s thay vì 15 s; dặn trong prompt không đổi gì).
# Tham chiếu một mục của kết quả trước ("cái thứ 3", "máy đầu tiên"). "con" chỉ đi với thứ tự rõ
# ràng vì "còn đâu", "còn đó" bỏ dấu cũng thành "con dau", "con do" (review X1.10).
_REFERENCE: Final = (
    r"\b(cai|may|chiec|san pham|sp)\b ?(thu \d+|thu (nhat|hai|ba|tu|nam)|so \d+"
    r"|dau( tien)?|cuoi( cung)?|do|nay|kia)\b"
    r"|\bcon (thu \d+|thu (nhat|hai|ba|tu|nam)|so \d+|dau tien|cuoi cung|nay|kia)\b"
)
_COMPARE: Final = re.compile(
    r"\bso (sanh|voi)\b|\bkhac (nhau|gi|biet)\b|\bvs\b|\bversus\b|\bcompare\b"
    r"|\b(nen|chon|lay|mua) (cai|may|con|chiec) nao\b"
    r"|\b(cai|may|con|chiec) nao\b[^.?!]{0,30}\b(tot|hon|ngon)\b"
    r"|\bhay\b[^.?!]{0,40}\b(tot hon|ngon hon|dang mua hon|hon)\b"
    r"|\bhon (cai|may|con|chiec)\b|\bdiem (manh|yeu)\b|\buu nhuoc\b"
    r"|\bwhich (one )?(is )?(better|best)\b|\bbetter than\b"
)
# "cấu hình" / "thông số" đứng một mình là cách nói tìm kiếm ("laptop cấu hình mạnh"): chỉ mở
# chi tiết khi đi kèm từ hỏi hoặc tham chiếu.
_DETAIL: Final = re.compile(
    r"\bchi tiet\b|\bspecs?\b|\bdetails?\b|\bbao hanh\b|\bmo ta\b|\bxem (them|ky)\b"
    r"|\b(cau hinh|thong so)\b[^.?!]{0,30}\b(the nao|ra sao|gi|nao|day du)\b"
    r"|\b(xem|cho xem|cho biet)\b[^.?!]{0,10}\b(cau hinh|thong so)\b"
    r"|\bco (may|bao nhieu)\b|\b(shop|trang|cho|noi) nao\b|" + _REFERENCE
)
# "tặng" bỏ dấu thành "tang": chỉ coi là diễn biến giá khi tăng/giảm đứng sát chữ "giá".
_HISTORY: Final = re.compile(
    r"\blich su gia\b|\bprice history\b|\bbien dong\b"
    r"|\b(tang|giam|ha|len|xuong) gia\b|\bgia (co |da |se |dang |vua )?(tang|giam|ha|len|xuong)\b"
    r"|\bgia\b[^.?!]{0,30}\b(dao nay|gan day|thay doi|the nao|ra sao|truoc (day|kia)"
    r"|len xuong|con on|on dinh)\b"
)
READ_ON_REQUEST_TOOLS: Final = frozenset(
    {"compare_products", "get_product_detail", "get_price_history"}
)
# Từ phủ định đứng ngay trước động từ yêu cầu ("đừng thêm …", "không cần đặt cảnh báo", "khỏi
# thêm", "không nghĩ nên thêm"): cụm đó là lời từ chối, không phải yêu cầu. Chỉ xét trong cùng
# mệnh đề và khi từ phủ định cách động từ tối đa 2 từ, nên "không quá 30 triệu và đặt cảnh báo"
# (phủ định thuộc về giá) không bị chặn nhầm. Gắn với cuối cửa sổ (`$`).
_NEGATION: Final = re.compile(
    r"\b(dung(?! (?:quen|ngai)\b)|khong|ko|chang|khoi|thoi|chua|sao(?: \w+){0,2} phai|do not"
    r"|don'?t|no need|never|why(?: (?:should|would|do|did) (?:i|we))?)\b(?: \w+){0,2} ?$"
)
# Câu hỏi tu từ ngay sau cụm yêu cầu ("tôi thêm vào danh sách làm gì", "đặt cảnh báo để làm gì")
# là lời từ chối. Chỉ xét liền sau cụm: "thêm vào danh sách rồi làm gì tiếp" vẫn là yêu cầu.
_RHETORICAL: Final = re.compile(r"\s*(?:de )?lam (?:gi|chi)\b")
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


def allowed_read_tools(message: str) -> frozenset[str]:
    """Tool trong `READ_ON_REQUEST_TOOLS` mà câu của người dùng hỏi tới (rỗng nếu chỉ tìm kiếm).

    Câu tham chiếu kết quả trước ("cái thứ 3", "máy đầu tiên") mở cả ba, vì câu kiểu "cái đầu
    tiên giá dạo này thế nào" có thể cần chi tiết lẫn lịch sử giá.
    """
    folded = " ".join(fold(message).split())
    allowed: set[str] = set()
    if _requested(_COMPARE, folded):
        allowed.add("compare_products")
    if _requested(_DETAIL, folded):
        allowed.add("get_product_detail")
    if _requested(_HISTORY, folded):
        allowed.add("get_price_history")
    if re.search(_REFERENCE, folded):
        allowed |= READ_ON_REQUEST_TOOLS
    return frozenset(allowed)


def _requested(pattern: re.Pattern[str], folded: str) -> bool:
    """Có cụm yêu cầu khớp `pattern` mà không bị từ phủ định đứng ngay trước trong cùng câu."""
    for match in pattern.finditer(folded):
        if _RHETORICAL.match(folded, match.end()):
            continue
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


# Tên nhóm hàng (đã bỏ dấu): không phải từ khóa lọc tên ("tai nghe" không có trong "HyperX
# Cloud II"), nhóm đã nằm ở `category`.
_CATEGORY_WORDS: Final = frozenset(
    {
        "laptop",
        "may tinh",
        "may tinh xach tay",
        "chuot",
        "mouse",
        "ban phim",
        "phim",
        "keyboard",
        "tai nghe",
        "headset",
        "headphone",
        "dien thoai",
        "smartphone",
        "phone",
    }
)
_BRAND_SPEC_FIELDS: Final = frozenset({"brand", "brands"})
# Trường cùng ý: ý định có `gpu_rank` mà LLM lọc theo `gpu_model` ("RTX 4060") vẫn là điều kiện
# của người dùng (review X1.10).
_SAME_MEANING_FIELDS: Final[Mapping[str, frozenset[str]]] = {
    "gpu_rank": frozenset({"gpu_model"}),
    "gpu_model": frozenset({"gpu_rank"}),
}


def _brand_key(name: object) -> str:
    """Tên hãng chỉ còn chữ và số, không dấu: "E-Dra", "Edra", "E Dra" là một."""
    return re.sub(r"[^a-z0-9]", "", fold(str(name)))


def _values_mentioned(value: object, folded_message: str) -> bool:
    """Giá trị chuỗi (hoặc danh sách chuỗi) của điều kiện đều có trong câu người dùng."""
    values = value if isinstance(value, list) else [value]
    texts = [" ".join(fold(item).split()) for item in values if isinstance(item, str)]
    return len(texts) == len(values) > 0 and all(_mentioned(t, folded_message) for t in texts)


def _mentioned(word: str, folded_message: str) -> bool:
    """`word` (đã bỏ dấu) xuất hiện trọn từ trong câu đã bỏ dấu."""
    return bool(word) and re.search(rf"(?<!\w){re.escape(word)}(?!\w)", folded_message) is not None


def ground_search_args(
    args: Mapping[str, Any], intent: QueryIntent, message: str
) -> tuple[dict[str, Any], list[str]]:
    """Bỏ điều kiện `search_catalog` mà người dùng không nêu; trả (tham số mới, điều kiện đã bỏ).

    Hãng/từ khóa được giữ khi có trong ý định của planner hoặc trong câu của người dùng; điều kiện
    thông số được giữ khi trường của nó (hoặc trường cùng ý, hoặc trường mà từ khóa của ý định đổi
    thành như "gaming" → `is_gaming`) có trong ý định, giá trị được đổi để nới lỏng; hoặc khi giá
    trị chuỗi của nó có trong câu (planner bỏ sót "RTX 4060"). Hội thoại
    50 (X1.10): Gemini tự thêm `has_mic=true` rồi danh sách HyperX/Razer/JBL… cho "tai nghe
    gaming". Tham số sai kiểu được để nguyên cho tool báo `VALIDATION_ERROR`.
    """
    folded = " ".join(fold(message).split())
    folded_compact = re.sub(r"[^a-z0-9]", "", folded)
    intent_brands = {_brand_key(brand) for brand in intent.brands}
    intent_words = {" ".join(fold(word).split()) for word in intent.keywords}
    intent_fields = {spec.field.lower() for spec in intent.spec_filters}
    intent_fields |= {
        same for field in tuple(intent_fields) for same in _SAME_MEANING_FIELDS.get(field, ())
    }
    if intent.category is not None:
        intent_fields |= {
            spec.field
            for (category, word), spec in KEYWORD_SPECS.items()
            if category == intent.category and word in intent_words
        }
    grounded = dict(args)
    dropped: list[str] = []

    def brand_ok(name: object) -> bool:
        key = _brand_key(name)
        # Dạng chỉ chữ-số ("edra" trong "tai nghe e dra") chỉ dùng cho tên từ 4 ký tự: "hp", "lg"
        # dễ khớp nhầm khi nối liền các từ.
        return bool(key) and (
            key in intent_brands
            or _mentioned(fold(str(name)), folded)
            or (len(key) >= 4 and key in folded_compact)
        )

    brands = args.get("brands")
    if isinstance(brands, list):
        kept_brands = [brand for brand in brands if brand_ok(brand)]
        dropped += [f"hãng {brand}" for brand in brands if not brand_ok(brand)]
        grounded["brands"] = kept_brands

    specs = args.get("spec_filters")
    if isinstance(specs, list):
        kept_specs: list[Any] = []
        for spec in specs:
            field_name = spec.get("field") if isinstance(spec, dict) else None
            if not isinstance(field_name, str):
                kept_specs.append(spec)
                continue
            key = field_name.lower()
            if key in _BRAND_SPEC_FIELDS:  # hãng đặt nhầm chỗ (X1.8): xét như `brands`
                values = spec.get("value")
                names = values if isinstance(values, list) else [values]
                if all(brand_ok(name) for name in names):
                    kept_specs.append(spec)
                else:
                    dropped.append(f"hãng {', '.join(str(name) for name in names)}")
            elif key in intent_fields or _values_mentioned(spec.get("value"), folded):
                kept_specs.append(spec)
            else:
                dropped.append(f"{field_name} {spec.get('op', '')} {spec.get('value', '')}".strip())
        grounded["spec_filters"] = kept_specs

    words = args.get("keywords")
    if isinstance(words, list):
        kept_words: list[Any] = []
        for word in words:
            key = " ".join(fold(str(word)).split())
            useful = key not in _CATEGORY_WORDS and _brand_key(key) not in intent_brands
            if useful and (key in intent_words or _mentioned(key, folded)):
                kept_words.append(word)
            else:
                dropped.append(f"từ khóa {word}")
        grounded["keywords"] = kept_words
    return grounded, dropped


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
    live_entries: dict[str, dict[str, Any]] = field(default_factory=dict)  # url -> mục gốc của tool
    prices: set[int] = field(default_factory=set)
    data_as_of: set[str] = field(default_factory=set)

    def add_result(self, tool: str, result: Mapping[str, Any]) -> None:
        """Gom id, link, giá từ một kết quả tool thành công (duyệt đệ quy)."""
        if result.get("ok") is False:
            return
        self._walk(result, tool)
        if tool == LIVE_TOOL:
            for entry in result.get("items") or []:
                if isinstance(entry, Mapping) and isinstance(entry.get("url"), str):
                    self.live_entries.setdefault(entry["url"], dict(entry))

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
    shown_live: set[str] = set()
    for item in answer.live_items:
        source = evidence.live_entries.get(item.url)
        if source is None:
            dropped_urls.append(item.url)
        elif item.url not in shown_live:
            # Chỉ URL do LLM chọn; tên, giá, trang, thời điểm lấy lại từ kết quả tool (bảng không
            # được dựng từ chữ LLM viết).
            shown_live.add(item.url)
            kept_live.append(
                LiveItem(
                    site=str(source.get("site", item.site)),
                    title=str(source.get("title", item.title)),
                    price=source.get("price"),
                    url=item.url,
                    scraped_at=source.get("scraped_at"),
                )
            )

    reference = [*evidence.prices, *user_amounts]
    # Id sản phẩm in trong câu ("ID: 118687") trông như số tiền nhưng không phải tiền.
    identifiers = evidence.product_ids | set(answer.product_ids)
    warnings = sorted(
        amount
        for amount in extract_amounts(answer.text, skip_estimates=True)
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
