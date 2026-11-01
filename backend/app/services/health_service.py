"""Kiểm tra sức khỏe hệ thống cho GET /api/health."""

import logging
from typing import Literal

from sqlalchemy import text

from app.db.engine import get_engine

logger = logging.getLogger(__name__)

DbStatus = Literal["ok", "error"]


def check_db(database_url: str) -> DbStatus:
    """Chạy `SELECT 1`; lỗi kết nối trả "error", không ném exception."""
    try:
        with get_engine(database_url).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Không kết nối được CSDL: %s", type(exc).__name__)
        return "error"
    return "ok"
