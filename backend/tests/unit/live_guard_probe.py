"""Chỉ được chạy trong tiến trình con của test_network_guard_m0b.py (`-m live`).

Không đặt tên `test_*.py` nên pytest không tự thu thập; không chạm mạng: chỉ kiểm tra rằng
fixture `disable_network` không vá gì khi test mang dấu `live`.
"""

import socket
from asyncio.proactor_events import BaseProactorEventLoop
from typing import Any

import pytest


@pytest.mark.live
def test_guard_is_not_installed_for_live_tests(disable_network: set[tuple[Any, ...]]) -> None:
    assert disable_network == set()
    assert socket.socket.connect.__name__ == "connect"
    assert socket.socket.connect_ex.__name__ == "connect_ex"
    assert socket.getaddrinfo.__name__ == "getaddrinfo"
    assert socket.gethostbyname.__name__ == "gethostbyname"
    assert "guarded" not in socket.socketpair.__name__
    assert BaseProactorEventLoop.sock_connect.__qualname__ == "BaseProactorEventLoop.sock_connect"
