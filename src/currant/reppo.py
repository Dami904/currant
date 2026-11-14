"""Reppo Evaluation API client (API key) and the ledger that makes it safe to retry.

Measured behaviour (docs/API_NOTES.md; the API changed between 2026-11-05 and 2026-11-11, so this
module targets the NEW endpoints, observed live on 2026-11-11):

* `POST /agents/evals` with `{taskType, input}` returns 201 with an `id` and status `QUEUED`; the
  old `/agents/eval-requests/...` endpoints are gone (404). `GET /agents/evals/{id}` reads it;
* an evaluation goes QUEUED, PROCESSING, COMPLETED (56 s measured) or FAILED (not charged); a
  completed one costs 440 credits and carries a score 0 to 100, a decision (accept or reject), a
  route (ship, review or block), a confidence and per-dimension rubric scores;
* there is no idempotency key, and everything submitted is PUBLIC;
* so a submit that times out or fails with a 5xx is UNKNOWN: the evaluation may exist. Resubmitting
  could spend twice. A read is idempotent and is retried.

The ledger is what makes the submit safe: an intent is written (and synced to disk) BEFORE the
request, so a crash or timeout can never be mistaken for "nothing was sent". An unresolved intent
blocks every later submit until a person says what happened (`resolve`).

Only public text is sent. Text that looks like a key, or contains the key in use, is refused.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from currant.config import Secret
from currant.guardrails import SECRET_SHAPES

REPPO_BASE = "https://eval.reppo.xyz/api/v1"
TASK_TYPES = ("claim", "response", "action")
DECISIONS = ("accept", "reject")
ROUTES = ("ship", "review", "block")
PENDING_STATUSES = ("QUEUED", "PROCESSING")
MAX_INPUT_BYTES = 50 * 1024
CREDITS_PER_EVALUATION = 440  # agents.md, the console, and the measured creditsCharged


class ReppoError(RuntimeError):
    """Base class: every failure here is one of the subclasses below."""


class InvalidSubmission(ReppoError):
    """Refused before anything was sent (a limit, a bad value, or text that must not be public)."""


class Rejected(ReppoError):
    """Reppo refused the request, so no evaluation exists: bad request, bad key, or no credits."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"http {status}: {message}")
        self.status = status


class SubmitUnknown(ReppoError):
    """The submit may or may not have created an evaluation. Never resubmit blindly."""


class UnresolvedSubmission(ReppoError):
    """An earlier submit is unresolved, so a new one could spend twice. Resolve it first."""


class LedgerWriteError(ReppoError):
    """The submit worked but the ledger could not record it; the message carries the id."""


class ReadFailed(ReppoError):
    """A read failed (after retries, or permanently such as an unknown id)."""


# --- what a completed evaluation says -------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    score: float
    decision: str  # accept | reject, at Reppo's policy threshold
    route: str  # ship | review | block: what Reppo recommends doing with the response
    confidence: str
    reason: str | None
    rubric: tuple[tuple[str, float], ...]  # per-dimension scores, for example factual_accuracy
    evaluators: int | None

    @property
    def needs_revision(self) -> bool:
        """`review`: neither good enough to ship nor bad enough to block. The loop retries only
        these; `ship` and `block` are final."""
        return self.route == "review"


@dataclass(frozen=True)
class Evaluation:
    eval_id: str
    status: str  # QUEUED | PROCESSING | COMPLETED | FAILED | anything else Reppo adds, kept as is
    credits_charged: int | None
    completed_at: str | None
    verdict: Verdict | None
    problem: str | None = None  # a completed evaluation whose verdict could not be read

    @property
    def pending(self) -> bool:
        return self.status in PENDING_STATUSES

    @property
    def failed(self) -> bool:
        return self.status == "FAILED"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def parse_verdict(data: Any) -> Verdict | str:
    """The verdict from an evaluation body, or a reason it cannot be trusted. A malformed verdict
    never becomes an accept or a ship."""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return "no result object"
    score = _number(result.get("score"))
    if score is None or not 0 <= score <= 100:
        return f"score {result.get('score')!r} is not a number from 0 to 100"
    decision, route = result.get("decision"), result.get("route")
    if decision not in DECISIONS:
        return f"unknown decision {decision!r}"
    if route not in ROUTES:
        return f"unknown route {route!r}"
    confidence, reason = result.get("confidence"), result.get("reason")
    rubric = result.get("rubric_scores")
    scores = (
        tuple(
            (str(name), value)
            for name, raw in sorted(rubric.items())
            if (value := _number(raw)) is not None
        )
        if isinstance(rubric, dict)
        else ()
    )
    consensus = result.get("consensus")
    evaluators = consensus.get("evaluators") if isinstance(consensus, dict) else None
    return Verdict(
        score,
        str(decision),
        str(route),
        confidence if isinstance(confidence, str) else "unknown",
        reason if isinstance(reason, str) else None,
        scores,
        len(evaluators) if isinstance(evaluators, list) else None,
    )


