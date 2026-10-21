"""Hậu xử lý `QueryIntent` do planner sinh ra (docs/05 §4). Toàn bộ là hàm thuần.

LLM hay sai ở những chỗ có luật rõ ràng (đơn vị tiền, "tầm", "RTX 4060 trở lên", RAM "đúng" hay
"từ"), nên code sửa lại các lỗi đó thay vì tin hoàn toàn vào prompt. Hàm không bịa điều kiện mới
ngoài những gì người dùng nói rõ trong câu hỏi.
"""

import re
from typing import Any, Final

from app.domain.dto import QueryIntent, SpecFilter
from app.domain.enums import Category, SiteKey
from app.normalize.specs.gpu_rank import GPU_RANKS, normalize_gpu_name
from app.normalize.text import fold

MIN_AMOUNT_VND: Final = 10_000  # nhỏ hơn mức này là số đo khác (GB, Hz, inch), không phải giá
MAX_AMOUNT_VND: Final = 10**12  # lớn hơn là rác (cùng trần với tool `create_price_alert`)
_MAX_AMOUNT_DIGITS: Final = (
    15  # số chữ số tối đa đem đổi sang số (chặn OverflowError, giới hạn 4300)
)

TIER1_CATEGORIES: Final = frozenset(
    {Category.laptop, Category.mouse, Category.keyboard, Category.headset}
)
# Trang có dữ liệu để tìm ở tầng 1. Trang còn lại (ví dụ viettelstore) chưa có dữ liệu thu thập.
SEARCHABLE_SITES: Final = frozenset(
    {SiteKey.gearvn, SiteKey.fptshop, SiteKey.anphat, SiteKey.mockshop}
)
UNSUPPORTED_SITE_WORDS: Final = {
    "shopee": "Shopee",
    "tiki": "Tiki",
    "lazada": "Lazada",
    "thegioididong": "Thế Giới Di Động",
    "tgdd": "Thế Giới Di Động",
    "cellphones": "CellphoneS",
    "hacom": "HACOM",
    "phong vu": "Phong Vũ",
}
DEFAULT_CLARIFICATION: Final = (
    "Bạn muốn tìm loại sản phẩm nào (laptop, chuột, bàn phím, tai nghe…)?"
)
MAX_PLAN_STEPS: Final = 5

_UNIT_FACTOR: Final = {
    "trieu": 1_000_000,
    "tr": 1_000_000,
    "m": 1_000_000,
    "cu": 1_000_000,
    "k": 1_000,
    "nghin": 1_000,
    "ngan": 1_000,
}
_AMOUNT = re.compile(
    r"(?<![\w.,])(?P<num>(?>\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?))"
    r"\s*(?P<unit>trieu|tr|m|cu|k|nghin|ngan)?(?:(?<=[a-z])(?P<tail>\d)(?!\d))?"
    r"(?P<cur>\s*(?:vnd|dong|d))?(?![\w])"
)
# Khoảng "20-30 triệu"; không khớp mã model như "i7-13700H" (chữ đứng ngay trước chữ số đầu).
_RANGE = re.compile(r"(?<![a-z\d.])\d+\s*(?:trieu|tr|m|k)?\s*(?:den|toi|->|-|~)\s*\d")
# Số trần không đơn vị cần ít nhất 7 chữ số hoặc hậu tố đ/vnd mới là tiền: "i5-12450", "25600 dpi",
# "ID 118687" không phải giá.
_MIN_PLAIN_DIGITS = 7
_GROUPED = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_MEASURE = re.compile(r"\s*(?:dpi|hz|mah|rpm|gb|tb|mb|ghz|mhz|nits?|inch|mm|cm)\b")
_APPROX_WORDS = re.compile(r"\b(tam|khoang|xap xi|around|about)\b")
_EXACT_WORDS = re.compile(r"\b(dung|chinh xac|exactly|exact)\b")
_CHEAPEST_WORDS = re.compile(r"\b(re nhat|gia thap nhat|cheapest|lowest price)\b")
# Thông số kiểu "từ X trở lên" mặc định: người dùng nói "RAM 16GB" nghĩa là ít nhất 16GB.
_AT_LEAST_FIELDS: Final = frozenset({"ram_gb", "storage_gb", "refresh_hz", "gpu_rank"})
_GPU_FIELDS: Final = frozenset({"gpu", "gpu_model", "gpu_name", "card", "vga"})


