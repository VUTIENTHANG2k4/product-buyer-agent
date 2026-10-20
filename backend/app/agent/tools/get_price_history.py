"""Tool `get_price_history`: lịch sử giá theo trang (docs/05 §3, tool 5)."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.tools.base import Result, ToolContext, iso, limit_size, make_tool, run_in_session
from app.domain.catalog import PricePointView
from app.services.catalog_service import MAX_HISTORY_DAYS, CatalogService

NAME = "get_price_history"
DESCRIPTION = (
    "Get the price history of one product per site over the last N days (max 180), with the "
    "lowest and highest price seen. Use when the user asks how the price changed. The id must "
    "come from earlier tool results."
)
MAX_POINTS_PER_SITE = 30


class HistoryArgs(BaseModel):
    product_id: int = Field(ge=1, description="Product id from an earlier result.")
    days: int = Field(default=30, ge=1, le=MAX_HISTORY_DAYS, description="Look-back days.")


def downsample(
    points: list[PricePointView], limit: int = MAX_POINTS_PER_SITE
) -> list[PricePointView]:
    """Tối đa `limit` điểm, trải đều và luôn giữ điểm đầu và điểm cuối."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(index * step)] for index in range(limit)]


async def handler(ctx: ToolContext, args: HistoryArgs) -> Result:
    def work(session: Session) -> Result:
        history = CatalogService(session, now=ctx.now).price_history(args.product_id, args.days)
        result: Result = {
            "ok": True,
            "product_id": args.product_id,
            "days": args.days,
            "series": [
                {
                    "site": series.site.value,
                    "point_count": len(series.points),
                    "points": [
                        {"t": iso(point.t), "price": point.price}
                        for point in downsample(series.points)
                    ],
                }
                for series in history.series
            ],
            "min_price": history.min_price,
            "max_price": history.max_price,
        }
        return limit_size(result, ("series",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=HistoryArgs, handler=handler
    )
