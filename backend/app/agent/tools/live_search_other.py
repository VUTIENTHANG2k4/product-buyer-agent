"""Tool `live_search_other`: tìm trực tiếp nhóm ngoài tầng 1 (docs/05 §3, tool 2).

Chỉ gọi `live_search_service` (tuần tự, cache 6 giờ, nhãn chưa chuẩn hóa). Không có service (cấu
hình thiếu) thì trả kết quả rỗng kèm lý do để agent nói rõ với người dùng thay vì bịa kết quả.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agent.tools.base import Result, ToolContext, clip, iso, limit_size, make_tool
from app.domain.errors import AppError

NAME = "live_search_other"
DESCRIPTION = (
    "Live search on retailer sites for products OUTSIDE laptops, mice, keyboards and headsets "
    "(speakers, monitors, SSDs...). Slow; results are not normalized, show them as live results "
    "with only name, price and link. Do NOT use for the four tier-1 categories (use "
    "search_catalog)."
)
UNAVAILABLE_REASON = "tìm trực tiếp chưa khả dụng"


class LiveSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Search keywords.")
    price_min: int | None = Field(default=None, ge=0, description="Minimum price in VND.")
    price_max: int | None = Field(default=None, ge=0, description="Maximum price in VND.")
    limit_per_site: int = Field(default=5, ge=1, le=10, description="Max results per site (1-10).")


async def handler(ctx: ToolContext, args: LiveSearchArgs) -> Result:
    if ctx.live_search is None:
        return {
            "ok": True,
            "items": [],
            "sites_searched": [],
            "sites_skipped": [],
            "from_cache": False,
            "label": "unnormalized",
            "reason": UNAVAILABLE_REASON,
        }
    try:
        found = await ctx.live_search.search(
            args.query,
            price_min=args.price_min,
            price_max=args.price_max,
            limit_per_site=args.limit_per_site,
        )
    except AppError as error:  # từ khóa/khoảng giá sai: LLM đổi tham số rồi thử lại
        return {"ok": False, "error": error.code, "message": error.message}
    result: Result = {
        "ok": True,
        "items": [
            {
                "site": item.site.value,
                "title": clip(item.title),
                "price": item.price,
                "url": item.url,
                "scraped_at": iso(item.scraped_at),
            }
            for item in found.items
        ],
        "sites_searched": [site.value for site in found.sites_searched],
        "sites_skipped": [
            {"site": skipped.site.value, "reason": skipped.reason}
            for skipped in found.sites_skipped
        ],
        "from_cache": found.from_cache,
        "label": found.label,
    }
    return limit_size(result, ("items",))


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=LiveSearchArgs, handler=handler
    )
