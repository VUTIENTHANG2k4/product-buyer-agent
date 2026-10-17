"""Môi trường Alembic: metadata từ SQLModel, URL từ `Settings` (docs/04 §3, ADR-0007).

URL lấy theo thứ tự: kết nối truyền qua `config.attributes["connection"]` (test dùng), rồi
`sqlalchemy.url` nếu có, cuối cùng là `DATABASE_URL` trong cấu hình ứng dụng.
"""

from logging.config import fileConfig

from sqlalchemy import Connection, create_engine, pool
from sqlmodel import SQLModel

import app.db.models  # noqa: F401  (đăng ký bảng vào SQLModel.metadata để autogenerate thấy)
from alembic import context
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def _database_url() -> str:
    return (
        config.get_main_option("sqlalchemy.url") or get_settings().database_url.get_secret_value()
    )


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)


def run_migrations_offline() -> None:
    """Sinh SQL ra stdout, không kết nối DB."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    shared: Connection | None = config.attributes.get("connection")
    if shared is not None:
        _configure(shared)
        with context.begin_transaction():
            context.run_migrations()
        return

    # connect_timeout như app/db/engine.py: DB tắt hoặc localhost phân giải sang IPv6 không ai nghe
    # thì báo lỗi sau vài giây thay vì treo vô hạn.
    connectable = create_engine(
        _database_url(), poolclass=pool.NullPool, connect_args={"connect_timeout": 3}
    )
    with connectable.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
