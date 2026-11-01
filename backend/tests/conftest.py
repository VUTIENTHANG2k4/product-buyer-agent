"""Fixture dùng chung: môi trường test và chặn mạng (docs/09 §3)."""

import ipaddress
import os
import socket
from asyncio.proactor_events import BaseProactorEventLoop
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from tests.db_support import BACKEND_DIR, upgrade_to_head

REPO_ROOT = BACKEND_DIR.parent

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
# CSDL test: biến môi trường (CI) > .env của máy (cổng Postgres khác nhau giữa các máy) > mặc định.
# Chỉ đọc đúng khóa này từ .env; các cấu hình khác vẫn do conftest đặt cố định ở trên.
_test_db_url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(REPO_ROOT / ".env").get(
    "TEST_DATABASE_URL"
)
_parsed_db_url = make_url(
    _test_db_url or "postgresql+psycopg://test:test@localhost:5432/product_buyer_test"
)
if _parsed_db_url.host == "localhost":
    # Docker chỉ mở cổng trên 127.0.0.1; `localhost` thử ::1 trước và treo hết connect_timeout
    # (3 giây) ở mỗi kết nối mới trên Windows.
    _parsed_db_url = _parsed_db_url.set(host="127.0.0.1")
os.environ["TEST_DATABASE_URL"] = _parsed_db_url.render_as_string(hide_password=False)

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

    real_gethostbyaddr = socket.gethostbyaddr
    real_getnameinfo = socket.getnameinfo
    real_sendto = socket.socket.sendto

    def check_reverse(host: str | bytes | None) -> None:
        """Tra ngược IP -> tên cũng gửi truy vấn DNS: chỉ cho loopback và địa chỉ được phép."""
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        address = (host or "").split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            check_host(host)
            return
        if not ip.is_loopback and not any(ip_text == address for ip_text, *_ in allowed):
            raise NetworkBlockedError(f"network bị chặn trong test: DNS ngược {host}")

    def guarded_gethostbyaddr(host: str) -> tuple[str, list[str], list[str]]:
        check_reverse(host)
        return real_gethostbyaddr(host)

    def guarded_getnameinfo(sockaddr: Any, flags: int) -> tuple[str, str]:
        check_reverse(sockaddr[0])
        return real_getnameinfo(sockaddr, flags)

    def guarded_sendto(self: socket.socket, data: Any, *args: Any) -> int:
        # sendto(data, address) hoặc sendto(data, flags, address); socket UNIX không có IP.
        if self.family != af_unix:
            check_connect(args[-1])
        return real_sendto(self, data, *args)

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

    real_sock_sendto = BaseProactorEventLoop.sock_sendto

    async def guarded_sock_sendto(
        self: BaseProactorEventLoop, sock: socket.socket, data: Any, address: Any = None
    ) -> int:
        if sock.family != af_unix and address is not None:
            check_connect(address)
        return await real_sock_sendto(self, sock, data, address)

    monkeypatch.setattr(BaseProactorEventLoop, "sock_connect", guarded_sock_connect)
    monkeypatch.setattr(BaseProactorEventLoop, "sock_sendto", guarded_sock_sendto)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)
    monkeypatch.setattr(socket, "getnameinfo", guarded_getnameinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", guarded_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    yield allowed


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Engine tới `TEST_DATABASE_URL`, đã `alembic upgrade head` (một lần mỗi phiên pytest).

    Không kết nối được thì dừng cả phiên với hướng dẫn, thay vì để từng test báo lỗi kết nối.
    """
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (url.database or "").endswith("_test"):
        # Chốt chặn: test chạy `upgrade head` và kiểm đếm bảng, không bao giờ được trỏ vào DB dev.
        pytest.exit(
            f"TEST_DATABASE_URL must point to a database whose name ends with _test "
            f"(got {url.database!r}); refusing to run DB tests against it.",
            returncode=2,
        )
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        engine.dispose()
        pytest.exit(
            # ASCII: pytest in thông báo thoát bằng escape trên console Windows (cp1252).
            f"Cannot reach the test PostgreSQL ({type(exc.orig).__name__}). "
            "Run `make db-up` and check TEST_DATABASE_URL in .env.",
            returncode=2,
        )
    upgrade_to_head(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Session PostgreSQL; mọi thay đổi (kể cả `commit()`) bị rollback khi test kết thúc.

    Transaction ngoài ôm cả test; `create_savepoint` làm `commit()` trong code chỉ giải phóng
    savepoint. Test cần kiểm lỗi ràng buộc dùng `with session.begin_nested():` để lỗi không làm
    hỏng transaction.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
