import socket

import pytest


def test_connecting_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_dns_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.getaddrinfo("example.com", 80)
