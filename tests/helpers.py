"""Shared test helpers. No test in this repo touches the network."""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from currant.obs import JsonLogger

Handler = Callable[[httpx.Request], httpx.Response]

FIXED_NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)


def fixed_now() -> datetime:
    return FIXED_NOW


def make_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def quiet_logger() -> JsonLogger:
    return JsonLogger(run_id="test", stream=io.StringIO(), now=fixed_now)


def md(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=body.encode(), headers={"content-type": "text/markdown"})
