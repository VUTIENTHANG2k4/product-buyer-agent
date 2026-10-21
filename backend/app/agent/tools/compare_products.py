"""Tool `compare_products`: so sánh 2–5 sản phẩm (docs/05 §3, tool 3)."""

from typing import Annotated

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
from app.domain.catalog import ProductFull
from app.domain.dto import INT4_MAX
from app.services.compare_service import CompareService
from app.services.views import key_specs

NAME = "compare_products"
DESCRIPTION = (
    "Compare 2 to 5 products already shown to the user by their product_id: specs that differ, "
    "offers and the cheapest product. Use when the user asks to compare. Ids must come from "
    "earlier tool results."
)
MAX_OFFERS_PER_PRODUCT = 3


class CompareArgs(BaseModel):
    product_ids: list[Annotated[int, Field(ge=1, le=INT4_MAX)]] = Field(
        min_length=2, max_length=5, description="2-5 distinct ids."
    )


def compact_product(product: ProductFull, differing: list[str]) -> dict[str, object]:
    shown = key_specs(product.category, product.specs)
    shown.update({name: product.specs[name] for name in differing if name in product.specs})
    return {
        "product_id": product.product_id,
        "name": clip(product.name),
        "brand": product.brand,
        "category": product.category.value,
        "specs": shown,
        "min_price": product.min_price,
        "offers": [
            {
                "site": offer.site.value,
                "price": offer.effective_price,
                "price_type": offer.price_type.value,
                "stock_status": offer.stock_status.value,
                "url": offer.url,
                "scraped_at": iso(offer.scraped_at),
            }
            for offer in product.offers[:MAX_OFFERS_PER_PRODUCT]
        ],
    }


async def handler(ctx: ToolContext, args: CompareArgs) -> Result:
    def work(session: Session) -> Result:
        comparison = CompareService(session, now=ctx.now).compare(args.product_ids)
        result: Result = {
            "ok": True,
            "products": [
                compact_product(product, comparison.differing_fields)
                for product in comparison.products
            ],
            "differing_fields": comparison.differing_fields,
            "cheapest_product_id": comparison.cheapest_product_id,
        }
        return limit_size(result, ("products",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=CompareArgs, handler=handler
    )
