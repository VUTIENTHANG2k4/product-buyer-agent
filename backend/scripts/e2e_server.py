"""Khởi động backend cho E2E Playwright (docs/09 §3, T8.8).

Chạy từ `backend/`: `uv run python -m scripts.e2e_server [--port 8010]`. Playwright gọi lệnh này qua
`webServer`; sau khi API trả `/api/health` thì bắt đầu chạy spec.

Việc làm theo thứ tự:
1. Chọn DB riêng cho E2E: `E2E_DATABASE_URL`, bỏ trống thì lấy tên DB của `DATABASE_URL` + `_e2e`.
   **Từ chối** nếu tên DB không kết thúc `_e2e`: seed `--reset` xóa sạch mọi bảng nên tuyệt đối
   không được chạy trên DB dev.
2. Tạo DB nếu chưa có, `alembic upgrade head`, `seed --fixture e2e --reset --yes` (kết quả xác
   định, chạy lại lần hai vẫn như lần đầu).
3. Chạy API với `LLM_PROVIDER=fake` và `SCRAPER_OFFLINE_ONLY=true` (không bao giờ tắt offline).
"""

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import psycopg
import uvicorn
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from app.config import get_settings

logger = logging.getLogger("e2e_server")

E2E_SUFFIX: Final = "_e2e"
DEFAULT_PORT: Final = 8010
BACKEND_DIR: Final = Path(__file__).resolve().parents[1]


class UnsafeE2eDatabase(ValueError):
    """Tên DB không kết thúc `_e2e` nên không được phép xóa sạch."""


def derive_e2e_url(database_url: str, explicit: str = "") -> URL:
    """URL của DB E2E: `explicit` nếu có, ngược lại tên DB của `database_url` + `_e2e`.

    Ném `UnsafeE2eDatabase` nếu kết quả không có tên DB kết thúc `_e2e`.
    """
    if explicit.strip():
        url = make_url(explicit.strip())
    else:
        base = make_url(database_url)
        name = base.database or ""
        url = base.set(database=name if name.endswith(E2E_SUFFIX) else f"{name}{E2E_SUFFIX}")
    if not (url.database or "").endswith(E2E_SUFFIX) or url.database == E2E_SUFFIX:
        raise UnsafeE2eDatabase(
            f"Tên DB E2E phải kết thúc bằng '{E2E_SUFFIX}' (nhận '{url.database}'); "
            "script từ chối chạy seed --reset trên DB khác."
        )
    return url


def admin_url(url: URL) -> URL:
    """URL tới DB `postgres` cùng máy chủ, dùng để tạo DB E2E."""
    return url.set(database="postgres")


def _libpq(url: URL) -> str:
    """Chuỗi kết nối psycopg (không có phần `+psycopg` của SQLAlchemy)."""
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def ensure_database(url: URL) -> bool:
    """Tạo DB của `url` nếu chưa có; trả `True` nếu vừa tạo."""
    name = url.database
    if not name or not name.endswith(E2E_SUFFIX):
        raise UnsafeE2eDatabase(f"Không tạo DB '{name}': tên phải kết thúc bằng '{E2E_SUFFIX}'.")
    with psycopg.connect(_libpq(admin_url(url)), autocommit=True, connect_timeout=5) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if exists:
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        return True


def e2e_environment(url: URL, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Biến môi trường cho tiến trình con: DB E2E, LLM giả, luôn offline."""
    env = dict(os.environ if base is None else base)
    env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    env["LLM_PROVIDER"] = "fake"
    env["SCRAPER_OFFLINE_ONLY"] = "true"
    return env


def _run(args: Sequence[str], env: Mapping[str, str]) -> None:
    subprocess.run([sys.executable, "-m", *args], cwd=BACKEND_DIR, env=dict(env), check=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backend cho E2E Playwright (DB riêng + LLM giả).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[e2e] %(message)s")

    settings = get_settings()
    try:
        url = derive_e2e_url(
            settings.database_url.get_secret_value(), settings.e2e_database_url.get_secret_value()
        )
    except UnsafeE2eDatabase as error:
        logger.error("%s", error)
        return 2

    created = ensure_database(url)
    logger.info("DB %s %s", url.database, "đã tạo" if created else "đã có")
    env = e2e_environment(url)
    _run(["alembic", "upgrade", "head"], env)
    _run(["scripts.seed", "--fixture", "e2e", "--reset", "--yes"], env)

    # Tiến trình này phục vụ API: đặt môi trường rồi xóa cache cấu hình để `create_app` thấy DB E2E.
    os.environ.update(env)
    get_settings.cache_clear()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
