"""Tool `search_catalog`: tìm sản phẩm trong danh mục đã thu thập (docs/05 §3, tool 1)."""

from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
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
    "Search the already-collected catalog of laptops, mice, keyboards and headsets "
    "(tier 1 only) with price, brand, site and spec filters. Use for any shopping "
    "request in these four categories. Do NOT use for other product types "
    "(use live_search_other) and never invent products that are not returned."
)


class SearchCatalogArgs(BaseModel):
    category: Literal[Category.laptop, Category.mouse, Category.keyboard, Category.headset] = Field(
        description="Product category."
    )
    price_min: int | None = Field(default=None, ge=0, description="Minimum price in VND.")
    price_max: int | None = Field(default=None, ge=0, description="Maximum price in VND.")
    brands: list[str] = Field(default_factory=list, max_length=10, description="Brand names.")
    sites: list[SiteKey] = Field(default_factory=list, description="Empty means all sites.")
    spec_filters: list[SpecFilter] = Field(
        default_factory=list,
        max_length=10,
        description="Spec conditions, e.g. field=gpu_rank op=gte value=40.",
    )
    sort: Literal["relevance", "price_asc", "price_desc", "rating_desc"] = Field(
        default="relevance", description="Sort order."
    )
    limit: int = Field(default=10, ge=1, le=20, description="Max products to return (1-20).")


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
            price_min=args.price_min,
            price_max=args.price_max,
            brands=args.brands,
            sites=args.sites,
            spec_filters=args.spec_filters,
            sort=args.sort,
            limit=args.limit,
        )
        found = CatalogService(session, now=ctx.now).search(filters)
        result: Result = {
            "ok": True,
            "total": found.total,
            "items": [compact_summary(item) for item in found.items],
            "stale": found.stale,
            "data_as_of": iso(found.data_as_of),
            "applied_filters": found.applied_filters,
        }
        return limit_size(result, ("items",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=SearchCatalogArgs, handler=handler
    )
