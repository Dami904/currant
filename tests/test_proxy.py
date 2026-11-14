from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.proxy import GroundingProxy, check_upstream
from currant.proxy_http import SOCKET_TIMEOUT, WEB, host_allowed, make_server, route
from tests.test_ground import simple

QUESTION = "How many free evaluations do new accounts get?"
AUTH = "Bearer caller-key-123"
OK = {"id": "c1", "choices": [{"finish_reason": "stop", "message": {"content": "50"}}]}


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
        *,
        finish: bool = True,
    ) -> None:
        self.calls: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request) if handler else httpx.Response(200, json=OK)

        world = simple()
        if finish:
            world.finish()
        self.store = world.store
        self.proxy = GroundingProxy(
            self.store,
            extract_run_id=world.extract,
            relate_run_id=world.relate,
            http=httpx.Client(transport=httpx.MockTransport(record)),
            receipts_dir=tmp_path / "receipts",
        )

    def chat(self, body: dict[str, Any] | None = None, auth: str | None = AUTH) -> Any:
        body = body or {"model": "gpt-6-luna", "messages": [{"role": "user", "content": QUESTION}]}
        return route(self.proxy, "POST", "/v1/chat/completions", json.dumps(body).encode(), auth)


# --- the contract --------------------------------------------------------------------------------


def test_a_question_is_grounded_forwarded_under_the_callers_key_and_leaves_a_replayable_receipt(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    reply = rig.chat(
        {
            "model": "gpt-6-luna",
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": QUESTION},
            ],
        }
    )
    assert reply.status == 200 and json.loads(reply.body) == OK  # the upstream reply, unchanged
    (call,) = rig.calls
    assert call.headers["Authorization"] == AUTH and call.url.host == "inference-api.openserv.ai"
    sent = json.loads(call.content)
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "system", "user", "user"] and sent["temperature"] == 0.2
    assert "untrusted" in sent["messages"][0]["content"]  # our prompt first, theirs kept
    assert sent["messages"][1]["content"] == "be brief"
    assert "[SUPERSEDED:" in sent["messages"][2]["content"]  # the documents, grounded
    assert sent["messages"][3]["content"] == QUESTION
    assert sent["tools"] == [{"type": "function", "function": {"name": "serv_prompt_guard"}}]

    rid = reply.headers["X-Currant-Receipt"]
    context = route(rig.proxy, "GET", f"/receipts/{rid}/context", b"", None).body.decode()
    assert hashlib.sha256(context.encode()).hexdigest() == reply.headers["X-Currant-Context-Sha256"]
    assert context == sent["messages"][2]["content"].removeprefix("Documents:\n")
    replayed = json.loads(route(rig.proxy, "GET", f"/receipts/{rid}/replay", b"", None).body)
    assert replayed["ok"] is True
    assert json.loads(route(rig.proxy, "GET", "/receipts", b"", None).body) == [rid]


@pytest.mark.parametrize(
    ("kwargs", "status", "kind"),
    [
        ({"auth": None}, 401, "missing_authorization"),
        (
            {"body": {"messages": [{"role": "user", "content": QUESTION}], "stream": True}},
            400,
            "stream_unsupported",
        ),
        ({"body": {"messages": [{"role": "assistant", "content": "hi"}]}}, 400, "no_question"),
        (
            {"body": {"messages": [{"role": "user", "content": "zebra quantum"}]}},
            503,
            "no_matching_documents",
        ),
    ],
)
def test_a_request_that_cannot_be_grounded_is_refused_and_never_sent_upstream(
    tmp_path: Path, kwargs: dict[str, Any], status: int, kind: str
) -> None:
    rig = Rig(tmp_path)
    reply = rig.chat(**kwargs)
    assert reply.status == status and json.loads(reply.body)["error"]["type"] == kind
    assert rig.calls == []


def test_an_unfinished_run_fails_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path, finish=False)  # the relate run never completed
    reply = rig.chat()
    assert reply.status == 503 and json.loads(reply.body)["error"]["type"] == "grounding_failed"
    assert rig.calls == [] and not (tmp_path / "receipts").exists()


