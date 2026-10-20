"""Tên chuẩn và khóa so sánh tên sản phẩm (docs/04 §7).

- `canonical_name`: tên hiển thị sạch của một `Product` (không có tiền tố loại, khối thông số,
  nhãn khuyến mãi, màu, mã phụ tùng); lấy từ offer đầu tiên của mẫu.
- `name_key`: các token đã `fold` dùng để so hai tên khi ghép mẫu. Màu và từ chỉ loại sản phẩm bị
  bỏ (cùng một mẫu khác màu là một `Product`), mọi từ khác kể cả "wireless", "lightspeed",
  "mini", tên switch đều giữ vì chúng phân biệt mẫu.
"""

import re
from dataclasses import dataclass
from typing import Final

from app.domain.enums import Category
from app.normalize.brand import UNKNOWN_BRAND, brand_words
from app.normalize.model_code import laptop_code_span
from app.normalize.specs.parsing import clean
from app.normalize.text import fold

_LEADING_TAGS = re.compile(r"^(?:\s*(?:\[[^\]]*\]|\([^)]*\)))+\s*")
_PAREN = re.compile(r"\(([^()]*)\)")
_EDGE: Final = " \t,;:()[]{}\"'-"
_PART_NUMBER = re.compile(r"^\d{3}-\d{4,6}$")  # mã phụ tùng Logitech: 910-007735

_COLORS: Final = frozenset(
    [
        "black",
        "white",
        "grey",
        "gray",
        "pink",
        "red",
        "blue",
        "green",
        "yellow",
        "purple",
        "orange",
        "silver",
        "magenta",
        "graphite",
        "cream",
        "gold",
        "brown",
        "beige",
        "navy",
        "midnight",
        "dark",
        "light",
        "rose",
        "lilac",
        "mint",
        "violet",
        "teal",
        "den",
        "trang",
        "xam",
        "hong",
        "xanh",
        "vang",
        "tim",
        "bac",
        "nau",
        "cam",
        "kem",
        "than",
        "chi",
        "nhat",
    ]
)
# Từ chỉ loại sản phẩm hoặc quảng cáo: không phân biệt mẫu.
_NOISE: Final = frozenset(
    [
        "chuot",
        "mouse",
        "keyboard",
        "headset",
        "headphone",
        "headphones",
        "laptop",
        "gaming",
        "game",
        "co",
        "new",
        "moi",
        "mau",
        "chinh",
        "hang",
    ]
)
# Tiền tố loại sản phẩm đứng trước tên hãng: bỏ khỏi tên hiển thị.
_PREFIX_WORDS: Final = frozenset(
    [
        "laptop",
        "gaming",
        "game",
        "chuot",
        "mouse",
        "ban",
        "phim",
        "keyboard",
        "tai",
        "nghe",
        "headset",
        "micro",
        "co",
        "khong",
        "day",
        "cong",
        "thai",
        "hoc",
        "true",
        "wireless",
        "bluetooth",
        "silent",
        "mechanical",
    ]
)
_PHRASES: Final = (  # (cụm đã fold, token thay thế); cụm dài đứng trước
    (("khong", "day"), ("wireless",)),
    (("co", "day"), ("wired",)),
    (("cong", "thai", "hoc"), ("ergonomic",)),
    (("ban", "phim"), ()),
    (("tai", "nghe"), ()),
    (("chinh", "hang"), ()),
    (("3", "mode"), ("trimode",)),
    (("triple", "mode"), ("trimode",)),
    (("tri", "mode"), ("trimode",)),
)
# Cách gọi khác của cùng một dòng, theo hãng: "Logitech PRO X3" và "Logitech G Pro X3".
_ALIASES: Final = {"Logitech": ((("g", "pro"), ("pro",)),)}


@dataclass(frozen=True)
class _Token:
    text: str  # nguyên văn (giữ hoa thường để hiển thị)
    key: str  # dạng đã fold


