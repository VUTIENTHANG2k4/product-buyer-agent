"""Gắn offer vào `Product`: giữ sản phẩm của offer đã có, ghép theo mã model/tên hoặc tạo mới
(`normalize.matcher`, docs/04 §7); kiểm URL của mục."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session

from app.db.models import Offer, Product
from app.db.repositories import LlmExtractionCacheRepository, OfferRepository, ProductRepository
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, MatchMethod
from app.normalize.brand import UNKNOWN_BRAND, detect_brand
from app.normalize.extract import SpecsExtraction, extract_specs, merge_specs, specs_confidence
from app.normalize.llm_extract import LlmSpecsFiller
from app.normalize.matcher import Candidate, decide_match
from app.normalize.model_code import extract_model_code
from app.normalize.names import canonical_name
from app.normalize.url import clean_url, host_key, scheme_twin
from app.scrapers.base import SiteConfig

logger = logging.getLogger(__name__)


class UnpricedItem(ValueError):
    """Mục không có giá dùng được (che, ngoài miền, 0): offer cũ của nó coi như hết bán."""


class InvalidItemUrl(ValueError):
    """Liên kết của mục trỏ ra ngoài trang hoặc về chính trang danh sách: không lưu thành offer."""


# ---- gắn offer vào product ----
@dataclass(frozen=True)
class Resolution:
    """Product mà một offer thuộc về và cách ghép (lưu vào `offer.match_method/match_score`)."""

    product_id: int
    method: MatchMethod
    score: float | None


ProductResolver = Callable[
    [Session, Category, ListingItem, ProductDetail | None, Mapping[str, str]], Resolution
]


def find_existing_offer(offers: OfferRepository, url: str) -> Offer | None:
    """Offer đã lưu của `url` (đã qua `clean_url`), kể cả khi trước đó trang dùng scheme còn lại.

    Cùng một sản phẩm khi thì `http://…` khi thì `https://…` là một offer, giữ URL đã lưu đầu tiên.
    """
    return offers.get_by_url(url) or offers.get_by_url(scheme_twin(url))


class _RepoSpecsCache:
    """Đưa `LlmExtractionCacheRepository` (theo session của mục) về giao diện `SpecsCache`."""

    def __init__(self, session: Session) -> None:
        self._repo = LlmExtractionCacheRepository(session)

    def get(self, content_hash: str) -> Mapping[str, Any] | None:
        entry = self._repo.get(content_hash)
        return None if entry is None else entry.result

    def put(
        self, content_hash: str, category: Category, result: Mapping[str, Any], model: str
    ) -> None:
        self._repo.put(content_hash, category, result, model)


def make_resolver(spec_filler: LlmSpecsFiller | None = None) -> ProductResolver:
    """`resolve_product` có (hoặc không có) LLM dự phòng điền trường bắt buộc còn thiếu."""

    def resolver(
        session: Session,
        category: Category,
        item: ListingItem,
        detail: ProductDetail | None,
        raw_specs: Mapping[str, str] | None = None,
    ) -> Resolution:
        return resolve_product(session, category, item, detail, raw_specs, spec_filler=spec_filler)

    return resolver


def resolve_product(
    session: Session,
    category: Category,
    item: ListingItem,
    detail: ProductDetail | None,
    raw_specs: Mapping[str, str] | None = None,
    *,
    spec_filler: LlmSpecsFiller | None = None,
) -> Resolution:
    """Product cho `item`: giữ sản phẩm của offer đã có, nếu không thì ghép hoặc tạo mới.

    `raw_specs` là bảng thông số đã gộp (offer cũ, thẻ, chi tiết); mặc định gộp thẻ + chi tiết.
    Thông số trích bằng luật chỉ điền thêm trường còn thiếu cho sản phẩm đã có, không ghi đè.
    `spec_filler` (T5.3) chỉ chạy khi luật còn thiếu trường bắt buộc.
    """
    raw = (
        dict(raw_specs)
        if raw_specs is not None
        else {**item.raw_specs, **(detail.raw_specs if detail is not None else {})}
    )
    extraction: SpecsExtraction = extract_specs(category, item.title, raw)
    if spec_filler is not None and extraction.missing:
        extraction = spec_filler(_RepoSpecsCache(session), category, item.title, raw, extraction)
    products = ProductRepository(session)
    existing = find_existing_offer(OfferRepository(session), clean_url(str(item.url)))
    if existing is not None:
        product = products.get(existing.product_id)
        if product is not None and product.category is category:
            _enrich(products, product, category, extraction.specs, None, _image_of(item))
        elif product is not None:
            logger.info(
                "Offer đã thuộc nhóm %s, không gộp thông số nhóm %s", product.category, category
            )
        return Resolution(existing.product_id, existing.match_method, existing.match_score)

    brand = detect_brand(item.title)
    if brand == UNKNOWN_BRAND and detail is not None and detail.brand_hint:
        brand = detect_brand(detail.brand_hint)
    code = extract_model_code(category, item.title, detail.model_code_hint if detail else None)
    name = canonical_name(item.title, category)
    candidates = [
        Candidate(_require_product_id(p), p.canonical_name, p.model_code, p.specs)
        for p in products.list_by_brand(category, brand)
    ]
    decision = decide_match(category, brand, code, name, extraction.specs, candidates)
    if decision.product_id is not None:
        matched = products.get(decision.product_id)
        if matched is None:  # pragma: no cover - ứng viên vừa đọc trong cùng transaction
            raise RuntimeError("matched product disappeared")
        _enrich(products, matched, category, extraction.specs, code, _image_of(item))
        return Resolution(decision.product_id, decision.method, decision.score)
    product = products.add(
        Product(
            category=category,
            brand=brand,
            model_code=None if decision.code_taken else code,
            canonical_name=name,
            specs=extraction.specs,
            specs_confidence=extraction.confidence,
            image_url=_image_of(item),
        )
    )
    return Resolution(_require_product_id(product), MatchMethod.new, None)


def _enrich(
    products: ProductRepository,
    product: Product,
    category: Category,
    specs: Mapping[str, Any],
    model_code: str | None,
    image_url: str | None = None,
) -> None:
    """Điền thông số, mã model và ảnh còn thiếu cho sản phẩm đã có (không ghi đè giá trị cũ)."""
    conflicts = [
        name
        for name, value in specs.items()
        if name != "gpu_rank" and name in product.specs and product.specs[name] != value
    ]
    if conflicts:
        logger.warning("Product %s: thông số mâu thuẫn %s, giữ giá trị cũ", product.id, conflicts)
    merged = merge_specs(category, product.specs, specs)
    if merged != product.specs:
        products.update_specs(product, merged, specs_confidence(category, merged))
    if (
        model_code is not None
        and product.model_code is None
        and products.find_by_model_key(category, product.brand, model_code) is None
    ):
        products.set_model_code(product, model_code)
    if image_url is not None and product.image_url is None:
        products.set_image_url(product, image_url)


def _image_of(item: ListingItem) -> str | None:
    return str(item.image_url) if item.image_url else None


def _require_product_id(product: Product) -> int:
    if product.id is None:  # pragma: no cover - flush luôn gán id
        raise RuntimeError("product has no id after flush")
    return product.id


def url_key(item: ListingItem) -> str | None:
    """URL đã làm sạch của mục (http và https của cùng URL cho cùng khóa), hoặc `None` nếu không
    làm sạch được (mục sẽ lỗi ở bước lưu)."""
    try:
        url = clean_url(str(item.url))
    except ValueError:
        return None
    return min(url, scheme_twin(url))


def check_item_url(config: SiteConfig, url: str) -> None:
    """URL mục phải cùng máy chủ với trang và không phải trang danh sách/trang chủ."""
    if host_key(url) != host_key(config.base_url):
        raise InvalidItemUrl(f"item URL is outside {config.base_url}")
    listing_paths = {urlsplit(page).path or "/" for page in config.categories.values()} | {"/"}
    if (urlsplit(url).path or "/") in listing_paths:
        raise InvalidItemUrl("item URL points to a listing page, not a product")
