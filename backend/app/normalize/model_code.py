"""Trích mã model từ tiêu đề laptop (docs/04 §7).

Không nguồn nào trả mã hãng (MPN) nên mã đọc từ tên: `AL15-53P-56QH`, `FX610JH-TU008W`,
`83DV01MCVN`, HP `D44VLPA`. Phụ kiện không có mã model: mã phụ tùng của hãng (Logitech
`910-007735`…) gắn với từng màu nên không dùng làm khóa gom, phụ kiện ghép bằng tên (`matcher.py`).
"""

import re
from typing import Final

from app.domain.enums import Category
from app.normalize.specs.parsing import clean

MAX_CODE_LENGTH: Final = 40
_MIN_CODE_LENGTH: Final = 5
_MIN_NUMERIC_CODE_LENGTH: Final = 7  # Dell `71100521`: mã chỉ gồm số phải đủ dài

# Phần đầu của tên (trước khối thông số) kết thúc ở "(", " | " hoặc "/" đầu tiên.
_SPEC_BLOCK = re.compile(r"\(|\s\|\s|/")
_EDGE_PUNCT = " \t,;:()[]{}\"'"
_LAPTOP_PREFIX = re.compile(r"^\s*laptop(?:\s+gaming)?\s+", re.IGNORECASE)
# Nhãn khuyến mãi ở đầu tên ("[Giảm 10%/ Tặng chuột] ...", "(Mới) ..."): chứa "(" hoặc "/" nên phải
# bỏ trước khi cắt khối thông số, nếu không phần đầu tên rỗng và mất mã model (BUG-M5-5).
_LEADING_TAGS = re.compile(r"^(?:\s*(?:\[[^\]]*\]|\([^)]*\)))+\s*")

# Token thông số (không phải mã model) dễ lẫn vì có cả chữ lẫn số.
_NOT_A_CODE = re.compile(
    r"^(?:"
    r"i[3579][-\s]?\d{4,5}[a-z]{0,2}"  # CPU Intel: i5-13420H
    r"|\d{4,5}[a-z]{1,2}"  # số hiệu CPU rời: 7730U, 13420H
    r"|r[3579][-\s]?\d{4}[a-z]{0,2}"  # CPU AMD viết tắt: R7-7730U
    r"|(?:rtx|gtx|rx)-?\d{3,4}[a-z]*"  # GPU
    r"|\d-\d{3,5}[a-z]{0,2}"  # CPU viết "Core 5-120U", "Ryzen 5-7535HS"
    r"|x\d[a-z]?-\d+-\d+"  # Snapdragon X1E-78-100
    r"|(?:lp)?ddr\d-\d+"  # DDR5-5600
    r"|\d+(?:\.\d+)?(?:gb|tb|hz|mm|kg|wh|inch|in)"  # dung lượng, tần số, kích thước
    r"|win(?:dows)?\d*"  # hệ điều hành
    r"|ddr\d+x?|lpddr\d+x?|\d+x\d+"  # RAM, độ phân giải
    r"|gen\d+"  # thế hệ: ThinkPad E14 Gen10
    r"|[a-z]{3,}\d{1,2}"  # tên dòng máy dính số: Book4, Yoga7, Zenbook14
    r")$",
    re.IGNORECASE,
)
_STRONG_HYPHENATED = re.compile(r"[a-z0-9]-[a-z0-9]", re.IGNORECASE)
_STRONG_MIN_LENGTH: Final = 7
_STRONG_MIN_DIGITS: Final = 3


def _normalize(code: str) -> str:
    return "".join(code.split()).upper()


def _trim(token: str) -> str:
    return token.strip(_EDGE_PUNCT).rstrip("-.")


def _is_code_like(token: str) -> bool:
    if len(token) < _MIN_CODE_LENGTH or len(token) > MAX_CODE_LENGTH:
        return False
    has_digit = any(char.isdigit() for char in token)
    has_letter = any(char.isalpha() for char in token)
    if not has_digit or _NOT_A_CODE.match(token):
        return False
    return has_letter or len(token) >= _MIN_NUMERIC_CODE_LENGTH


def is_strong_code(code: str) -> bool:
    """Mã đủ đặc trưng để tin là mã hãng của một cấu hình (`AL15-53P-56QH`, `83DV01MCVN`).

    Mã ngắn không gạch (`15IRX9`, `B13VFK`) thường là mã nền tảng chung cho nhiều dòng máy,
    nên khi ghép phải có thêm tên và cấu hình khớp (`matcher.py`).
    """
    if _STRONG_HYPHENATED.search(code):
        return True
    digits = sum(char.isdigit() for char in code)
    return len(code) >= _STRONG_MIN_LENGTH and digits >= _STRONG_MIN_DIGITS


def laptop_head(title: str) -> list[str]:
    """Các token của phần tên laptop trước khối thông số (đã bỏ chữ "Laptop [gaming]")."""
    untagged = _LEADING_TAGS.sub("", clean(title))
    head = _SPEC_BLOCK.split(_LAPTOP_PREFIX.sub("", untagged), maxsplit=1)[0]
    return [token for token in (_trim(raw) for raw in head.split()) if token]


def laptop_code_span(title: str) -> tuple[str, str] | None:
    """(tên đến hết mã model, mã model) của laptop; `None` nếu tiêu đề không có mã.

    Mã là token giống mã cuối cùng của phần đầu tên: HP ghi họ máy rồi mới tới mã
    (`15-fa2452TX D44VLPA`), Lenovo ghi nền tảng rồi mới tới mã (`15IRX9 83DV01MCVN`).
    """
    tokens = laptop_head(title)
    for index in range(len(tokens) - 1, -1, -1):
        if _is_code_like(tokens[index]):
            return " ".join(tokens[: index + 1]), _normalize(tokens[index])
    return None


def hint_code(hint: str | None) -> str | None:
    """Mã từ `ProductDetail.model_code_hint` (chỉ khi có cả chữ và số: số trơn là mã nội bộ)."""
    if hint is None:
        return None
    code = _normalize(hint)
    if not 3 <= len(code) <= MAX_CODE_LENGTH:
        return None
    if any(c.isalpha() for c in code) and any(c.isdigit() for c in code):
        return code
    return None


def extract_model_code(category: Category, title: str, hint: str | None = None) -> str | None:
    """Mã model chuẩn hóa (viết hoa, bỏ khoảng trắng) hoặc `None`.

    Ưu tiên `hint` (MPN của trang, hiện chỉ mock-shop có). Chỉ laptop đọc mã từ tên.
    """
    from_hint = hint_code(hint)
    if from_hint is not None:
        return from_hint
    if category is not Category.laptop:
        return None
    span = laptop_code_span(title)
    return span[1] if span else None
