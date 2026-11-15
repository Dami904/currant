"""Test-suite-wide guard: the default test run must never touch the network.

CLAUDE.md says anything needing the network or a live key is a demo path (`live_*`), not a
test. This makes that rule fail loudly instead of living only in prose. HTTP in tests goes
through `httpx.MockTransport`, which never opens a socket.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import NoReturn

import pytest

# How many tests this run collected, and from which files: lets test_readme_count compare the
# README's stated count with the real one, but only on a run of the whole suite.
COLLECTED = pytest.StashKey[tuple[int, frozenset[Path]]]()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    config.stash[COLLECTED] = (len(items), frozenset(item.path for item in items))


@pytest.fixture(autouse=True)
def _network_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("network access is blocked in tests; use httpx.MockTransport")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
