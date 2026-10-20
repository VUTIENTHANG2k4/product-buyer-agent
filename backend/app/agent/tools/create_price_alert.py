"""Tool `create_price_alert`: đặt cảnh báo giảm giá (docs/05 §3, tool 7, tool GHI).

Địa chỉ nhận lấy từ cấu hình (`ALERT_DEFAULT_EMAIL`, `TELEGRAM_CHAT_ID`); tool không nhận địa chỉ
từ LLM để agent không hỏi hay lưu email của người dùng.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.tools.base import Result, ToolContext, make_tool, run_in_session
from app.domain.catalog import AlertCreate
from app.domain.enums import AlertChannel
from app.services.alert_service import AlertService

NAME = "create_price_alert"
DESCRIPTION = (
    "Create a price-drop alert for a product. ONLY call when the user explicitly asks to be "
    "notified (e.g. 'báo tôi khi giá xuống dưới...') in the current message. The id must come "
    "from earlier tool results. The destination is taken from configuration."
)


class AlertArgs(BaseModel):
    product_id: int = Field(ge=1, description="Product id from an earlier result.")
    target_price: int = Field(
        ge=1, le=10**12, description="Notify when the price is at or below this, in VND."
    )
    channel: AlertChannel | None = Field(
        default=None, description="email or telegram; omit for the configured default."
    )


async def handler(ctx: ToolContext, args: AlertArgs) -> Result:
    def work(session: Session) -> Result:
        alert = AlertService(session, ctx.settings, now=ctx.now).create(
            AlertCreate(
                product_id=args.product_id, target_price=args.target_price, channel=args.channel
            )
        )
        return {
            "ok": True,
            "alert_id": alert.alert_id,
            "product_id": alert.product_id,
            "target_price": alert.target_price,
            "channel": alert.channel.value,
            "current_best_price": alert.current_best_price,
        }

    return await run_in_session(ctx, work, write=True)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=AlertArgs, handler=handler
    )
