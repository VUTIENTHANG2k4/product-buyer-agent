"""Fixture dùng chung: môi trường test và chặn mạng (docs/09 §3)."""

import os
import socket
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest

# Phải đặt trước khi import app.*: test không phụ thuộc cấu hình trên máy.
os.environ.update(
    {
        "LLM_PROVIDER": "fake",
        "SCRAPER_OFFLINE_ONLY": "true",
        "SCRAPER_MIN_DELAY_SECONDS": "0",
        "MOCK_SHOP_DELAY_SECONDS": "0",
        "SCRAPER_USER_AGENT": "ProductBuyerAgent-test/0.1",
    }
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/product_buyer")
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/product_buyer_test"
)

from app.config import Settings  # noqa: E402  (sau khi đặt biến môi trường ở trên)

# Test không đọc file cấu hình của máy: chỉ dùng biến môi trường đặt ở trên.
Settings.model_config["env_file"] = None

Address = tuple[Any, ...]


class NetworkBlockedError(RuntimeError):
    """Test cố mở kết nối mạng ra ngoài."""


def _resolve(host: str, port: int) -> set[Address]:
    allowed: set[Address] = {(host, port)}
    try:
        for *_, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            allowed.add(tuple(sockaddr[:2]))
    except OSError:
        pass
    return allowed


@pytest.fixture(autouse=True)
def disable_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[set[Address]]:
    """Chặn mọi socket ra ngoài, chỉ cho phép host:port của TEST_DATABASE_URL.

    Trả về tập địa chỉ được phép để test có thể thêm (ví dụ server cục bộ tạm thời).
    Test đánh dấu `live` không bị chặn.
    """
    allowed: set[Address] = set()
    if request.node.get_closest_marker("live"):
        yield allowed
        return

    db = urlsplit(os.environ["TEST_DATABASE_URL"])
    allowed |= _resolve(db.hostname or "localhost", db.port or 5432)

    real_connect = socket.socket.connect
    real_socketpair = socket.socketpair
    in_socketpair = False

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if self.family == getattr(socket, "AF_UNIX", None) or in_socketpair:
            return real_connect(self, address)
        if tuple(address[:2]) not in allowed:
            raise NetworkBlockedError(f"network bị chặn trong test: {address[:2]}")
        return real_connect(self, address)

    def guarded_socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        # Trên Windows socketpair (event loop asyncio dùng) tự connect qua loopback.
        nonlocal in_socketpair
        in_socketpair = True
        try:
            return real_socketpair(*args, **kwargs)
        finally:
            in_socketpair = False

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        try:
            guarded_connect(self, address)
        except NetworkBlockedError:
            raise
        except OSError as exc:
            return exc.errno or 1
        return 0

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    yield allowed
