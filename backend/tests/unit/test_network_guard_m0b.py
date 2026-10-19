"""QA M0 lần hai: lỗ hổng còn lại của fixture `disable_network` (T0.6).

Chỉ dùng tên `.invalid` (RFC 6761), cổng loopback đang đóng và 203.0.113.0/24 (TEST-NET-3).
Các test `xfail(strict=True)` tái hiện chỗ chốt chặn còn hở; khi vá `conftest.py`, XPASS sẽ
báo để bỏ dấu xfail.
"""

import asyncio
import inspect
import socket
import ssl
import subprocess
import sys
import urllib.request
from asyncio.proactor_events import BaseProactorEventLoop
from pathlib import Path
from typing import Any

import pytest

BLOCKED = "network bị chặn"
UNLISTED_HOST = "qa-m0b-unlisted.invalid"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _closed_loopback_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# --- Lỗ hổng: UDP không đi qua connect ---


def test_udp_sendto_to_a_disallowed_address_is_blocked() -> None:
    port = _closed_loopback_port(socket.SOCK_DGRAM)
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        pytest.raises(RuntimeError, match=BLOCKED),
    ):
        udp.sendto(b"x", ("127.0.0.1", port))


async def test_asyncio_udp_sock_sendto_to_a_disallowed_address_is_blocked() -> None:
    port = _closed_loopback_port(socket.SOCK_DGRAM)
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        pytest.raises(RuntimeError, match=BLOCKED),
    ):
        udp.setblocking(False)
        await asyncio.get_running_loop().sock_sendto(udp, b"x", ("127.0.0.1", port))


# --- Lỗ hổng: tra cứu tên ngược / getfqdn vẫn gửi truy vấn DNS ---


@pytest.mark.parametrize("lookup", ["gethostbyaddr", "getfqdn"])
def test_hostname_lookup_through_gethostbyaddr_or_getfqdn_is_blocked(lookup: str) -> None:
    # Tra hàm lúc chạy: tham chiếu lấy lúc thu thập test là hàm gốc, chưa bị vá bởi fixture.
    with pytest.raises(RuntimeError, match=BLOCKED):
        getattr(socket, lookup)(UNLISTED_HOST)


def test_reverse_lookup_of_a_public_ip_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.getnameinfo(("8.8.8.8", 53), 0)
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.gethostbyaddr("8.8.8.8")


# --- Đường đi đã được chặn, nhưng chưa có test ---


def test_ssl_wrapped_socket_to_an_unlisted_hostname_is_blocked_before_any_handshake() -> None:
    context = ssl.create_default_context()
    tls = context.wrap_socket(socket.socket(), server_hostname=UNLISTED_HOST)
    with tls, pytest.raises(RuntimeError, match=BLOCKED):
        tls.connect((UNLISTED_HOST, 443))


def test_create_connection_to_an_unlisted_hostname_is_blocked_at_dns() -> None:
    with pytest.raises(RuntimeError, match=f"{BLOCKED} trong test: DNS {UNLISTED_HOST}"):
        socket.create_connection((UNLISTED_HOST, 443), timeout=1)


def test_urllib_request_to_an_unlisted_hostname_is_not_turned_into_a_url_error() -> None:
    # urllib chỉ bắt OSError; lỗi chặn mạng phải tới tay test chứ không bị nuốt.
    with pytest.raises(RuntimeError, match=BLOCKED):
        urllib.request.urlopen(f"http://{UNLISTED_HOST}/", timeout=1)  # noqa: S310


async def test_asyncio_open_connection_to_an_unlisted_hostname_is_blocked_at_dns() -> None:
    with pytest.raises(RuntimeError, match=f"{BLOCKED} trong test: DNS {UNLISTED_HOST}"):
        await asyncio.wait_for(asyncio.open_connection(UNLISTED_HOST, 80), timeout=1)


async def test_asyncio_tls_connection_to_an_unlisted_hostname_is_blocked_at_dns() -> None:
    loop = asyncio.get_running_loop()
    with pytest.raises(RuntimeError, match=f"{BLOCKED} trong test: DNS {UNLISTED_HOST}"):
        await loop.create_connection(asyncio.Protocol, UNLISTED_HOST, 443, ssl=True)


