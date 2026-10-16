"""Schema phản hồi chung của API (docs/07)."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """GET /api/health. `status` là "degraded" khi CSDL không kết nối được."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    llm_provider: str
    offline_mode: bool
    version: str
