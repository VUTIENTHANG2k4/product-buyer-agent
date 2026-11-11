"""Tool `search_catalog`: tìm sản phẩm trong danh mục đã thu thập (docs/05 §3, tool 1)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, Self

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session

from app.agent.tools.base import (
    Result,
    ToolContext,
    clip,
    iso,
    limit_size,
    make_tool,
    run_in_session,
)
from app.domain.catalog import CatalogFilters, ProductSummary
from app.domain.dto import SpecFilter
from app.domain.enums import Category, SiteKey
from app.services.catalog_service import CatalogService

NAME = "search_catalog"
DESCRIPTION = (
    "Search the already-collected catalog of laptops, mice, keyboards, headsets and phones "
    "(tier 1 only) with price, brand, site, spec and keyword filters. Use for any shopping "
    "request in these five categories. Do NOT use for other product types "
    "(use live_search_other) and never invent products that are not returned."
)


_BRAND_FIELDS = frozenset({"brand", "brands"})
_SELECT_OPS = frozenset({"eq", "in", "contains", "contains_any"})
_MAX_BRANDS = 10
_MAX_KEYWORDS = 5
_MAX_KEYWORD_CHARS = 40
# Từ khóa đã có trường thông số tương ứng: lọc theo tên sẽ bỏ sót máy không ghi chữ đó trong tên
# (Lenovo Legion là laptop gaming nhưng tên không có "Gaming"), nên đổi sang bộ lọc thông số.
_KEYWORD_SPECS: Final[Mapping[tuple[Category, str], SpecFilter]] = MappingProxyType(
    {(Category.laptop, "gaming"): SpecFilter(field="is_gaming", op="eq", value=True)}
)


class SearchCatalogArgs(BaseModel):
    category: Literal[
        Category.laptop, Category.mouse, Category.keyboard, Category.headset, Category.phone
    ] = Field(description="Product category.")
    price_min: int | None = Field(default=None, ge=0, description="Minimum price in VND.")
    price_max: int | None = Field(default=None, ge=0, description="Maximum price in VND.")
    brands: list[str] = Field(
        default_factory=list, max_length=_MAX_BRANDS, description="Brand names."
    )
    sites: list[SiteKey] = Field(default_factory=list, description="Empty means all sites.")
    spec_filters: list[SpecFilter] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Spec conditions, e.g. field=gpu_rank op=gte value=40. Spec fields only: put brands "
            "in `brands`, sites in `sites` and prices in price_min/price_max, never here."
        ),
    )
    keywords: list[str] = Field(
        default_factory=list,
        max_length=_MAX_KEYWORDS,
        description=(
            "Words that must appear in the product name, e.g. ['gaming'] for 'tai nghe gaming'. "
            "Only features with no spec field; never the category, a brand, a price or a site."
        ),
    )
    sort: Literal["relevance", "price_asc", "price_desc", "rating_desc"] = Field(
        default="relevance", description="Sort order."
    )
    limit: int = Field(default=10, ge=1, le=20, description="Max products to return (1-20).")

    @model_validator(mode="after")
    def _brand_filter_belongs_in_brands(self) -> Self:
        """Chuyển `spec_filters=[{field: "brand", op: "eq", value: "Samsung"}]` sang `brands`.

        `brand` không nằm trong khung thông số nên bộ lọc đó luôn rỗng; LLM thật (Gemini) hay đặt
        nhầm hãng vào đây (eval P01, X1.8). Chỉ chuyển toán tử chọn giá trị (eq/in/contains…);
        `gte`/`lte` trên hãng vô nghĩa nên giữ nguyên.
        """
        brands = list(self.brands)
        kept: list[SpecFilter] = []
        for spec in self.spec_filters:
            if spec.field.lower() not in _BRAND_FIELDS or spec.op not in _SELECT_OPS:
                kept.append(spec)
                continue
            names = spec.value if isinstance(spec.value, list) else [str(spec.value)]
            known = {brand.lower() for brand in brands}
            for name in names:
                if name.lower() not in known:
                    brands.append(name)
                    known.add(name.lower())
        self.brands, self.spec_filters = brands[:_MAX_BRANDS], kept
        return self

    @model_validator(mode="after")
    def _keywords_are_clean(self) -> Self:
        """Bỏ khoảng trắng thừa, mục rỗng và mục trùng; từ khóa có trường thông số thì đổi sang
        bộ lọc thông số (laptop "gaming" → `is_gaming`)."""
        words: list[str] = []
        seen: set[str] = set()
        for raw in self.keywords:
            word = " ".join(raw.split())
            if len(word) > _MAX_KEYWORD_CHARS:
                raise ValueError(f"keyword longer than {_MAX_KEYWORD_CHARS} characters")
            key = word.casefold()
            if not word or key in seen:
                continue
            seen.add(key)
            spec = _KEYWORD_SPECS.get((self.category, key))
            if spec is None:
                words.append(word)
            elif all(existing.field != spec.field for existing in self.spec_filters):
                self.spec_filters = [*self.spec_filters, spec]
        self.keywords = words
        return self


def compact_summary(item: ProductSummary) -> dict[str, object]:
    best = item.best_offer
    return {
        "product_id": item.product_id,
        "name": clip(item.name),
        "brand": item.brand,
        "category": item.category.value,
        "key_specs": item.key_specs,
        "min_price": item.min_price,
        "max_price": item.max_price,
        "best_offer": {
            "site": best.site.value,
            "price": best.effective_price,
            "price_type": best.price_type.value,
            "url": best.url,
            "scraped_at": iso(best.scraped_at),
        },
        "offers_count": item.offers_count,
    }


async def handler(ctx: ToolContext, args: SearchCatalogArgs) -> Result:
    def work(session: Session) -> Result:
        filters = CatalogFilters(
            category=args.category,
            q=" ".join(args.keywords) or None,
            price_min=args.price_min,
            price_max=args.price_max,
            brands=args.brands,
            sites=args.sites,
            spec_filters=args.spec_filters,
            sort=args.sort,
            limit=args.limit,
        )
        service = CatalogService(session, now=ctx.now)
        found = service.search(filters)
        relaxed = found.total == 0 and filters.q is not None
        if relaxed:  # từ khóa làm rỗng: bỏ từ khóa, giữ mọi điều kiện khác (quyết định X1.10)
            found = service.search(filters.model_copy(update={"q": None}))
        result: Result = {
            "ok": True,
            "total": found.total,
            "items": [compact_summary(item) for item in found.items],
            "stale": found.stale,
            "data_as_of": iso(found.data_as_of),
            "applied_filters": found.applied_filters,
        }
        if relaxed:
            result["keywords_relaxed"] = True
            result["ignored_keywords"] = list(args.keywords)
        return limit_size(result, ("items",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=SearchCatalogArgs, handler=handler
    )
