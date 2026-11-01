import socket

import pytest


def test_external_connection_is_blocked() -> None:
    with socket.socket() as s, pytest.raises(RuntimeError, match="network bị chặn"):
        s.connect(("93.184.216.34", 80))


def test_allowed_address_passes_the_guard(disable_network: set[tuple[object, ...]]) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        address = server.getsockname()[:2]
        disable_network.add(address)
        with socket.socket() as client:
            client.connect(address)


@pytest.mark.live
def test_live_marker_is_not_blocked(disable_network: set[tuple[object, ...]]) -> None:
    # Chỉ chạy khi `-m live`; khẳng định fixture bỏ qua việc chặn.
    assert disable_network == set()