def extract_amounts(message: str) -> set[int]:
    """Các số tiền (VND) người dùng viết trong câu: "30 triệu", "30tr", "1,5tr", "2tr5", "500k",
    "30.000.000". Số nhỏ hơn 10.000 (RAM, Hz, inch…) không được coi là tiền."""
    found: set[int] = set()
    folded = fold(message)
    for match in _AMOUNT.finditer(folded):
        raw, unit = match.group("num"), match.group("unit")
        if len(re.sub(r"[.,]", "", raw)) > _MAX_AMOUNT_DIGITS:
            continue  # số quá lớn không phải giá (và int()/float() có thể ném lỗi)
        if _MEASURE.match(folded, match.end()):
            continue  # "16.000 dpi", "26k dpi", "5000 mah": đơn vị đo, không phải tiền
        if unit is None:
            if _GROUPED.fullmatch(raw):
                value = int(re.sub(r"[.,]", "", raw))
            elif raw.isdigit() and (len(raw) >= _MIN_PLAIN_DIGITS or match.group("cur")):
                value = int(raw)
            else:
                continue
        else:
            number = raw if not _GROUPED.fullmatch(raw) else re.sub(r"[.,]", "", raw)
            tail = match.group("tail")
            text = number.replace(",", ".") + (
                "" if tail is None else f"{'.' if '.' not in number else ''}{tail}"
            )
            try:
                value = round(float(text) * _UNIT_FACTOR[unit])
            except ValueError:  # pragma: no cover - regex chỉ cho chuỗi số hợp lệ
                continue
        if MIN_AMOUNT_VND <= value <= MAX_AMOUNT_VND:
            found.add(value)
    return found


def _fix_money_scale(value: int | None, amounts: set[int]) -> int | None:
    """Giá LLM viết sai đơn vị ("30" thay vì 30.000.000) được đối chiếu với số tiền trong câu."""
    if value is None or value == 0 or value in amounts or not amounts:
        return value
    for factor in (1_000_000, 1_000):
        if value * factor in amounts:
            return value * factor
    return value


def _gpu_filter_from_name(name: str) -> SpecFilter | None:
    canonical = normalize_gpu_name(name)
    rank = GPU_RANKS.get(canonical) if canonical else None
    return None if rank is None else SpecFilter(field="gpu_rank", op="gte", value=rank)


def _fix_spec_filters(filters: list[SpecFilter], folded_message: str) -> list[SpecFilter]:
    exact = _EXACT_WORDS.search(folded_message) is not None
    fixed: list[SpecFilter] = []
    for spec in filters:
        if spec.field in _GPU_FIELDS or (spec.field == "gpu_rank" and isinstance(spec.value, str)):
            mapped = _gpu_filter_from_name(str(spec.value))
            if mapped is not None:
                fixed.append(mapped)
            continue  # GPU không có hạng: bỏ điều kiện thay vì lọc sai
        value: Any = spec.value
        op = spec.op
        if spec.field in _AT_LEAST_FIELDS and op == "eq" and not exact:
            op = "gte"
        if (
            spec.field == "storage_gb"
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= 16
            and re.search(r"\d\s*tb\b", folded_message)
        ):
            value *= 1000  # "SSD 1TB" → 1000 GB
        fixed.append(SpecFilter(field=spec.field, op=op, value=value))
    return fixed


def _gpu_filter_from_message(message: str) -> SpecFilter | None:
    """ "RTX 4060" trong câu hỏi → `gpu_rank >= hạng(RTX 4060)` khi LLM quên."""
    return _gpu_filter_from_name(message)


