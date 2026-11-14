"""The HTTP layer of the grounding proxy: routing (a pure function) and a small server.

Routes:

    POST /v1/chat/completions     the grounded chat call (see currant.proxy for the contract)
    GET  /                        the receipt viewer (static page, script and style)
    GET  /receipts                receipt ids, newest first
    GET  /receipts/<id>           the receipt
    GET  /receipts/<id>/context   the exact text the model was given
    GET  /receipts/<id>/replay    re-ground from the store and compare the context hash
    GET  /healthz
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from currant.proxy import GroundingProxy, Reply, error_reply

MAX_BODY = 1_000_000
SOCKET_TIMEOUT = 10.0
LOOPBACK = ("127.0.0.1", "localhost", "::1")
WEB = Path(__file__).parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
    "/viewer.css": ("viewer.css", "text/css; charset=utf-8"),
}
# Receipts hold crawled text, which is untrusted: the page may load only its own script and style
# and may talk only to this server, so nothing in a receipt can run or phone home.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def host_allowed(header: str | None) -> bool:
    """A Host header naming a loopback address (any port). Absent is allowed: a browser always
    sends one, so a missing header is not a rebinding attack."""
    if header is None:
        return True
    name = header.strip().lower()
    name = name[1 : name.index("]")] if name.startswith("[") and "]" in name else name.split(":")[0]
    return name in LOOPBACK


def route(proxy: GroundingProxy, method: str, path: str, raw: bytes, auth: str | None) -> Reply:
    """Everything the server does, as a function of the request (so it can be tested). Anything
    unexpected becomes a clean 500 (the exception type only, never its text, which may hold a
    question): the caller gets an answer instead of a dropped connection."""
    try:
        return _route(proxy, method, path, raw, auth)
    except Exception as exc:
        return error_reply(
            500, "internal_error", f"{type(exc).__name__} while handling the request"
        )


def _route(proxy: GroundingProxy, method: str, path: str, raw: bytes, auth: str | None) -> Reply:
    if method == "POST":
        if path == "/v1/chat/completions":
            return proxy.chat(raw, auth)
        return error_reply(404, "not_found", "no such route")
    if method != "GET":
        return error_reply(405, "method_not_allowed", "GET or POST only")
    if path in STATIC:
        name, content_type = STATIC[path]
        return Reply(200, (WEB / name).read_bytes(), {"Content-Security-Policy": CSP}, content_type)
    if path == "/healthz":
        return Reply(200, b'{"ok": true}')
    if path == "/receipts":
        return Reply(200, json.dumps(proxy.receipt_ids()).encode("utf-8"))
    parts = path.strip("/").split("/")
    if parts[0] == "receipts" and len(parts) in (2, 3):
        kind = parts[2] if len(parts) == 3 else "receipt"
        if kind in ("receipt", "context", "replay"):
            return proxy.get(parts[1], kind)
    return error_reply(404, "not_found", "no such route")


def make_server(proxy: GroundingProxy, host: str = "127.0.0.1", port: int = 8787) -> HTTPServer:
    """A single-threaded server (the store is not shared across threads). It does not log
    requests, which carry the caller's questions and key."""

    loopback = host in LOOPBACK

    class Handler(BaseHTTPRequestHandler):
        server_version = "currant"
        timeout = SOCKET_TIMEOUT  # a client that stalls mid-request must not hold up everyone else

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _reply(self, reply: Reply) -> None:
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in reply.headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(reply.body)

        def _host_refused(self) -> bool:
            """On a loopback server only loopback names are served, so a web page cannot reach it
            through a DNS name it controls (DNS rebinding)."""
            if loopback and not host_allowed(self.headers.get("Host")):
                self._reply(error_reply(403, "bad_host", "this server answers on loopback only"))
                return True
            return False

        def do_GET(self) -> None:
            if self._host_refused():
                return
            self._reply(route(proxy, "GET", self.path.split("?")[0], b"", None))

        def do_POST(self) -> None:
            if self._host_refused():
                return
            length = self.headers.get("Content-Length")
            if length is None or not (length.isascii() and length.isdigit()):
                self._reply(error_reply(411, "length_required", "send a Content-Length"))
                return
            if int(length) > MAX_BODY:
                self._reply(error_reply(413, "too_large", f"the body is over {MAX_BODY} bytes"))
                return
            try:
                raw = self.rfile.read(int(length))
            except TimeoutError:
                self._reply(error_reply(408, "request_timeout", "the request body did not arrive"))
                return
            path = self.path.split("?")[0]
            self._reply(route(proxy, "POST", path, raw, self.headers.get("Authorization")))

    return HTTPServer((host, port), Handler)
