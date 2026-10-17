"""Ca biên của fixture chặn mạng: nó phải chặn thật, kể cả với asyncio và cổng lạ."""

import asyncio
import os
import socket
import sys
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

BLOCKED = "network bị chặn"

# Trên Windows asyncio mặc định dùng ProactorEventLoop, kết nối bằng ConnectEx chứ không gọi
# socket.connect nên fixture `disable_network` không chặn được (xem báo cáo QA M0).
# strict: khi sửa conftest, test XPASS sẽ báo để gỡ dấu xfail. Trên Linux/CI phải xanh thật.
_WINDOWS_ASYNC_GAP = pytest.mark.xfail(
    sys.platform == "win32",
    strict=True,
    reason="disable_network không chặn kết nối asyncio (ProactorEventLoop) trên Windows",
)


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


@_WINDOWS_ASYNC_GAP
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


@_WINDOWS_ASYNC_GAP
async def test_httpx_async_request_to_disallowed_loopback_port_is_blocked() -> None:
    port = _closed_loopback_port()
    async with httpx.AsyncClient(timeout=1) as client:
        with pytest.raises(RuntimeError, match=BLOCKED):
            await client.get(f"http://127.0.0.1:{port}/")
