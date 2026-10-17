"""Fixture dùng chung: môi trường test và chặn mạng (docs/09 §3)."""

import ipaddress
import os
import socket
from asyncio.proactor_events import BaseProactorEventLoop
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


def _is_ip_literal(host: str) -> bool:
    """IP dạng số không cần DNS; việc có được kết nối tới hay không do chốt connect quyết định."""
    # Zone id chỉ có ở IPv6 (fe80::1%eth0); "1.2.3.4%x" không phải IP, phải qua kiểm tra tên.
    address = host.split("%", 1)[0] if ":" in host else host
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


@pytest.fixture(autouse=True)
def disable_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[set[Address]]:
    """Chặn mọi socket ra ngoài và mọi truy vấn DNS tới tên lạ.

    Chỉ cho phép host:port của TEST_DATABASE_URL; DNS chỉ cho `localhost`, IP dạng số và các
    host chuỗi nằm trong tập được phép. Trả về tập địa chỉ được phép để test có thể thêm
    (ví dụ server cục bộ tạm thời). Test đánh dấu `live` không bị chặn.
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

    af_unix = getattr(socket, "AF_UNIX", None)

    def check_connect(address: Any) -> None:
        if tuple(address[:2]) not in allowed:
            raise NetworkBlockedError(f"network bị chặn trong test: {address[:2]}")

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if self.family != af_unix and not in_socketpair:
            check_connect(address)
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

    def check_host(host: str | bytes | None) -> None:
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if not host or _is_ip_literal(host) or host.lower() == "localhost":
            return
        if host not in {name for name, *_ in allowed if isinstance(name, str)}:
            raise NetworkBlockedError(f"network bị chặn trong test: DNS {host}")

    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    real_gethostbyname_ex = socket.gethostbyname_ex

    # loop.getaddrinfo của asyncio tra `socket.getaddrinfo` lúc gọi nên cũng đi qua hàm này.
    def guarded_getaddrinfo(host: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
        check_host(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host: str) -> str:
        check_host(host)
        return real_gethostbyname(host)

    def guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        check_host(host)
        return real_gethostbyname_ex(host)

    # Trên Windows asyncio mặc định dùng ProactorEventLoop: kết nối bằng ConnectEx chứ không gọi
    # socket.connect, nên phải chặn ở sock_connect (create_connection, open_connection và
    # httpx.AsyncClient đều đi qua đây). Loop Selector (Linux/macOS) đã bị chặn bởi socket.connect.
    real_sock_connect = BaseProactorEventLoop.sock_connect

    async def guarded_sock_connect(
        self: BaseProactorEventLoop, sock: socket.socket, address: Any
    ) -> None:
        if sock.family != af_unix:
            check_connect(address)
        return await real_sock_connect(self, sock, address)

    monkeypatch.setattr(BaseProactorEventLoop, "sock_connect", guarded_sock_connect)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", guarded_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    yield allowed
