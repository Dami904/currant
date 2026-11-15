"""Command line entry point (`currant --help` lists every command).

One module per command group: `corpus` (crawl, verify, secrets), `pipeline` (extract, relate,
ground, replay, serve), `evaluation` (the sealed item set), `real` (real items and the drift
report) and `reppo` (the audit). `app.main` dispatches. This package is the only place outside
`live_*` scripts that may build an HTTP client (see `currant.guardrails`).
"""

from __future__ import annotations

import httpx

from currant.cli.app import _tolerate_console_encoding, main

__all__ = ["_tolerate_console_encoding", "httpx", "main"]
