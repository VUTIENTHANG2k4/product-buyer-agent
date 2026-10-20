"""Tool `add_to_shopping_list`: thêm sản phẩm vào danh sách mua (docs/05 §3, tool 6, tool GHI)."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.tools.base import Result, ToolContext, make_tool, run_in_session
from app.services.shopping_list_service import ShoppingListService

NAME = "add_to_shopping_list"
DESCRIPTION = (
    "Add a product to the user's shopping list. ONLY call when the user explicitly asks to add "
    "it in the current message (e.g. 'thêm vào danh sách'). Never call it on your own to be "
    "helpful. The id must come from earlier tool results."
)


class AddToListArgs(BaseModel):
    product_id: int = Field(ge=1, description="Product id from an earlier result.")
    list_name: str | None = Field(
        default=None, max_length=100, description="List name; omit for the default list."
    )
    quantity: int = Field(default=1, ge=1, le=100, description="Quantity to add.")
    note: str | None = Field(default=None, max_length=200, description="Optional short note.")


async def handler(ctx: ToolContext, args: AddToListArgs) -> Result:
    def work(session: Session) -> Result:
        service = ShoppingListService(session, now=ctx.now)
        shopping_list = service.get_or_create(args.list_name)
        item = service.add_item(
            shopping_list.list_id, args.product_id, quantity=args.quantity, note=args.note
        )
        return {
            "ok": True,
            "list_id": shopping_list.list_id,
            "item_id": item.item_id,
            "list_name": shopping_list.name,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "price_at_add": item.price_at_add,
            "current_price": item.current_price,
        }

    return await run_in_session(ctx, work, write=True)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=AddToListArgs, handler=handler
    )
