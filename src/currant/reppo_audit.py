"""The Reppo audit: real questions in, a reviewable submissions file out, and a report afterwards.

The plan's audit sends matched answers (the same questions answered by the baseline and by the best
grounded arm) to Reppo for an independent verdict. Three steps, and only the middle one touches the
network or spends credits:

1. `prepare`  answer each question both ways (this uses SERV, a few cents) and WRITE the
              submissions file. Nothing is sent to Reppo. A person reads the file.
2. `submit`   `reppo_run.run_submissions`, which refuses to send unless given the SHA-256 of that
              exact file. Everything in it becomes public on Reppo's feed.
3. `report`   per-arm mean score and the paired difference per question, with an interval.

Reppo's current API takes only `taskType` and `input`: no criteria and no context. Measured on
2026-11-11, a CORRECT answer with no reference scored 65 (factual_accuracy 0, route `review`),
because the judges had nothing to check the figures against. So the reference documentation goes
INSIDE the input, after the question and before the answer, for both arms alike.

The questions are REAL questions about real documentation, written by a person; the synthetic
evaluation items are never used here (they contain invented "updates" that must not be posted
publicly as if they were documentation). A question may carry a `reference`: a person's own
statement of what the current documentation says. When it is there, it is the reference Reppo is
shown for BOTH answers, so the judges' yardstick does not depend on Currant's output.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from currant.ground import ground
from currant.harness.answer import Answer, AnswerModel, ask
from currant.harness.stats import paired_cluster_bootstrap
from currant.reppo import MAX_INPUT_BYTES, read_jsonl
from currant.reppo_run import Submission
from currant.retrieve import PageIndex
from currant.store import ClaimStore


class AuditError(RuntimeError):
    """The audit cannot be prepared as asked."""


@dataclass(frozen=True)
class Question:
    qid: str
    question: str
    reference: str | None = None
    notes: tuple[str, ...] = ()  # optional things for the judges to check, added to the input


def load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            qid, text = str(row["id"]), str(row["question"]).strip()
            if not qid or not text:
                raise ValueError("an id and a question are required")
            notes = row.get("notes") or []
            if not isinstance(notes, list):
                raise ValueError("`notes` must be a list")
            reference = row.get("reference")
            questions.append(
                Question(
                    qid,
                    text,
                    str(reference) if reference else None,
                    tuple(str(n) for n in notes),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise AuditError(f"{path} line {number} is not a question: {exc}") from exc
    ids = [q.qid for q in questions]
    if len(set(ids)) != len(ids):
        raise AuditError("question ids must be unique")
    return questions


def answer_text(answer: Answer) -> str:
    if answer.verdict == "answer" and answer.value is not None:
        unit = f" {answer.unit}" if answer.unit else ""
        evidence = f" Evidence: {answer.evidence}" if answer.evidence else ""
        return f"{answer.value:g}{unit}.{evidence}"
    if answer.verdict == "contested":
        text = (
            "The documentation is contested: the sources disagree and nothing shows which "
            "is current."
        )
        if answer.contested:  # only values the CONTESTED notice's verified quotes state
            stated = "; ".join(
                f"{v.value:g}{f' {v.unit}' if v.unit else ''}"
                + (f" ({v.source})" if v.source else "")
                for v in answer.contested
            )
            text += f" The sources state: {stated}."
        return text
    return "The documentation does not say."


def compose_input(question: Question, reference: str, answer: str) -> str:
    """What Reppo is shown: the question, the reference to check against, then the answer."""
    parts = [f"User prompt: {question.question}"]
    parts.append(f"Reference (the current documentation, for checking the facts):\n{reference}")
    if question.notes:
        parts.append("Check in particular:\n" + "\n".join(f"- {n}" for n in question.notes))
    parts.append(f"AI response: {answer}")
    return "\n\n".join(parts)


@dataclass
class Prepared:
    submissions: list[Submission]
    identical: list[str] = field(default_factory=list)  # questions where both arms said the same


def prepare(
    store: ClaimStore,
    extract_run_id: int,
    relate_run_id: int,
    model: AnswerModel,
    questions: list[Question],
    *,
    arm: str = "pull",
    top_k: int = 2,
    retries: int = 2,
    sleep: Any = None,
) -> Prepared:
    """Answer every question with the baseline and with `arm`. Any failure stops the preparation:
    a half-prepared audit would compare unequal sets."""
    if arm == "baseline":
        raise AuditError("the second arm must be a grounded arm, not the baseline")
    snapshot_id = store.run_meta(extract_run_id).snapshot_id
    prepared = Prepared([])
    kwargs: dict[str, Any] = {"retries": retries}
    if sleep is not None:
        kwargs["sleep"] = sleep
    with PageIndex(store, snapshot_id) as index:
        for q in questions:
            docs = index.search(q.question, k=top_k)
            if not docs:
                raise AuditError(f"no stored page matches question {q.qid!r}")
            contexts = {
                mode: ground(
                    store, docs, mode=mode,
                    extract_run_id=extract_run_id, relate_run_id=relate_run_id,
                ).context
                for mode in ("baseline", arm)
            }  # fmt: skip
            reference = q.reference or contexts[arm]
            texts: dict[str, str] = {}
            for mode in ("baseline", arm):
                result = ask(model, q.question, contexts[mode], **kwargs)
                if result.answer is None:  # blocked, failed or unreadable: never half an audit
                    raise AuditError(f"{q.qid}/{mode}: {result.status}: {result.reason}")
                text = compose_input(q, reference, answer_text(result.answer))
                if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
                    raise AuditError(
                        f"question {q.qid!r}: the submission is over {MAX_INPUT_BYTES} bytes; use "
                        "a smaller --top-k or give the question a shorter `reference`"
                    )
                texts[mode] = text
                prepared.submissions.append(Submission(f"{q.qid}-{mode}", mode, q.qid, text))
            if texts["baseline"] == texts[arm]:
                prepared.identical.append(q.qid)
    return prepared


# --- the report ------------------------------------------------------------


def report(results: Path) -> str:
    rows = read_jsonl(results)
    if not rows:
        return "no settled verdicts yet"
    by_arm: dict[str, dict[str, float]] = {}
    routes: dict[str, dict[str, int]] = {}
    skipped = 0
    for row in rows:
        score = row.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(score)
        ):
            skipped += 1  # a null or non-finite score is not a result
            continue
        arm, qid = str(row["arm"]), str(row["question_id"])
        by_arm.setdefault(arm, {})[qid] = float(score)
        counts = routes.setdefault(arm, {})
        counts[str(row.get("route"))] = counts.get(str(row.get("route")), 0) + 1
    lines = [f"{len(rows) - skipped} completed verdicts from {results.name}"]
    if skipped:
        lines.append(f"  {skipped} rows skipped: their score is missing or not a number")
    for arm, scores in sorted(by_arm.items()):
        mean = sum(scores.values()) / len(scores)
        lines.append(f"  {arm:<12} n={len(scores):<3} mean score {mean:5.1f}  routes {routes[arm]}")
    if "baseline" in by_arm:
        for arm in (a for a in by_arm if a != "baseline"):
            shared = sorted(set(by_arm["baseline"]) & set(by_arm[arm]))
            diffs = [(qid, by_arm[arm][qid] - by_arm["baseline"][qid]) for qid in shared]
            interval = paired_cluster_bootstrap(diffs)
            better = sum(1 for _q, d in diffs if d > 0)
            worse = sum(1 for _q, d in diffs if d < 0)
            if interval is None:
                lines.append(f"  {arm} vs baseline: no matched questions")
                continue
            mean, low, high = interval
            lines.append(
                f"  {arm} minus baseline over {len(diffs)} matched questions: {mean:+.1f} "
                f"(95% interval {low:+.1f} to {high:+.1f}); better on {better}, worse on {worse}"
            )
            if len(diffs) < 20:
                lines.append("  few questions: read the interval, not the mean")
    lines.append(
        "  Reppo's judges have noise of their own; this is an audit, not the primary metric."
    )
    return "\n".join(lines)
