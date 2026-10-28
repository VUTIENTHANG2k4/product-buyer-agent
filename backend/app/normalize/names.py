"""Tên chuẩn và khóa so sánh tên sản phẩm (docs/04 §7).

- `canonical_name`: tên hiển thị sạch của một `Product` (không có tiền tố loại, khối thông số,
  nhãn khuyến mãi, màu, mã phụ tùng); lấy từ offer đầu tiên của mẫu.
- `name_key`: các token đã `fold` dùng để so hai tên khi ghép mẫu. Màu và từ chỉ loại sản phẩm bị
  bỏ (cùng một mẫu khác màu là một `Product`), mọi từ khác kể cả "wireless", "lightspeed",
  "mini", tên switch đều giữ vì chúng phân biệt mẫu.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from app.domain.enums import Category
from app.normalize.brand import UNKNOWN_BRAND, brand_words, find_brand, strip_leading_decoration
from app.normalize.model_code import laptop_code_span
from app.normalize.specs.parsing import clean
from app.normalize.text import fold

_PAREN = re.compile(r"\(([^()]*)\)")
_EDGE: Final = " \t,;:()[]{}\"'-"
_PART_NUMBER = re.compile(r"^\d{3}-\d{4,6}$")  # mã phụ tùng Logitech: 910-007735
# Mã phụ tùng/cảm biến đặt trong ngoặc ("(PMW920)") dài từ 6 ký tự; tên mẫu ngắn trong ngoặc như
# "(G304)", "(M331)", "(Gen2)" phân biệt sản phẩm nên được giữ (BUG-M5-3).
_MIN_PART_CODE_LENGTH: Final = 6
_MAX_PART_CODE_GROUPS: Final = 3  # PMW920 (2 cụm), HERO25K (3); WH1000XM5 (4) là tên mẫu
# Nhóm ngoặc chỉ chứa nhãn bán hàng ("[Hot]", "(Mới 100%)", "(Bảo hành 24 tháng)", "(Fullbox)").
_BRACKET_GROUP = re.compile(r"\s*[\[(]([^\[\]()]*)[\])]")
_MARKETING_LABEL = re.compile(
    r"^(?:moi(?: 100%)?|new(?: 100%| seal)?|hot|sale|gia tot|fullbox|nhap khau|chinh hang"
    r"|bao hanh.*)$"
)
# "Mới 100%" (tình trạng máy) khác "100%" (bố cục phím full-size): chỉ bỏ khi đứng sau mới/new.
_NEW_CONDITION: Final = frozenset(["moi", "new"])

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
        "do",  # đỏ
        "luc",  # lục
        "bac",
        "nau",
        "cam",
        "kem",
        "than",
        "chi",
        "nhat",
    ]
)
# Màu đứng ngay sau / ngay trước các từ này là tên switch bàn phím chứ không phải màu vỏ.
_SWITCH_BEFORE: Final = frozenset(
    [
        "mx",
        "gateron",
        "cherry",
        "kailh",
        "outemu",
        "jwk",
        "switch",
        "sw",
        "optical",
        "box",
        "jelly",
        "ink",
        "milky",
        "crystal",
        "silent",
    ]
)
# Tên/màu switch đứng ngay trước chữ "switch": sau đó là màu vỏ chứ không còn là tên switch.
_SWITCH_NAME_WORDS: Final = (_SWITCH_BEFORE - {"switch", "sw"}) | _COLORS
_SWITCH_AFTER: Final = frozenset(["switch", "sw", "axis"])
_AFTER_BLUE: Final = frozenset(["duong", "la", "ngoc", "nuoc"])  # xanh dương/lá/ngọc/nước biển
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
    # Mã phụ tùng/cảm biến có tối đa 3 cụm chữ/số ("PMW920", "HERO25K"); tên mẫu viết liền
    # xen kẽ nhiều cụm ("WH1000XM5") phân biệt sản phẩm nên được giữ (BUG-S1-6).
    return (
        _MIN_PART_CODE_LENGTH <= len(word) <= 14
        and word.isalnum()
        and any(c.isdigit() for c in word)
        and any(c.isalpha() for c in word)
        and len(re.findall(r"[^\W\d_]+|\d+", word)) <= _MAX_PART_CODE_GROUPS
    )


def _strip_marketing(text: str) -> str:
    """Bỏ phần sau " | " (tên cửa hàng: "… | GearVN") và các nhóm ngoặc chỉ chứa nhãn bán hàng."""

    def replace(match: re.Match[str]) -> str:
        return " " if _MARKETING_LABEL.match(fold(match[1]).strip(_EDGE)) else match[0]

    return _BRACKET_GROUP.sub(replace, text.split(" | ")[0])


def _tokens(title: str) -> list[_Token]:
    text = _unwrap_parentheses(_strip_marketing(strip_leading_decoration(clean(title))))
    tokens: list[_Token] = []
    for raw in re.split(r"[\s/]+", text):
        stripped = raw.strip(_EDGE)
        key = fold(stripped).strip(_EDGE)
        # Token chỉ có dấu câu ("–", "•", "+", "&", "|") không phân biệt mẫu.
        if not any(c.isalnum() for c in key) or _PART_NUMBER.match(key):
            continue
        if key == "100%" and tokens and tokens[-1].key in _NEW_CONDITION:
            continue
        tokens.append(_Token(stripped, key))
    return tokens


def _is_switch_colour(tokens: list[_Token], index: int) -> bool:
    """Màu là một phần tên switch (`MX Red`, `Gateron Brown`, `Red Axis`, `Cream Blue`)."""
    before = tokens[index - 1].key if index > 0 else ""
    after = tokens[index + 1].key if index + 1 < len(tokens) else ""
    if before in {"switch", "sw"} and index >= 2 and tokens[index - 2].key in _SWITCH_NAME_WORDS:
        return False  # "Gateron Red Switch Đen": màu sau tên switch đầy đủ là màu vỏ (BUG-S1-7)
    if before in _SWITCH_BEFORE or after in _SWITCH_AFTER:
        return True
    # "Cream Blue" / "Cream Yellow" là tên switch của Akko, không phải hai màu vỏ.
    return (tokens[index].key == "cream" and after in _COLORS) or before == "cream"


def _is_colour_token(tokens: list[_Token], index: int) -> bool:
    key = tokens[index].key
    if key in _COLORS:
        return not _is_switch_colour(tokens, index)
    # "Xanh dương", "Xanh lá": từ thứ hai chỉ là màu khi đứng sau "xanh".
    return key in _AFTER_BLUE and index > 0 and tokens[index - 1].key == "xanh"


def _drop_colors(tokens: list[_Token]) -> list[_Token]:
    """Bỏ màu (và chữ "màu" đứng trước màu). Màu thuộc tên switch thì giữ vì nó phân biệt mẫu."""
    return [token for index, token in enumerate(tokens) if not _is_colour_token(tokens, index)]


def _leading_prefix_length(tokens: list[_Token]) -> int:
    """Số token đầu là tiền tố loại sản phẩm ("Chuột gaming không dây …")."""
    count = 0
    while count < len(tokens) and tokens[count].key in _PREFIX_WORDS:
        count += 1
    return count


def _brand_index(tokens: list[_Token], *, typed: bool = False) -> int | None:
    found = find_brand([token.key for token in tokens], typed=typed)
    return None if found is None else found[0]


def _from_brand(text: str) -> str:
    """Bỏ mô tả loại đứng trước hãng ("văn phòng Dell Inspiron …" → "Dell Inspiron …")."""
    tokens = _tokens(text)
    index = _brand_index(tokens, typed=True)
    return text if not index else " ".join(token.text for token in tokens[index:])


def canonical_name(title: str, category: Category) -> str:
    """Tên hiển thị sạch của sản phẩm.

    Laptop: từ hãng đến hết mã model (`Acer Aspire Lite 15 AL15-53P-56QH`). Nhóm khác: bỏ tiền tố
    loại, màu, mã phụ tùng và nhãn khuyến mãi. Không rỗng: về cuối dùng nguyên tiêu đề đã gọn.
    """
    cleaned = clean(title)
    if category is Category.laptop:
        span = laptop_code_span(cleaned)
        if span is not None:
            return _from_brand(span[0])
    tokens = _tokens(cleaned)
    brand_at = _brand_index(tokens)
    tokens = tokens[brand_at if brand_at is not None else _leading_prefix_length(tokens) :]
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


@lru_cache(maxsize=8192)  # hàm thuần; matcher tính lại khóa của mọi ứng viên cho mỗi offer
def name_key(name: str, brand: str) -> tuple[str, ...]:
    """Các token đã `fold` của tên, dùng để so hai sản phẩm cùng hãng.

    Bỏ: tên công ty, từ chỉ loại/quảng cáo, màu. Giữ thứ tự xuất hiện (matcher so như tập hợp).
    """
    tokens = _drop_colors(_tokens(name))
    keys = _substitute([token.key for token in tokens], _PHRASES)
    keys = _substitute(keys, _ALIASES.get(brand, ()))
    company = brand_words(brand) if brand != UNKNOWN_BRAND else frozenset()
    return tuple(key for key in keys if key not in _NOISE and key not in company and key != "")
