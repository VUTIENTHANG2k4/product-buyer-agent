"""Tool `live_search_other`: tìm trực tiếp nhóm ngoài tầng 1 (docs/05 §3, tool 2).

Tầng 2 chỉ được bật ở M10 (T10.2 `live_search_service`, T10.3 nối vào đây). Đến lúc đó tool trả
kết quả rỗng kèm lý do để agent nói rõ với người dùng.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agent.tools.base import Result, ToolContext, make_tool

NAME = "live_search_other"
DESCRIPTION = (
    "Live search on retailer sites for products OUTSIDE laptops, mice, keyboards and headsets "
    "(speakers, monitors, SSDs...). Slow; results are not normalized. Do NOT use for the four "
    "tier-1 categories (use search_catalog)."
)
NOT_ENABLED_REASON = "chưa bật tầng 2"
PENDING_SITES = ("viettelstore", "nguyenkim")


class LiveSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Search keywords.")
    price_min: int | None = Field(default=None, ge=0, description="Minimum price in VND.")
    price_max: int | None = Field(default=None, ge=0, description="Maximum price in VND.")
    limit_per_site: int = Field(default=5, ge=1, le=10, description="Max results per site (1-10).")


async def handler(ctx: ToolContext, args: LiveSearchArgs) -> Result:
    return {
        "ok": True,
        "items": [],
        "sites_searched": [],
        "sites_skipped": [{"site": site, "reason": NOT_ENABLED_REASON} for site in PENDING_SITES],
        "from_cache": False,
        "label": "unnormalized",
        "reason": NOT_ENABLED_REASON,
    }


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=LiveSearchArgs, handler=handler
    )
