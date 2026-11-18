"""A cache in front of a chat model, keyed by the exact request.

Why: the evaluation re-runs the same extraction on the same pages many times (one real page is
used by several items, and every tuning round reruns everything). A cache makes a rerun free,
makes an interrupted run resumable, and keeps the raw model output next to the request that
produced it. The key covers everything that can change the answer: model, prompts, schema, guard,
shadow hint and output budget. Change the prompt and the key changes, so nothing stale is served.

The cache stores model OUTPUT only. It never sees an API key (the wrapped client holds that), and
a guard block is cached like any other reply, so it is not retried against the live service.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from currant.obs import utc_now
from currant.serv import ModelError, ModelReply

_DDL = """
CREATE TABLE IF NOT EXISTS replies (
    cache_key         TEXT PRIMARY KEY,
    model             TEXT NOT NULL,
    content           TEXT,
    finish_reason     TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER NOT NULL,
    request_id        TEXT
) WITHOUT ROWID;
"""


def cache_key(
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    schema_name: str,
    guard: bool,
    shadow_hint: str | None,
    max_completion_tokens: int | None,
) -> str:
    payload = json.dumps(
        [model, system, user, schema, schema_name, guard, shadow_hint, max_completion_tokens],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def json_object_reply(reply: ModelReply) -> bool:
    """True if the reply is a JSON object, which is what every Currant prompt asks for."""
    try:
        return isinstance(json.loads(reply.content or ""), dict)
    except ValueError:
        return False


def _worth_keeping(reply: ModelReply, accept: Callable[[ModelReply], bool] | None) -> bool:
    """Keep only final replies: a guard block (deterministic), or a normal completion with text
    that the caller can use. Truncated (`length`), empty, odd or unusable replies are never
    remembered, so a rerun gets another try."""
    if reply.finish_reason == "content_filter":
        return True
    if reply.finish_reason != "stop" or not (reply.content and reply.content.strip()):
        return False
    return accept is None or accept(reply)


class CachingModel:
    """Wraps any chat model (anything with `.model` and `.complete(...)`)."""

    def __init__(
        self,
        inner: Any,
        path: Path | str,
        *,
        accept: Callable[[ModelReply], bool] | None = None,
        raw_log: Path | None = None,
    ) -> None:
        self._inner = inner
        self._accept = accept
        self._raw_log = raw_log
        self.log_errors = 0  # raw-log writes that failed; the run still goes on
        if raw_log is not None:
            raw_log.parent.mkdir(parents=True, exist_ok=True)  # cannot: refuse to start
            self._repair_tail(raw_log)
        self.model: str = inner.model
        # What the key names besides the request: the model, or a graph client's fuller tag.
        self._tag: str = getattr(inner, "cache_tag", inner.model)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_DDL)
        self.hits = 0
        self.misses = 0

    def complete(
        self,
        system: str,
        user: str,
        *,
        schema: dict[str, Any],
        schema_name: str,
        guard: bool,
        shadow_hint: str | None = None,
        max_completion_tokens: int | None = None,
    ) -> ModelReply:
        key = cache_key(
            self._tag, system, user, schema, schema_name, guard, shadow_hint, max_completion_tokens
        )
        row = self._db.execute("SELECT * FROM replies WHERE cache_key = ?", (key,)).fetchone()
        if row is not None:
            cached = ModelReply(
                row["content"], row["finish_reason"], row["prompt_tokens"],
                row["completion_tokens"], row["latency_ms"], row["request_id"],
            )  # fmt: skip
            if _worth_keeping(cached, self._accept):
                self.hits += 1
                self._record(key, "cache", cached, kept=True)
                return cached
            # Written before the caller's check existed, and it would be rejected today:
            # never serve it again.
            with self._db:
                self._db.execute("DELETE FROM replies WHERE cache_key = ?", (key,))
        try:
            reply: ModelReply = self._inner.complete(
                system,
                user,
                schema=schema,
                schema_name=schema_name,
                guard=guard,
                shadow_hint=shadow_hint,
                max_completion_tokens=max_completion_tokens,
            )
        except ModelError as exc:
            self._write(
                {
                    "cache_key": key, "source": "model", "cached": False, "error": str(exc),
                    "transient": exc.transient, "request_id": exc.request_id,
                }
            )  # fmt: skip
            raise
        self.misses += 1
        keep = _worth_keeping(reply, self._accept)
        if keep:  # store the paid reply FIRST: a failing log must never cost it
            with self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO replies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, self.model, reply.content, reply.finish_reason,
                     reply.prompt_tokens, reply.completion_tokens, reply.latency_ms,
                     reply.request_id),
                )  # fmt: skip
        self._record(key, "model", reply, kept=keep)
        return reply  # (an unkept reply is a truncated, empty or unusable one: retry later)

    def _record(self, key: str, source: str, reply: ModelReply, *, kept: bool) -> None:
        self._write(
            {
                "cache_key": key, "source": source, "cached": kept,
                "request_id": reply.request_id, "finish_reason": reply.finish_reason,
                "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
                "latency_ms": reply.latency_ms, "content": reply.content,
                **({"screen_request_id": reply.screen_request_id}
                   if reply.screen_request_id else {}),
            }
        )  # fmt: skip

    def _write(self, record: dict[str, Any]) -> None:
        """Append one line per model call (hit, miss or error) to the raw log, if there is one.
        This is the audit trail of what the model said; the cache is only a cost saver."""
        if self._raw_log is None:
            return
        try:
            line = json.dumps({"ts": utc_now().isoformat(), **record}, ensure_ascii=False)
            with self._raw_log.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError:
            # A full or locked disk must not cost a paid reply or replace the real error.
            # The count is surfaced at the end of the run.
            self.log_errors += 1

    def _repair_tail(self, path: Path) -> None:
        """Drop a half-written last line (a crash mid-write) so the next record starts clean."""
        try:
            if path.exists():
                data = path.read_bytes()
                if data and not data.endswith(b"\n"):
                    with path.open("r+b") as handle:
                        handle.truncate(data.rfind(b"\n") + 1)
        except OSError:
            self.log_errors += 1

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> CachingModel:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
