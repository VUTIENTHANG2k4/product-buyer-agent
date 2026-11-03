"""Chạy Alembic bằng mã (không qua `alembic.ini`), dùng cho test và `scripts.run_eval`."""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> AlembicConfig:
    """Cấu hình Alembic không qua alembic.ini để không đổi cấu hình logging của tiến trình."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def upgrade_to_head(engine: Engine) -> None:
    """Chạy `alembic upgrade head` trên `engine` trong một transaction (DDL của PostgreSQL)."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
