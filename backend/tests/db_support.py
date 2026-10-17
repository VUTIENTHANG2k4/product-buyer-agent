"""Hàm dùng chung cho test CSDL: cấu hình Alembic chạy qua kết nối có sẵn (docs/09 §4)."""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> AlembicConfig:
    """Cấu hình Alembic không qua alembic.ini để test không đổi cấu hình logging của pytest."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def upgrade_to_head(engine: Engine) -> None:
    """Chạy `alembic upgrade head` trên `engine` trong một transaction (DDL của PostgreSQL)."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def downgrade_to_base(engine: Engine) -> None:
    """Chạy `alembic downgrade base` trên `engine` trong một transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
