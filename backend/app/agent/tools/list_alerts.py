"""Tool `list_alerts`: xem các cảnh báo giá đang theo dõi (docs/05 §3, tool 8)."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.tools.base import Result, ToolContext, clip, limit_size, make_tool, run_in_session
from app.domain.enums import AlertStatus
from app.services.alert_service import AlertService

NAME = "list_alerts"
DESCRIPTION = (
    "List the user's price alerts (optionally by status). Use when the user asks which products "
    "they are tracking or what alerts exist. Read-only."
)
MAX_ALERTS = 20


class ListAlertsArgs(BaseModel):
    status: AlertStatus | None = Field(
        default=None, description="active, triggered or paused; omit for all."
    )


async def handler(ctx: ToolContext, args: ListAlertsArgs) -> Result:
    def work(session: Session) -> Result:
        alerts = AlertService(session, ctx.settings, now=ctx.now).list_alerts(args.status)
        result: Result = {
            "ok": True,
            "total": len(alerts),
            "alerts": [
                {
                    "alert_id": alert.alert_id,
                    "product_id": alert.product_id,
                    "product_name": clip(alert.product_name),
                    "target_price": alert.target_price,
                    "channel": alert.channel.value,
                    "status": alert.status.value,
                    "current_best_price": alert.current_best_price,
                }
                for alert in alerts[:MAX_ALERTS]
            ],
        }
        if len(alerts) > MAX_ALERTS:
            result["truncated"] = True
        return limit_size(result, ("alerts",))

    return await run_in_session(ctx, work)


def build(ctx: ToolContext) -> StructuredTool:
    return make_tool(
        ctx, name=NAME, description=DESCRIPTION, args_schema=ListAlertsArgs, handler=handler
    )
