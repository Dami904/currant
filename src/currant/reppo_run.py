"""Running Reppo evaluations: the audit runner and the `revise` loop, on top of `reppo.py`.

Everything submitted to Reppo is PUBLIC and spends credits (440 per completed evaluation). An
evaluation takes about a minute (56 s measured), and several may be in flight at once; this module
still sends them ONE AT A TIME, because the cost of a doubt is money. So:

* a submission file is written first (`currant reppo-audit prepare`) and reviewed by a person; the
  runner refuses to send it unless it is given that file's SHA-256 (`--confirm-public`), so posting
  is always an explicit act on exactly the reviewed text;
* the runner is sequential and STOPS at the first thing that is not a completed verdict (a timeout,
  an unknown submit, no credits, a failed evaluation). It never loops past a doubt. Running it again
  resumes: finished rows are skipped and an evaluation already submitted is read, not resent. A
  FAILED evaluation was not charged, so it is recorded as failed and the next run sends it again;
* the loop never overrules a verdict. `ship` and `block` end it; only `review` asks for a new
  proposal, up to a round limit.

Reppo's reason text is third-party text. It may be passed to a model only as data, behind the
prompt guard; this module only carries it.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from currant.reppo import (
    Evaluation,
    InvalidSubmission,
    ReadFailed,
    Rejected,
    ReppoClient,
    ReppoError,
    ReppoLedger,
    SubmitUnknown,
    UnresolvedSubmission,
    Verdict,
    read_jsonl,
    repair_jsonl_tail,
    submission_key,
)


@dataclass(frozen=True)
class Submission:
    sub_id: str
    arm: str
    question_id: str
    text: str  # the `input` that is sent: the question, the answer, and any reference
    task_type: str = "response"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub_id": self.sub_id,
            "arm": self.arm,
            "question_id": self.question_id,
            "task_type": self.task_type,
            "text": self.text,
        }


def write_submissions(path: Path, submissions: list[Submission]) -> str:
    """Write the file a person will review; returns its SHA-256."""
    ids = [s.sub_id for s in submissions]
    if len(set(ids)) != len(ids):
        raise InvalidSubmission("submission ids must be unique")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s.to_dict(), ensure_ascii=False, sort_keys=True) for s in submissions]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)  # whole or not at all: a reviewer never sees half a file
    return hashlib.sha256(data).hexdigest()


def load_confirmed(path: Path, confirmed_sha256: str | None) -> list[Submission]:
    """The submissions in `path`, but only if the caller names the SHA-256 of exactly these bytes.
    The bytes are read once, hashed, and parsed, so what was confirmed is what is sent. Everything
    in the file is posted publicly, so this is the one door to the network."""
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if confirmed_sha256 != actual:
        raise InvalidSubmission(
            f"--confirm-public must be {actual} (the SHA-256 of {path.name} as it is now). "
            "Review the file first: everything in it is posted publicly."
        )
    out: list[Submission] = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            out.append(
                Submission(
                    str(row["sub_id"]),
                    str(row["arm"]),
                    str(row["question_id"]),
                    str(row["text"]),
                    str(row.get("task_type", "response")),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidSubmission(f"{path} line {number} is not a submission: {exc}") from exc
    return out


# --- one evaluation -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    status: str  # settled | stopped
    evaluation: Evaluation | None = None
    eval_id: str | None = None
    reason: str | None = None  # why it stopped


def evaluate(
    client: ReppoClient,
    ledger: ReppoLedger,
    sub: Submission,
    *,
    interval: float = 10.0,
    timeout: float = 600.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    """Submit (once) and wait for the verdict. Anything but a readable completed one is a stop."""
    eval_id: str | None = None
    try:
        eval_id = client.submit(ledger, text=sub.text, task_type=sub.task_type)
        evaluation = client.wait(
            eval_id, interval=interval, timeout=timeout, sleep=sleep, clock=clock
        )
        if evaluation.failed:
            # Reppo says a FAILED evaluation is not charged: remember that, so the same text is
            # sent again on the next run instead of being read as "done" forever.
            ledger.failed(submission_key(sub.task_type, sub.text), "FAILED, not charged")
    except (UnresolvedSubmission, SubmitUnknown) as exc:
        return Result("stopped", None, eval_id, f"unresolved: {exc}")
    except Rejected as exc:
        return Result("stopped", None, eval_id, f"refused by Reppo: {exc}")
    except (ReadFailed, ReppoError, OSError) as exc:
        return Result("stopped", None, eval_id, str(exc))
    if evaluation.pending:
        return Result("stopped", evaluation, eval_id, "still pending; run again to resume")
    if evaluation.failed:
        return Result("stopped", evaluation, eval_id, "FAILED (not charged); run again to resend")
    if evaluation.verdict is None:
        why = evaluation.problem or f"status {evaluation.status}"
        return Result("stopped", evaluation, eval_id, f"no usable verdict: {why}")
    return Result("settled", evaluation, eval_id)


# --- the audit runner -----------------------------------------------------------------------------


def _row(sub: Submission, result: Result) -> dict[str, Any]:
    evaluation, verdict = (
        result.evaluation,
        result.evaluation.verdict if result.evaluation else None,
    )
    assert verdict is not None and evaluation is not None
    return {
        "sub_id": sub.sub_id,
        "arm": sub.arm,
        "question_id": sub.question_id,
        "eval_id": result.eval_id,
        "score": verdict.score,
        "decision": verdict.decision,
        "route": verdict.route,
        "confidence": verdict.confidence,
        "reason": verdict.reason,
        "rubric": dict(verdict.rubric),
        "evaluators": verdict.evaluators,
        "credits": evaluation.credits_charged,
        "completed_at": evaluation.completed_at,
    }


def _settled_ids(path: Path) -> set[str]:
    return {str(row["sub_id"]) for row in read_jsonl(path)}


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repair_jsonl_tail(path)
    with path.open("ab") as handle:
        handle.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


@dataclass
class RunReport:
    settled: int = 0
    skipped: int = 0
    stopped: str | None = None  # the reason, or None when every submission has a verdict
    notes: list[str] = field(default_factory=list)


def run_submissions(
    client: ReppoClient,
    ledger: ReppoLedger,
    submissions_path: Path,
    confirmed_sha256: str | None,
    out: Path,
    **wait: Any,
) -> RunReport:
    """Send the reviewed submissions one at a time, appending each verdict to `out`; stop at the
    first doubt. Re-running resumes: finished rows are skipped. Nothing is sent unless
    `confirmed_sha256` is the SHA-256 of the submissions file."""
    submissions = load_confirmed(submissions_path, confirmed_sha256)
    report = RunReport()
    done = _settled_ids(out)
    for sub in submissions:
        if sub.sub_id in done:
            report.skipped += 1
            continue
        result = evaluate(client, ledger, sub, **wait)
        if result.status != "settled":
            report.stopped = f"{sub.sub_id}: {result.reason}"
            return report
        _append(out, _row(sub, result))
        report.settled += 1
    return report


# --- the revise loop ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    text: str
    label: str  # for example the grounding mode that produced it


@dataclass(frozen=True)
class Round:
    number: int
    label: str
    text: str
    eval_id: str | None
    verdict: Verdict | None
    stopped: str | None = None

    @property
    def score(self) -> float | None:
        return self.verdict.score if self.verdict else None


def verdict_loop(
    client: ReppoClient,
    ledger: ReppoLedger,
    question_id: str,
    propose: Callable[[int, Verdict | None], Proposal | None],
    *,
    max_rounds: int = 3,
    **wait: Any,
) -> list[Round]:
    """Ask Reppo about a proposal; on a `review` route, ask `propose` for another (it gets the
    verdict, so it can re-ground with Reppo's reason). `ship` and `block` end the loop, as does any
    doubt."""
    rounds: list[Round] = []
    previous: Verdict | None = None
    for number in range(max_rounds):
        proposal = propose(number, previous)
        if proposal is None:
            break
        sub = Submission(f"{question_id}-r{number}", proposal.label, question_id, proposal.text)
        result = evaluate(client, ledger, sub, **wait)
        verdict = result.evaluation.verdict if result.evaluation else None
        rounds.append(
            Round(number, proposal.label, proposal.text, result.eval_id, verdict, result.reason)
        )
        if result.status != "settled" or verdict is None or not verdict.needs_revision:
            break
        previous = verdict
    return rounds


def preference_pairs(question: str, rounds: list[Round]) -> list[dict[str, Any]]:
    """A pair for each revision that Reppo scored higher than what it replaced: the verdict stream
    as preference data. A revision that did not improve the score is not a preference."""
    pairs: list[dict[str, Any]] = []
    for before, after in itertools.pairwise(rounds):
        if before.score is None or after.score is None or after.score <= before.score:
            continue
        pairs.append(
            {
                "prompt": question,
                "chosen": after.text,
                "rejected": before.text,
                "margin": after.score - before.score,
                "eval_ids": [before.eval_id, after.eval_id],
            }
        )
    return pairs