def _unwrap_parentheses(title: str) -> str:
    """Bỏ nhóm ngoặc chỉ chứa màu hoặc mã (`(White/Black)`, `(910-006479)`, `(PMW920)`); nhóm có
    chữ khác (`(Bàn phím chống nước)`) được giữ lại không kèm dấu ngoặc."""

    def replace(match: re.Match[str]) -> str:
        inner = match[1]
        words = [fold(w).strip(_EDGE) for w in re.split(r"[\s/]+", inner) if w.strip(_EDGE)]
        if not words:
            return " "
        if all(word in _COLORS for word in words):
            return " "
        if len(words) == 1 and _is_part_code(words[0]):
            return " "
        return f" {inner} "

    return _PAREN.sub(replace, title)


def _is_part_code(word: str) -> bool:
    if _PART_NUMBER.match(word):
        return True
    return (
        4 <= len(word) <= 14
        and any(c.isdigit() for c in word)
        and any(c.isalpha() for c in word)
        and word.isalnum()
    )


def _tokens(title: str) -> list[_Token]:
    text = _unwrap_parentheses(_LEADING_TAGS.sub("", clean(title)))
    tokens: list[_Token] = []
    for raw in re.split(r"[\s/]+", text):
        stripped = raw.strip(_EDGE)
        key = fold(stripped).strip(_EDGE)
        if key and not _PART_NUMBER.match(key):
            tokens.append(_Token(stripped, key))
    return tokens


def _drop_colors(tokens: list[_Token]) -> list[_Token]:
    """Bỏ màu (và chữ "màu" đứng trước màu). Từ ngay trước "switch" thuộc tên switch nên giữ."""
    kept: list[_Token] = []
    for index, token in enumerate(tokens):
        before_switch = index + 1 < len(tokens) and tokens[index + 1].key == "switch"
        if token.key in _COLORS and not before_switch:
            continue
        kept.append(token)
    return kept


def _leading_prefix_length(tokens: list[_Token]) -> int:
    """Số token đầu là tiền tố loại sản phẩm ("Chuột gaming không dây …")."""
    count = 0
    while count < len(tokens) and tokens[count].key in _PREFIX_WORDS:
        count += 1
    return count


def canonical_name(title: str, category: Category) -> str:
    """Tên hiển thị sạch của sản phẩm.

    Laptop: từ hãng đến hết mã model (`Acer Aspire Lite 15 AL15-53P-56QH`). Nhóm khác: bỏ tiền tố
    loại, màu, mã phụ tùng và nhãn khuyến mãi. Không rỗng: về cuối dùng nguyên tiêu đề đã gọn.
    """
    cleaned = clean(title)
    if category is Category.laptop:
        span = laptop_code_span(cleaned)
        if span is not None:
            return span[0]
    tokens = _tokens(cleaned)
    tokens = tokens[_leading_prefix_length(tokens) :]
    tokens = [t for t in _drop_colors(tokens) if t.key not in {"mau", "chinh", "hang"}]
    name = " ".join(token.text for token in tokens)
    return name or cleaned


def _substitute(
    keys: list[str], rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
) -> list[str]:
    """Thay các cụm token theo `rules` (cụm đầu tiên khớp thắng)."""
    result: list[str] = []
    index = 0
    while index < len(keys):
        for phrase, replacement in rules:
            if tuple(keys[index : index + len(phrase)]) == phrase:
                result.extend(replacement)
                index += len(phrase)
                break
        else:
            result.append(keys[index])
            index += 1
    return result


def name_key(name: str, brand: str) -> tuple[str, ...]:
    """Các token đã `fold` của tên, dùng để so hai sản phẩm cùng hãng.

    Bỏ: tên công ty, từ chỉ loại/quảng cáo, màu. Giữ thứ tự xuất hiện (matcher so như tập hợp).
    """
    tokens = _drop_colors(_tokens(name))
    keys = _substitute([token.key for token in tokens], _PHRASES)
    keys = _substitute(keys, _ALIASES.get(brand, ()))
    company = brand_words(brand) if brand != UNKNOWN_BRAND else frozenset()
    return tuple(key for key in keys if key not in _NOISE and key not in company and key != "")
