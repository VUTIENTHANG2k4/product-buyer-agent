"""Ca biên của fixture chặn mạng: nó phải chặn thật, kể cả với asyncio và cổng lạ."""

import asyncio
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

BLOCKED = "network bị chặn"


@contextmanager
def expect_blocked() -> Iterator[None]:
    """Chấp nhận lỗi chặn mạng trần hoặc bị bọc trong ExceptionGroup.

    `anyio.connect_tcp` (httpcore) chạy các lần kết nối trong một task group và chỉ bắt
    `OSError`, nên lỗi chặn (RuntimeError) tới tay người gọi dưới dạng ExceptionGroup.
    """
    with pytest.raises((RuntimeError, ExceptionGroup)) as info:
        yield
    error = info.value
    leaves = error.exceptions if isinstance(error, ExceptionGroup) else (error,)
    assert leaves
    assert all(isinstance(e, RuntimeError) and BLOCKED in str(e) for e in leaves), leaves


def _closed_loopback_port() -> int:
    """Cổng loopback đang không ai nghe (không rời khỏi máy)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_connect_ex_to_external_address_raises_instead_of_returning_an_errno() -> None:
    with socket.socket() as s, pytest.raises(RuntimeError, match=BLOCKED):
        s.connect_ex(("203.0.113.5", 443))


def test_create_connection_to_external_ip_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.create_connection(("203.0.113.5", 443), timeout=1)


def test_loopback_on_a_port_that_is_not_allowed_is_blocked() -> None:
    # Chỉ host:port của TEST_DATABASE_URL được phép, không phải cả loopback.
    port = _closed_loopback_port()
    with socket.socket() as s, pytest.raises(RuntimeError, match=BLOCKED):
        s.connect(("127.0.0.1", port))


def test_ipv6_external_address_is_blocked() -> None:
    try:
        s = socket.socket(socket.AF_INET6)
    except OSError:
        pytest.skip("máy không hỗ trợ IPv6")
    with s, pytest.raises(RuntimeError, match=BLOCKED):
        s.connect(("2001:db8::1", 443, 0, 0))


def test_only_the_test_database_address_is_allowed_by_default(
    disable_network: set[tuple[Any, ...]],
) -> None:
    db = urlsplit(os.environ["TEST_DATABASE_URL"])
    assert disable_network  # có ít nhất host:port của CSDL test
    assert {port for _host, port in disable_network} == {db.port or 5432}


def test_httpx_sync_request_to_external_ip_never_reaches_the_network() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        httpx.get("http://203.0.113.5/", timeout=1)


# --- DNS: tên miền `.invalid` (RFC 6761) luôn NXDOMAIN, nên test không bao giờ tới máy chủ nào ---

UNLISTED_HOST = "blocked-by-test-guard.invalid"


def test_getaddrinfo_for_an_unlisted_hostname_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.getaddrinfo(UNLISTED_HOST, 443)


def test_gethostbyname_for_an_unlisted_hostname_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.gethostbyname(UNLISTED_HOST)
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.gethostbyname_ex(UNLISTED_HOST)


async def test_loop_getaddrinfo_for_an_unlisted_hostname_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        await asyncio.get_running_loop().getaddrinfo(UNLISTED_HOST, 443)


async def test_httpx_async_request_to_an_unlisted_hostname_is_blocked_before_dns() -> None:
    async with httpx.AsyncClient(timeout=1) as client:
        with expect_blocked():
            await client.get(f"http://{UNLISTED_HOST}/")


@pytest.mark.parametrize("host", ["1.2.3.4%eth0", "127.1.invalid", "LOCALHOST.invalid"])
def test_names_that_only_look_like_ip_or_localhost_are_blocked(host: str) -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.getaddrinfo(host, 80)


def test_uppercase_localhost_resolves_without_dns() -> None:
    assert socket.getaddrinfo("LOCALHOST", 80)


def test_numeric_ip_and_localhost_resolve_without_dns() -> None:
    assert socket.getaddrinfo("127.0.0.1", 80)
    assert socket.getaddrinfo("localhost", 80)
    assert socket.gethostbyname("127.0.0.1") == "127.0.0.1"


def test_database_host_of_test_url_is_not_blocked_by_dns_guard() -> None:
    db = urlsplit(os.environ["TEST_DATABASE_URL"])
    assert socket.getaddrinfo(db.hostname or "localhost", db.port or 5432)


async def test_asyncio_connection_to_disallowed_loopback_port_is_blocked() -> None:
    """Vòng lặp asyncio (httpx.AsyncClient, anyio) cũng phải đi qua chốt chặn.

    Dùng cổng loopback đang đóng để nếu chốt bị vượt qua thì chỉ nhận ConnectionRefused,
    không có gói tin nào rời khỏi máy.
    """
    port = _closed_loopback_port()
    with pytest.raises(RuntimeError, match=BLOCKED):
        await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=1,
        )


async def test_asyncio_connection_to_an_allowed_local_server_still_works(
    disable_network: set[tuple[Any, ...]],
) -> None:
    """Chặn không quá tay: địa chỉ đã thêm vào tập được phép vẫn kết nối và trao đổi dữ liệu."""

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.readline())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    async with server:
        address = server.sockets[0].getsockname()[:2]
        disable_network.add(address)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(*address), timeout=2)
        writer.write("xin chào\n".encode())
        await writer.drain()
        assert await asyncio.wait_for(reader.readline(), timeout=2) == "xin chào\n".encode()
        writer.close()
        await writer.wait_closed()


async def test_httpx_async_request_to_disallowed_loopback_port_is_blocked() -> None:
    port = _closed_loopback_port()
    async with httpx.AsyncClient(timeout=1) as client:
        with expect_blocked():
            await client.get(f"http://127.0.0.1:{port}/")