async def test_asyncio_datagram_endpoint_with_a_remote_address_is_blocked() -> None:
    loop = asyncio.get_running_loop()
    port = _closed_loopback_port(socket.SOCK_DGRAM)
    with pytest.raises(RuntimeError, match=BLOCKED):
        await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=("127.0.0.1", port)
        )
    with pytest.raises(RuntimeError, match=f"{BLOCKED} trong test: DNS {UNLISTED_HOST}"):
        await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=(UNLISTED_HOST, 53)
        )


async def test_asyncio_sock_connect_with_a_hostname_tuple_is_blocked() -> None:
    loop = asyncio.get_running_loop()
    with socket.socket() as sock:
        sock.setblocking(False)
        with pytest.raises(RuntimeError, match=BLOCKED):
            await loop.sock_connect(sock, (UNLISTED_HOST, 80))


# --- Không chặn nhầm ---


def test_socketpair_and_event_loop_creation_still_work_under_the_guard() -> None:
    left, right = socket.socketpair()
    with left, right:
        left.sendall("xin chào".encode())
        assert right.recv(64).decode() == "xin chào"
    loop = asyncio.new_event_loop()  # tự tạo socketpair nội bộ (self-pipe)
    loop.close()


def test_guard_is_active_again_right_after_a_socketpair() -> None:
    socket.socketpair()[0].close()
    with socket.socket() as sock, pytest.raises(RuntimeError, match=BLOCKED):
        sock.connect(("203.0.113.5", 443))


def test_unconnected_socket_and_bind_do_not_trigger_the_guard() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        assert sock.getsockname()[0] == "127.0.0.1"


def test_host_added_to_the_allowed_set_passes_the_dns_guard(
    disable_network: set[tuple[Any, ...]],
) -> None:
    # Qua chốt chặn thì tới DNS thật của `.invalid` (NXDOMAIN) -> gaierror, không phải RuntimeError.
    host = "qa-m0b-allowed.invalid"
    disable_network.add((host, 8100))
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo(host, 8100)


# --- Rò rỉ trạng thái giữa các test ---

_LEAK_ADDRESS = ("127.0.0.1", 65001)


def test_address_added_by_one_test_is_visible_to_that_test(
    disable_network: set[tuple[Any, ...]],
) -> None:
    disable_network.add(_LEAK_ADDRESS)
    assert _LEAK_ADDRESS in disable_network


def test_address_added_by_the_previous_test_does_not_leak_into_the_next(
    disable_network: set[tuple[Any, ...]],
) -> None:
    assert _LEAK_ADDRESS not in disable_network


def test_patches_are_not_stacked_on_top_of_the_previous_tests_patches() -> None:
    """Mỗi test dựng chốt chặn mới trên hàm gốc; chồng lên chốt cũ nghĩa là teardown thiếu."""
    wrappers: dict[str, tuple[Any, str]] = {
        "socket.socket.connect": (socket.socket.connect, "real_connect"),
        "socket.socketpair": (socket.socketpair, "real_socketpair"),
        "socket.getaddrinfo": (socket.getaddrinfo, "real_getaddrinfo"),
        "socket.gethostbyname": (socket.gethostbyname, "real_gethostbyname"),
        "socket.gethostbyname_ex": (socket.gethostbyname_ex, "real_gethostbyname_ex"),
        "BaseProactorEventLoop.sock_connect": (
            BaseProactorEventLoop.sock_connect,
            "real_sock_connect",
        ),
    }
    for name, (function, original_name) in wrappers.items():
        original = inspect.getclosurevars(function).nonlocals[original_name]
        assert "guarded" not in original.__name__, f"{name} đang bọc chốt chặn của test trước"


# --- Test live không bị chặn (chạy trong tiến trình con vì mặc định `-m "not live"`) ---


def test_live_marked_test_runs_with_the_guard_switched_off() -> None:
    probe = Path(__file__).with_name("live_guard_probe.py")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-m", "live", "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
