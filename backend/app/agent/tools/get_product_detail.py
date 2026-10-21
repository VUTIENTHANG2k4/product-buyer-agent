"""Tool `get_product_detail`: thông số đầy đủ và mọi offer của một sản phẩm (docs/05 §3, tool 4)."""

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
from app.domain.dto import INT4_MAX
from app.services.catalog_service import CatalogService

NAME = "get_product_detail"
DESCRIPTION = (
    "Get full specs and every current offer (site, price, stock, link) of one product by "
    "product_id. Use when the user asks about a specific product. The id must come from "
    "earlier tool results."
)
MAX_OFFERS = 8


class DetailArgs(BaseModel):
    product_id: int = Field(ge=1, le=INT4_MAX, description="Product id from an earlier result.")


async def handler(ctx: ToolContext, args: DetailArgs) -> Result:
    def work(session: Session) -> Result:
        product = CatalogService(session, now=ctx.now).get_detail(args.product_id)
        result: Result = {
            "ok": True,
            "product_id": product.product_id,
            "name": clip(product.name),
            "brand": product.brand,
            "category": product.category.value,
            "model_code": product.model_code,
            "specs": product.specs,
            "min_price": product.min_price,
            "max_price": product.max_price,
            "offers": [
                {
                    "offer_id": offer.offer_id,
                    "site": offer.site.value,
                    "price": offer.effective_price,
                    "list_price": offer.list_price,
                    "price_type": offer.price_type.value,
                    "stock_status": offer.stock_status.value,
                    "url": offer.url,
                    "scraped_at": iso(offer.scraped_at),
                }
                for offer in product.offers[:MAX_OFFERS]
            ],
        }
        return limit_size(result, ("offers",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=DetailArgs, handler=handler
    )
