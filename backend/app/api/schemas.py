"""Schema phản hồi chung của API (docs/07)."""

from typing import Any, Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """GET /api/health. `status` là "degraded" khi CSDL không kết nối được."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    llm_provider: str
    offline_mode: bool
    version: str


class ErrorDetail(BaseModel):
    """Nội dung lỗi (docs/07 §1–2). `details` luôn là object, có thể rỗng."""

    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    """Thân của mọi phản hồi lỗi 4xx/5xx."""

    error: ErrorDetail