def test_an_upstream_error_passes_through_and_a_timeout_is_unknown_and_not_retried(
    tmp_path: Path,
) -> None:
    failing = Rig(tmp_path / "a", lambda _r: httpx.Response(503, json={"error": "busy"}))
    reply = failing.chat()
    assert reply.status == 503 and json.loads(reply.body) == {"error": "busy"}
    assert "X-Currant-Receipt" in reply.headers  # the question was grounded; the receipt exists

    def slow(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    timing_out = Rig(tmp_path / "b", slow)
    reply = timing_out.chat()
    assert reply.status == 504 and json.loads(reply.body)["error"]["type"] == "upstream_unknown"
    assert len(timing_out.calls) == 1


def test_a_receipt_id_can_never_reach_the_filesystem_as_a_path(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rid = rig.chat().headers["X-Currant-Receipt"]
    for bad in ("../x", "..%2Fx", "a" * 63, rid.upper(), rid + "/..", "x" * 64):
        assert route(rig.proxy, "GET", f"/receipts/{bad}", b"", None).status == 404
    assert route(rig.proxy, "GET", f"/receipts/{rid}/nope", b"", None).status == 404
    assert route(rig.proxy, "GET", f"/receipts/{'0' * 64}", b"", None).status == 404


def test_the_callers_key_is_only_ever_sent_to_https_or_loopback() -> None:
    assert (
        check_upstream("https://inference-api.openserv.ai/v1/")
        == "https://inference-api.openserv.ai/v1"
    )
    assert check_upstream("http://127.0.0.1:9000/v1") == "http://127.0.0.1:9000/v1"
    for bad in ("http://example.com/v1", "ftp://x/v1", "example.com/v1"):
        with pytest.raises(ValueError, match="https"):
            check_upstream(bad)


# --- the viewer ------------------------------------------------------------


def test_the_viewer_cannot_run_or_load_anything_a_receipt_contains(tmp_path: Path) -> None:
    page = route(Rig(tmp_path).proxy, "GET", "/", b"", None)
    csp = page.headers["Content-Security-Policy"]
    assert page.status == 200 and "default-src 'none'" in csp and "'unsafe-inline'" not in csp
    script = (WEB / "viewer.js").read_text(encoding="utf-8")
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in script, f"the viewer uses {unsafe} on untrusted text"
    assert "<script>" not in (WEB / "index.html").read_text(encoding="utf-8")  # no inline script


class FakeConnection:
    """Stands in for a client socket: the suite blocks real connections, even to loopback."""

    def __init__(self, raw: bytes) -> None:
        self.incoming, self.sent = io.BytesIO(raw), io.BytesIO()

    def makefile(self, mode: str, *_a: object, **_k: object) -> io.BytesIO:
        return self.incoming if "r" in mode else self.sent

    def sendall(self, data: bytes) -> None:
        self.sent.write(data)

    def settimeout(self, _seconds: float | None) -> None:
        return None


def serve_once(rig: Rig, raw: bytes) -> tuple[int, bytes]:
    server = make_server(rig.proxy, "127.0.0.1", 0)  # binds, never connects
    try:
        connection = FakeConnection(raw)
        server.RequestHandlerClass(connection, ("127.0.0.1", 1), server)
        head, _, body = connection.sent.getvalue().partition(b"\r\n\r\n")
        return int(head.split(b" ")[1]), body
    finally:
        server.server_close()


def request(method_and_path: str, *headers: str, body: bytes = b"") -> bytes:
    lines = [f"{method_and_path} HTTP/1.1", *headers, "", ""]
    return "\r\n".join(lines).encode() + body


def test_the_server_reads_requests_enforces_limits_and_defaults_to_loopback(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert serve_once(rig, request("GET /healthz")) == (200, b'{"ok": true}')
    body = json.dumps({"messages": [{"role": "user", "content": QUESTION}]}).encode()
    status, reply = serve_once(
        rig,
        request(
            "POST /v1/chat/completions",
            f"Authorization: {AUTH}",
            f"Content-Length: {len(body)}",
            body=body,
        ),
    )
    assert status == 200 and json.loads(reply) == OK
    assert serve_once(rig, request("POST /v1/chat/completions"))[0] == 411
    too_big = request("POST /v1/chat/completions", "Content-Length: 99999999")
    assert serve_once(rig, too_big)[0] == 413
    assert len(rig.calls) == 1  # only the valid request reached the upstream


def test_serve_refuses_a_public_address_without_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "serve",
            "--extract-run",
            "1",
            "--relate-run",
            "2",
            "--host",
            "0.0.0.0",
            "--db",
            str(tmp_path / "x.db"),
        ]
    )
    assert code == 2 and "--allow-remote" in capsys.readouterr().err


# --- hardening found by the reliability audit ----------------------------------------------------


def test_the_callers_own_tools_are_checked_and_the_guard_is_always_ours(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    fake_guard = {"type": "function", "function": {"name": "serv_prompt_guard", "parameters": {}}}
    mine = {"type": "function", "function": {"name": "lookup"}}
    body = {"messages": [{"role": "user", "content": QUESTION}], "tools": [fake_guard, mine]}
    assert rig.chat(body).status == 200
    sent = json.loads(rig.calls[0].content)["tools"]
    assert sent == [mine, {"type": "function", "function": {"name": "serv_prompt_guard"}}]
    for bad in ("lookup", [1], ["x"]):
        reply = rig.chat({"messages": [{"role": "user", "content": QUESTION}], "tools": bad})
        assert reply.status == 400
    assert len(rig.calls) == 1 and len(rig.proxy.receipt_ids()) == 1  # bad requests left no receipt


def test_what_became_of_the_upstream_call_is_recorded_beside_the_receipt(tmp_path: Path) -> None:
    def slow(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    timing_out = Rig(tmp_path / "a", slow)
    rid = timing_out.chat().headers["X-Currant-Receipt"]
    outcome = json.loads((tmp_path / "a" / "receipts" / f"{rid}.upstream.json").read_text())
    assert outcome == {"state": "unknown", "error": "ReadTimeout"}  # UNKNOWN is kept, not dropped
    fine = Rig(tmp_path / "b")
    rid = fine.chat().headers["X-Currant-Receipt"]
    assert (
        json.loads((tmp_path / "b" / "receipts" / f"{rid}.upstream.json").read_text())["state"]
        == "http_200"
    )


def test_an_upstream_reply_can_only_arrive_as_json_and_the_key_is_stored_nowhere(
    tmp_path: Path,
) -> None:
    def html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<script>x</script>", headers={"content-type": "text/html"})

    rig = Rig(tmp_path, html)
    reply = rig.chat()
    assert reply.content_type == "application/json"  # never HTML under this origin
    stored = b"".join(p.read_bytes() for p in (tmp_path / "receipts").iterdir())
    exposed = stored + json.dumps(reply.headers).encode() + reply.body
    assert b"caller-key-123" not in exposed


def test_the_receipt_list_is_capped_and_an_internal_error_is_a_clean_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path)
    for question in (QUESTION, QUESTION + " please", QUESTION + " now"):
        rig.chat({"messages": [{"role": "user", "content": question}]})
    assert len(rig.proxy.receipt_ids()) == 3 and len(rig.proxy.receipt_ids(limit=2)) == 2

    def boom(*_a: object, **_k: object) -> None:
        raise ValueError("a private question leaked here")

    monkeypatch.setattr(GroundingProxy, "chat", boom)
    reply = rig.chat()
    assert reply.status == 500 and b"private question" not in reply.body
    assert json.loads(reply.body)["error"]["type"] == "internal_error"


def test_the_server_refuses_foreign_hosts_bad_lengths_and_stalled_clients(tmp_path: Path) -> None:
    assert [host_allowed(h) for h in ("127.0.0.1:8787", "localhost", "[::1]:80", None)] == [
        True
    ] * 4
    assert not any(host_allowed(h) for h in ("evil.example", "127.0.0.1.evil.example", "10.0.0.1"))
    rig = Rig(tmp_path)
    assert serve_once(rig, request("GET /healthz", "Host: evil.example"))[0] == 403
    assert serve_once(rig, request("GET /healthz", "Host: 127.0.0.1:8787"))[0] == 200
    superscript = request("POST /v1/chat/completions", "Content-Length: X").replace(
        b"X", bytes([0xB2])
    )
    assert serve_once(rig, superscript)[0] == 411  # "²".isdigit() is True, int() would raise

    server = make_server(rig.proxy, "127.0.0.1", 0)
    try:
        handler: Any = server.RequestHandlerClass
        assert handler.timeout == SOCKET_TIMEOUT  # set on every connection

        class Stalled(FakeConnection):
            def __init__(self) -> None:
                super().__init__(request("POST /v1/chat/completions", "Content-Length: 50"))

                class Stream(io.BytesIO):
                    def read(self, size: int | None = -1) -> bytes:
                        raise TimeoutError("the client stopped sending")

                self.incoming = Stream(self.incoming.getvalue())

        connection = Stalled()
        server.RequestHandlerClass(connection, ("127.0.0.1", 1), server)  # returns, no exception
        assert b" 408 " in connection.sent.getvalue().split(b"\r\n")[0] and rig.calls == []
    finally:
        server.server_close()