def parse_evaluation(data: Any, requested_id: str) -> Evaluation:
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise ReadFailed("unreadable evaluation: no status")
    verdict: Verdict | None = None
    problem: str | None = None
    if data["status"] == "COMPLETED":
        parsed = parse_verdict(data)
        if isinstance(parsed, str):
            problem = parsed
        else:
            verdict = parsed
    charged = data.get("creditsCharged")
    return Evaluation(
        str(data.get("id") or requested_id),
        data["status"],
        charged if isinstance(charged, int) and not isinstance(charged, bool) else None,
        data.get("completedAt") if isinstance(data.get("completedAt"), str) else None,
        verdict,
        problem,
    )


# --- what may be sent -----------------------------------------------------------------------------


def submission_key(task_type: str, text: str) -> str:
    """Our own idempotency key: the same submission always has the same key."""
    canonical = json.dumps([task_type, text], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_submission(task_type: str, text: str, secret: Secret | None = None) -> None:
    """Raise `InvalidSubmission` unless this may be sent. Everything sent is public."""
    if task_type not in TASK_TYPES:
        raise InvalidSubmission(f"taskType must be one of {', '.join(TASK_TYPES)}")
    if not text.strip():
        raise InvalidSubmission("input is empty")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise InvalidSubmission(f"input is over {MAX_INPUT_BYTES} bytes")
    for candidate in (text, _plain(text)):
        for name, shape in SECRET_SHAPES.items():
            if shape.search(candidate):
                raise InvalidSubmission(f"text contains a {name}; submissions are public")
        if secret is not None and secret.reveal() and secret.reveal() in candidate:
            raise InvalidSubmission("text contains the API key in use; submissions are public")


def _plain(text: str) -> str:
    """The text as a reader sees it: compatibility forms folded (full-width letters) and invisible
    format characters (zero-width joiners and spaces) removed. Best effort, not a guarantee."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


# Measured shape: a cuid such as `cmwc1px5w000208l1go59so28` (docs/API_NOTES.md). The pattern is
# looser on purpose, so a real id in another shape is not mistaken for garbage, but it can never
# contain a path separator.
EVAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")


def check_eval_id(eval_id: str) -> str:
    if not EVAL_ID.fullmatch(eval_id):
        raise ReppoError(f"{eval_id!r} is not an evaluation id (letters, digits and . _ : - only)")
    return eval_id


# --- the ledger -----------------------------------------------------------------------------------


def repair_jsonl_tail(path: Path) -> None:
    """A crash mid-append can leave a last line without its newline. A complete record gets its
    newline; a torn fragment is cut off so the next record starts on a clean line. (In the ledger a
    torn INTENT means the request was never sent, and a torn outcome leaves the earlier intact
    intent unresolved, which is the safe reading: the request may have been sent.)"""
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    cut = data.rfind(b"\n") + 1
    try:
        json.loads(data[cut:])
    except ValueError:
        path.write_bytes(data[:cut])
    else:
        path.write_bytes(data + b"\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """The records of a JSON-lines file. A torn last line (no newline, not valid JSON) is a crash
    in the middle of an append and is skipped; a bad line anywhere else is an error."""
    if not path.exists():
        return []
    data = path.read_bytes().decode("utf-8")
    lines = data.splitlines()
    torn_last = bool(data) and not data.endswith("\n")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            if torn_last and number == len(lines):
                break
            raise ReppoError(f"{path} line {number} is unreadable: {exc}") from exc
        rows.append(row)
    return rows


@dataclass
class LedgerState:
    eval_id: str | None = None
    status: str = "intent"  # intent | submitted | rejected | failed | resolved_none
    reason: str | None = None


class ReppoLedger:
    """Append-only JSON lines. An intent is on disk before its request is made."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _append(self, record: dict[str, Any]) -> None:
        record = {"at": datetime.now(UTC).replace(microsecond=0).isoformat(), **record}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        repair_jsonl_tail(self.path)
        with self.path.open("ab") as handle:
            handle.write((json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Held for a whole submit (check, intent, request, outcome), so two processes cannot both
        pass the check. The OS drops the lock if the process dies, so nothing is left stuck."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.with_name(self.path.name + ".lock").open("a+b")
        try:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ReppoError(
                    "another process is submitting to this ledger right now; try again when it ends"
                ) from exc
            yield
        finally:
            handle.close()  # closing releases the lock

    def states(self) -> dict[str, LedgerState]:
        states: dict[str, LedgerState] = {}
        for row in read_jsonl(self.path):
            try:
                key, event = row["key"], row["event"]
            except KeyError as exc:
                raise ReppoError(f"{self.path} has a record with no {exc}") from exc
            state = states.setdefault(key, LedgerState())
            if event == "submitted":
                state.status, state.eval_id = "submitted", row.get("eval_id")
            elif event == "failed":
                # Reppo reports a FAILED evaluation as not charged, so the same text may be sent
                # again. Only a submission that was recorded can fail.
                if state.status == "submitted":
                    state.status, state.reason = "failed", row.get("reason")
            elif event == "rejected":
                # Only an unresolved attempt can be rejected: a 4xx for a later attempt must never
                # undo a submission that did succeed.
                if state.status == "intent":
                    state.status, state.reason = "rejected", row.get("reason")
            elif event == "resolved":
                if state.status == "intent":
                    state.eval_id = row.get("eval_id")
                    state.status = "submitted" if state.eval_id else "resolved_none"
            elif event == "intent" and state.status != "submitted":
                state.status, state.eval_id = "intent", None
        return states

    def intent(self, key: str, summary: dict[str, Any]) -> None:
        self._append({"event": "intent", "key": key, **summary})

    def submitted(self, key: str, eval_id: str) -> None:
        self._append({"event": "submitted", "key": key, "eval_id": eval_id})

    def rejected(self, key: str, reason: str) -> None:
        self._append({"event": "rejected", "key": key, "reason": reason})

    def failed(self, key: str, reason: str) -> None:
        self._append({"event": "failed", "key": key, "reason": reason})

    def resolve(self, key: str, eval_id: str | None) -> None:
        """A person checked the console: `eval_id` if the evaluation exists, None if it does not."""
        with self.lock():  # not while a submit is in flight
            known = self.states().get(key)
            if known is None:
                raise ReppoError(
                    f"no submission has the key {key[:12]}; see `currant reppo-status`"
                )
            if known.status != "intent":
                raise ReppoError(f"submission {key[:12]} is not unresolved")
            if eval_id is not None:
                check_eval_id(eval_id)
            self._append({"event": "resolved", "key": key, "eval_id": eval_id})

    def unresolved(self) -> list[str]:
        return [k for k, s in self.states().items() if s.status == "intent"]


# --- the client -----------------------------------------------------------------------------------


@dataclass
class ReppoClient:
    http: httpx.Client
    api_key: Secret
    base_url: str = REPPO_BASE
    log: Callable[[str, dict[str, Any]], None] = field(default=lambda _kind, _data: None)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key.reveal()}",
            "Content-Type": "application/json",
        }

    def _scrub(self, text: str) -> str:
        secret = self.api_key.reveal()
        return (text.replace(secret, "<redacted>") if secret else text)[:300]

    def submit(self, ledger: ReppoLedger, *, text: str, task_type: str = "response") -> str:
        """Submit once. Returns the evaluation id (the existing one if this exact submission was
        already made and did not fail). Never sends a second request for a submission whose first
        outcome is unknown."""
        check_submission(task_type, text, self.api_key)
        key = submission_key(task_type, text)
        with ledger.lock():
            return self._submit_locked(ledger, key, task_type, text)

    def _submit_locked(self, ledger: ReppoLedger, key: str, task_type: str, text: str) -> str:
        states = ledger.states()
        known = states.get(key)
        if known is not None and known.status == "submitted" and known.eval_id:
            return known.eval_id
        blockers = [k for k, s in states.items() if s.status == "intent"]
        if blockers:
            raise UnresolvedSubmission(
                f"submission {blockers[0][:12]} may exist at Reppo (its outcome is unknown). Check "
                "the console's My evaluations, then run `currant reppo-resolve`."
            )
        body = {"taskType": task_type, "input": text}
        try:
            ledger.intent(
                key,
                {"task_type": task_type, "input_sha256": hashlib.sha256(text.encode()).hexdigest()},
            )
        except OSError as exc:
            raise ReppoError(f"could not record the intent, so nothing was sent: {exc}") from exc
        try:
            response = self.http.post(
                f"{self.base_url}/agents/evals", headers=self._headers(), json=body
            )
        except httpx.RequestError as exc:
            self.log("submit_unknown", {"key": key, "error": type(exc).__name__})
            raise SubmitUnknown(
                f"{type(exc).__name__}: the request may have arrived; the intent stays unresolved"
            ) from exc
        status = response.status_code
        if status == 201:
            return self._record(ledger, key, response)
        if status in (400, 401, 402):
            reason = self._scrub(response.text)
            self.log("submit_refused", {"key": key, "http_status": status})
            ledger.rejected(key, f"http {status}")
            raise Rejected(status, reason)
        # 5xx (a 502 is documented as "not queued, not charged", but that is unmeasured), 429, or
        # anything unexpected: the evaluation may exist. Keep the intent unresolved.
        self.log("submit_unknown", {"key": key, "http_status": status})
        raise SubmitUnknown(f"http {status}: the evaluation may exist; the intent stays unresolved")

    def _record(self, ledger: ReppoLedger, key: str, response: httpx.Response) -> str:
        try:
            eval_id = response.json()["id"]
        except (ValueError, KeyError, TypeError) as exc:
            self.log("submit_unreadable", {"key": key, "body": self._scrub(response.text)})
            raise SubmitUnknown("a 201 with no readable id; the intent stays unresolved") from exc
        if not isinstance(eval_id, str) or not EVAL_ID.fullmatch(eval_id):
            self.log("submit_unreadable", {"key": key, "body": self._scrub(response.text)})
            raise SubmitUnknown("a 201 with no readable id; the intent stays unresolved")
        try:
            ledger.submitted(key, eval_id)
        except OSError as exc:
            self.log("ledger_write_failed", {"key": key, "eval_id": eval_id})
            raise LedgerWriteError(
                f"submitted, but the ledger could not record it. Keep this id: {eval_id}"
            ) from exc
        return eval_id

    def read(
        self, eval_id: str, *, retries: int = 3, sleep: Callable[[float], None] = time.sleep
    ) -> Evaluation:
        """Read one evaluation. A read changes nothing, so a transient failure is retried."""
        check_eval_id(eval_id)
        last = "no attempt made"
        for attempt in range(1, retries + 1):
            try:
                response = self.http.get(
                    f"{self.base_url}/agents/evals/{eval_id}", headers=self._headers()
                )
            except httpx.RequestError as exc:
                last = type(exc).__name__
            else:
                if response.status_code == 200:
                    try:
                        return parse_evaluation(response.json(), eval_id)
                    except ValueError as exc:
                        last = f"unreadable body: {exc}"
                elif response.status_code in (408, 429) or response.status_code >= 500:
                    last = f"http {response.status_code}"
                else:
                    raise ReadFailed(f"http {response.status_code}: {self._scrub(response.text)}")
            self.log("read_retry", {"eval_id": eval_id, "attempt": attempt, "error": last})
            if attempt < retries:
                sleep(2.0 * attempt)
        raise ReadFailed(f"could not read {eval_id}: {last}")

    def wait(
        self,
        eval_id: str,
        *,
        interval: float = 10.0,
        timeout: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Evaluation:
        """Poll until the evaluation leaves QUEUED and PROCESSING. If `timeout` passes first, the
        last reading (still pending) is returned: that is UNKNOWN, not a failure, and it can be read
        again."""
        deadline = clock() + timeout
        while True:
            evaluation = self.read(eval_id, sleep=sleep)
            if not evaluation.pending or clock() >= deadline:
                return evaluation
            sleep(interval)
