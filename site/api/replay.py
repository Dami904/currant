"""Vercel Python function: POST /api/replay. A thin adapter over `currant.replay_api.handle`.

Currant itself is installed from GitHub at the commit pinned in site/requirements.txt, so the
code this endpoint runs is public and named (`scripts/check_replay_pin.py` checks the pin is
current). The stores it replays against are the files in `_stores/`, byte-identical copies of the
committed example stores, each checked against its pinned SHA-256 before it is opened read-only.
See docs/THREAT_MODEL.md and docs/DEPLOYING.md.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from pathlib import Path

from currant.replay_api import MAX_BODY, handle, new_request_id, reply, too_large, unexpected

STORE_DIR = Path(__file__).resolve().parent / "_stores"


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        rid = new_request_id()
        declared = self.headers.get("Content-Length")
        try:
            if declared is None:
                # A chunked or length-less body would otherwise read as empty: say so instead.
                status, body = reply(rid, 411, "FAILED", ["send the receipt with a Content-Length"])
            elif not declared.isdigit() or int(declared) > MAX_BODY:
                status, body = too_large(rid)  # refused before the body is touched
            else:
                status, body = handle(self.rfile.read(int(declared)), STORE_DIR, rid)
        except Exception as exc:  # the reply is always JSON, and the failure is logged
            status, body = unexpected(rid, exc)
        self._send(status, body)

    def do_GET(self) -> None:
        self._send(*reply(new_request_id(), 405, "FAILED", ["POST a receipt as JSON"]))

    def log_message(self, format: str, *args: object) -> None:
        return None  # request lines are not logged; handle() logs one line per request
