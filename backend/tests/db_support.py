"""Hàm dùng chung cho test CSDL: cấu hình Alembic chạy qua kết nối có sẵn (docs/09 §4)."""

from sqlalchemy import Engine

from alembic import command
from app.db.migrations import BACKEND_DIR, alembic_config, upgrade_to_head

__all__ = [
    "BACKEND_DIR",
    "alembic_config",
    "downgrade_to",
    "downgrade_to_base",
    "upgrade_to",
    "upgrade_to_head",
]


def upgrade_to(engine: Engine, revision: str) -> None:
    """Chạy `alembic upgrade <revision>` trên `engine` trong một transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade_to(engine: Engine, revision: str) -> None:
    """Chạy `alembic downgrade <revision>` trên `engine` trong một transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def downgrade_to_base(engine: Engine) -> None:
    """Chạy `alembic downgrade base` trên `engine` trong một transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
