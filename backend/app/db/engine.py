"""Engine SQLAlchemy dùng chung (PostgreSQL, ADR-0007)."""

from functools import lru_cache

from sqlalchemy import Engine
from sqlmodel import create_engine


@lru_cache
def get_engine(database_url: str) -> Engine:
    """Engine một lần cho mỗi URL; `pool_pre_ping` loại bỏ kết nối đã chết, timeout 3 giây."""
    return create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