def default_plan_steps(intent: QueryIntent) -> list[str]:
    """Các bước kế hoạch mặc định (tiếng Việt) khi LLM không đưa ra bước nào."""
    names = {
        Category.laptop: "laptop",
        Category.mouse: "chuột",
        Category.keyboard: "bàn phím",
        Category.headset: "tai nghe",
    }
    target = names.get(intent.category, "sản phẩm") if intent.category else "sản phẩm"
    if intent.tier == 2:
        return [f"Tìm trực tiếp {target} ở các trang bán lẻ hỗ trợ tìm kiếm"]
    steps = [f"Tìm {target} trong danh mục đã thu thập"]
    conditions: list[str] = []
    if intent.price_max is not None:
        conditions.append(f"giá dưới {intent.price_max:,}".replace(",", ".") + " ₫")
    if intent.price_min is not None:
        conditions.append(f"giá từ {intent.price_min:,}".replace(",", ".") + " ₫")
    if intent.spec_filters:
        conditions.append("thỏa các điều kiện cấu hình")
    if conditions:
        steps.append("Lọc theo " + ", ".join(conditions))
    steps.append("So sánh giá giữa các trang và trình bày bảng kết quả")
    return steps


def postprocess_intent(intent: QueryIntent, message: str) -> QueryIntent:
    """Sửa các lỗi thường gặp của LLM bằng quy tắc cố định (docs/05 §4); trả `QueryIntent` mới."""
    folded = fold(message)
    amounts = extract_amounts(message)
    data = intent.model_dump()

    # Tầng và nhóm phải nhất quán: nhóm ngoài 4 nhóm lõi là tầng 2 với category "other".
    category = intent.category
    if intent.tier == 2 or (category is not None and category not in TIER1_CATEGORIES):
        data["tier"] = 2
        data["category"] = Category.other
        category = Category.other
    elif category is not None:
        data["tier"] = 1

    # Tiền: đúng đơn vị, rồi "tầm X" → ±10% khi người dùng chỉ nêu một số tiền.
    price_min = _fix_money_scale(intent.price_min, amounts)
    price_max = _fix_money_scale(intent.price_max, amounts)
    if (
        _APPROX_WORDS.search(folded)
        and not _RANGE.search(folded)
        and len(amounts) == 1
        and (price_min, price_max)
        in {(None, None), (None, next(iter(amounts))), (next(iter(amounts)), None)}
    ):
        center = next(iter(amounts))
        price_min, price_max = center * 9 // 10, center * 11 // 10
    if price_min is not None and price_max is not None and price_min > price_max:
        price_min, price_max = price_max, price_min
    data["price_min"], data["price_max"] = price_min, price_max

    # Thông số: GPU → hạng, RAM/ổ cứng "từ X", đổi TB sang GB.
    filters = _fix_spec_filters(list(intent.spec_filters), folded)
    if (
        category is Category.laptop
        and not any(spec.field == "gpu_rank" for spec in filters)
        and (from_message := _gpu_filter_from_message(message)) is not None
    ):
        filters.append(from_message)
    data["spec_filters"] = filters

    # Trang: chỉ giữ trang có dữ liệu; trang người dùng nhắc mà chưa hỗ trợ → thêm bước giải thích.
    data["sites"] = [site for site in intent.sites if site in SEARCHABLE_SITES]
    steps = list(intent.plan_steps)
    unsupported = sorted(
        {label for word, label in UNSUPPORTED_SITE_WORDS.items() if word in folded}
    )
    if unsupported:
        listed = ", ".join(unsupported)
        note = f"Chưa hỗ trợ {listed}: tìm trên các nguồn hiện có (GearVN, FPT Shop, An Phát)"
        if not any(label.lower() in step.lower() for step in steps for label in unsupported):
            steps.append(note)

    if intent.sort == "relevance" and _CHEAPEST_WORDS.search(folded):
        data["sort"] = "price_asc"

    # Hỏi lại: có cờ thì phải có câu hỏi; không có cờ thì bỏ câu hỏi thừa.
    if intent.needs_clarification:
        data["clarification_question"] = (
            intent.clarification_question or ""
        ).strip() or DEFAULT_CLARIFICATION
    else:
        data["clarification_question"] = None
        if not steps:
            steps = default_plan_steps(QueryIntent.model_validate({**data, "plan_steps": []}))

    data["plan_steps"] = [step.strip() for step in steps if step.strip()][:MAX_PLAN_STEPS]
    return QueryIntent.model_validate(data)
