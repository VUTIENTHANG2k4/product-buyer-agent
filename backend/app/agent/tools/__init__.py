"""8 tool của agent (docs/05 §3). Tool chỉ gọi `app/services`."""

from langchain_core.tools import StructuredTool

from app.agent.tools import (
    add_to_shopping_list,
    compare_products,
    create_price_alert,
    get_price_history,
    get_product_detail,
    list_alerts,
    live_search_other,
    search_catalog,
)
from app.agent.tools.base import MAX_RESULT_CHARS, ToolContext

# Tool GHI: chỉ được gọi khi người dùng yêu cầu rõ ràng trong lượt hiện tại (guardrail ở executor).
WRITE_TOOLS = frozenset({add_to_shopping_list.NAME, create_price_alert.NAME})

_BUILDERS = (
    search_catalog,
    live_search_other,
    compare_products,
    get_product_detail,
    get_price_history,
    add_to_shopping_list,
    create_price_alert,
    list_alerts,
)
TOOL_NAMES = tuple(module.NAME for module in _BUILDERS)


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    """8 tool theo thứ tự trong docs/05 §3, gắn với `ctx` (cách mở session, cấu hình, đồng hồ)."""
    return [module.build(ctx) for module in _BUILDERS]


__all__ = ["MAX_RESULT_CHARS", "TOOL_NAMES", "WRITE_TOOLS", "ToolContext", "build_tools"]
