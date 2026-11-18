"""The hosted, read-only receipt replay: `currant replay` behind one HTTP endpoint.

`site/api/replay.py` (a Vercel Python function) is a thin adapter over `handle`. A caller posts a
receipt; the server picks the committed example store for the receipt's corpus, opens it
read-only, and runs the same `replay` the CLI runs. It holds no key and cannot write.

Verdicts, the same discipline as the rest of Currant:
- REPLAYED: re-grounding from the store reproduced the receipt exactly.
- FAILED: the receipt is malformed, or replay found a problem (each one is listed).
- UNKNOWN: the server could not decide: no hosted store for this corpus, a store whose bytes no
  longer match their pinned hash, or an unexpected error. Never reported as a pass, and never as
  a failure of the receipt either.

Default-deny on stores: only the files pinned in HOSTED (corpus hash -> file name and SHA-256)
are ever opened, and only after their bytes hash to the pinned value. A receipt cannot name a
path.

Logging: one JSON line per request on stderr, with a request id that the reply also carries, the
first 12 characters of the receipt id (a public hash), the corpus hash and the verdict. The
receipt itself is never logged (it holds the caller's question). Error detail goes to the log,
never into the reply.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import traceback
from pathlib import Path
from typing import Any

from currant import __version__
from currant.obs import JsonLogger
from currant.receipt import REQUIRED_FIELDS, replay
from currant.store import ClaimStore

REPLAY_API_VERSION = "replay-api-v1"
MAX_BODY = 256 * 1024  # the committed receipts are under 5 KB
# corpus_hash -> (file in the store directory, SHA-256 of its bytes). Copies of
# examples/real/store.db and examples/demo/store.db, kept identical by tests/test_replay_api.py.
HOSTED: dict[str, tuple[str, str]] = {
    "df09c0e2aa9b0520ef76631dc3c47b4a23fcb551299fb9c46e3f61ab8908704c": (
        "real.db",
        "d8e5394a42b9d66d93b59718d43bed3784cdb10c6f9e4f05892669d38a9d30eb",
    ),
    "d2f6ed1cb8c7af1a8de429458d0583ee9529fbddc5be521a06d1e89e30876077": (
        "demo.db",
        "a99bf8418e897b7d023cb4dc09e5e835848a1a4f79642581142ee4e3d8742885",
    ),
}


def _log() -> JsonLogger:
    """A logger bound to the current stderr (resolved per call, so a host or test can swap it)."""
    return JsonLogger(run_id="replay-api")


def new_request_id() -> str:
    return secrets.token_hex(8)


def reply(
    request_id: str, status: int, verdict: str, problems: list[str], **extra: Any
) -> tuple[int, bytes]:
    body = {
        "verdict": verdict,
        "problems": problems,
        "request_id": request_id,
        "replay_api": REPLAY_API_VERSION,
        "currant": __version__,
        **extra,
    }
    return status, json.dumps(body, sort_keys=True).encode("utf-8")


def too_large(request_id: str | None = None) -> tuple[int, bytes]:
    """The reply for a body over MAX_BODY, sent without reading the body."""
    rid = request_id or new_request_id()
    _log().info("replay refused", request_id=rid, verdict="FAILED", reason="too large")
    return reply(rid, 413, "FAILED", [f"the receipt is larger than {MAX_BODY} bytes"])


def unexpected(request_id: str, exc: BaseException) -> tuple[int, bytes]:
    """Anything unexpected: UNKNOWN, never a pass; the detail goes to the log only."""
    _log().error(
        "replay did not finish",
        request_id=request_id,
        verdict="UNKNOWN",
        error=f"{type(exc).__name__}: {exc}",
        traceback="".join(traceback.format_exception(exc))[-4000:],
    )
    return reply(request_id, 500, "UNKNOWN", ["the replay did not finish on the server"])


def handle(raw: bytes, store_dir: Path, request_id: str | None = None) -> tuple[int, bytes]:
    """One replay request: the raw POST body in, an HTTP status and a JSON body out."""
    rid = request_id or new_request_id()
    started = time.monotonic()
    if len(raw) > MAX_BODY:
        return too_large(rid)
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):  # RecursionError: deep nesting
        _log().info("replay refused", request_id=rid, verdict="FAILED", reason="not json")
        return reply(rid, 400, "FAILED", ["the body is not JSON"])
    if not isinstance(receipt, dict):
        _log().info("replay refused", request_id=rid, verdict="FAILED", reason="not an object")
        return reply(rid, 400, "FAILED", ["the receipt is not a JSON object"])
    receipt_id = receipt.get("receipt_id")
    short_id = receipt_id[:12] if isinstance(receipt_id, str) else None
    missing = [key for key in REQUIRED_FIELDS if key not in receipt]
    if missing:
        _log().info("replay refused", request_id=rid, receipt=short_id, verdict="FAILED")
        return reply(rid, 200, "FAILED", [f"missing fields: {', '.join(missing)}"])

    corpus = receipt["corpus"]
    corpus_hash = corpus.get("corpus_hash") if isinstance(corpus, dict) else None
    hosted = HOSTED.get(corpus_hash) if isinstance(corpus_hash, str) else None
    if hosted is None:
        _log().info(
            "replay unhosted",
            request_id=rid,
            receipt=short_id,
            corpus_hash=corpus_hash if isinstance(corpus_hash, str) else None,
            verdict="UNKNOWN",
        )
        return reply(
            rid,
            200,
            "UNKNOWN",
            ["no hosted store for this corpus: replay it where its store is, with currant replay"],
        )
    name, pinned = hosted
    store_info = {"name": name, "sha256": pinned}
    try:
        path = store_dir / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != pinned:
            _log().error(
                "hosted store hash mismatch",
                request_id=rid,
                store=name,
                expected=pinned,
                actual=actual,
                verdict="UNKNOWN",
            )
            return reply(
                rid, 200, "UNKNOWN", [f"the hosted store {name} does not match its pinned hash"]
            )
        with ClaimStore.open_readonly(path) as store:
            result = replay(store, receipt)
    except Exception as exc:
        return unexpected(rid, exc)
    verdict = "REPLAYED" if result.ok else "FAILED"
    _log().info(
        "replay",
        request_id=rid,
        receipt=short_id,
        store=name,
        verdict=verdict,
        problems=len(result.problems),
        ms=round((time.monotonic() - started) * 1000),
    )
    return reply(
        rid,
        200,
        verdict,
        list(result.problems),
        context_sha256=result.context_sha256,
        store=store_info,
    )
