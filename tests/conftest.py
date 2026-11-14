"""Test-suite-wide guard: the default test run must never touch the network.

CLAUDE.md says anything needing the network or a live key is a demo path (`live_*`), not a
test. This makes that rule fail loudly instead of living only in prose. HTTP in tests goes
through `httpx.MockTransport`, which never opens a socket.
"""

from __future__ import annotations

import socket
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def _network_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("network access is blocked in tests; use httpx.MockTransport")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
