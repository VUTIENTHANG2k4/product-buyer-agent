"""Ghép offer vào Product (docs/04 §7): hàm thuần, không đụng CSDL.

Thứ tự quyết định:

1. Trùng `model_code` (cùng category + brand do người gọi lọc sẵn) → `model_code`, điểm 1,0.
2. Không có mã trùng: so tên (`token_sort_ratio ≥ 0,90`) kèm các chốt chặn để không ghép nhầm:
   token có chữ số (`g304`, `75`) phải trùng, tập từ còn lại (`pro`, `mini`, `wireless`, tên
   switch…) phải trùng, và các trường bắt buộc không được mâu thuẫn. → `fuzzy`.
3. Còn lại → `new`.

Ưu tiên "không ghép sai" hơn "ghép đủ": hai mẫu chưa chắc cùng nhau thì giữ riêng. Hãng
`Unknown` không bao giờ ghép mờ vì mọi mẫu chưa rõ hãng sẽ lẫn vào nhau.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from rapidfuzz import fuzz

from app.domain.enums import Category, MatchMethod
from app.normalize.brand import UNKNOWN_BRAND
from app.normalize.extract import missing_required
from app.normalize.names import name_key
from app.normalize.specs import REQUIRED_FIELDS

FUZZY_THRESHOLD: Final = 0.90


@dataclass(frozen=True)
class Candidate:
    """Một Product có sẵn cùng category và brand."""

    product_id: int
    canonical_name: str
    model_code: str | None
    specs: Mapping[str, Any]


@dataclass(frozen=True)
class MatchDecision:
    """Kết quả ghép. `product_id` là `None` khi cần tạo Product mới.

    `code_taken` báo mã model đã thuộc một Product khác nhưng thông số mâu thuẫn nên không ghép:
    Product mới không được mang mã đó (chỉ mục unique `(category, brand, model_code)`).
    """

    product_id: int | None
    method: MatchMethod
    score: float | None
    code_taken: bool = False


def _as_comparable(value: Any) -> Any:
    return frozenset(value) if isinstance(value, list) else value


def specs_compatible(
    category: Category, left: Mapping[str, Any], right: Mapping[str, Any], *, strict: bool = False
) -> bool:
    """Các trường bắt buộc có ở cả hai bên phải bằng nhau (danh sách so như tập hợp).

    `strict`: cả hai bên phải có đủ mọi trường bắt buộc (dùng khi ghép mờ laptop, không có mã).
    """
    required = REQUIRED_FIELDS.get(category, ())
    if strict and (missing_required(category, left) or missing_required(category, right)):
        return False
    for name in required:
        a, b = left.get(name), right.get(name)
        if a in (None, []) or b in (None, []):
            continue
        if _as_comparable(a) != _as_comparable(b):
            return False
    return True


def _has_digit(token: str) -> bool:
    return any(char.isdigit() for char in token)


def same_model_name(left: Sequence[str], right: Sequence[str]) -> bool:
    """Hai khóa tên là cùng một mẫu: cùng token có số, cùng tập từ, độ giống ≥ 0,90."""
    if not left or not right:
        return False
    if {t for t in left if _has_digit(t)} != {t for t in right if _has_digit(t)}:
        return False
    if {t for t in left if not _has_digit(t)} != {t for t in right if not _has_digit(t)}:
        return False
    return fuzz.token_sort_ratio(" ".join(left), " ".join(right)) / 100 >= FUZZY_THRESHOLD


def name_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    """Độ giống 0..1 của hai khóa tên (rapidfuzz `token_sort_ratio`)."""
    return float(fuzz.token_sort_ratio(" ".join(left), " ".join(right))) / 100


def decide_match(
    category: Category,
    brand: str,
    model_code: str | None,
    name: str,
    specs: Mapping[str, Any],
    candidates: Sequence[Candidate],
) -> MatchDecision:
    """Chọn Product có sẵn để ghép (hoặc `new`). `candidates` cùng category và brand với offer."""
    code_taken = False
    if model_code is not None:
        for candidate in candidates:
            if candidate.model_code != model_code:
                continue
            if specs_compatible(category, specs, candidate.specs):
                return MatchDecision(candidate.product_id, MatchMethod.model_code, 1.0)
            code_taken = True  # cùng mã nhưng cấu hình khác: coi là mẫu riêng
    if brand == UNKNOWN_BRAND:
        return MatchDecision(None, MatchMethod.new, None, code_taken)

    key = name_key(name, brand)
    strict = category is Category.laptop
    best: tuple[float, int] | None = None
    for candidate in sorted(candidates, key=lambda c: c.product_id):
        if model_code is not None and candidate.model_code not in (None, model_code):
            continue  # hai mã khác nhau rõ ràng là hai mẫu
        other = name_key(candidate.canonical_name, brand)
        if not same_model_name(key, other):
            continue
        if not specs_compatible(category, specs, candidate.specs, strict=strict):
            continue
        score = name_similarity(key, other)
        if best is None or score > best[0]:
            best = (score, candidate.product_id)
    if best is None:
        return MatchDecision(None, MatchMethod.new, None, code_taken)
    return MatchDecision(best[1], MatchMethod.fuzzy, round(best[0], 4), code_taken)
