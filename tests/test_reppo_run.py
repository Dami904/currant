from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant.reppo import InvalidSubmission, ReppoLedger, Verdict
from currant.reppo_run import (
    Proposal,
    Submission,
    load_confirmed,
    preference_pairs,
    run_submissions,
    verdict_loop,
    write_submissions,
)
from tests.test_reppo import Rig, created

NOW: dict[str, Any] = {"sleep": lambda _s: None}


def completed(eval_id: str, route: str = "ship", score: float = 90) -> httpx.Response:
    decision = "accept" if score >= 70 else "reject"
    return httpx.Response(
        200,
        json={
            "id": eval_id, "status": "COMPLETED", "creditsCharged": 440,
            "completedAt": "2026-11-11T11:39:34.326Z",
            "result": {
                "score": score, "decision": decision, "route": route, "confidence": "high",
                "reason": "check it", "rubric_scores": {"factual_accuracy": 50},
                "consensus": {"evaluators": [{}, {}, {}]},
            },
        },
    )  # fmt: skip


def subs(*names: str) -> list[Submission]:
    return [Submission(n, "baseline", f"q-{n}", f"Answer {n}.") for n in names]


def run(rig: Rig, tmp_path: Path, names: tuple[str, ...], out: Path, **kw: Any) -> Any:
    """Review (write the file, take its hash), then run: the only way the runner is ever started."""
    path = tmp_path / "submissions.jsonl"
    digest = write_submissions(path, subs(*names))
    return run_submissions(rig.client, rig.ledger, path, digest, out, **{**NOW, **kw})


# --- posting publicly is an explicit act on exactly the reviewed file --------------------


def test_nothing_is_sent_unless_the_hash_of_the_reviewed_file_is_given(tmp_path: Path) -> None:
    path = tmp_path / "submissions.jsonl"
    digest = write_submissions(path, subs("a", "b"))
    assert [s.sub_id for s in load_confirmed(path, digest)] == ["a", "b"]
    rig = Rig(tmp_path)
    out = tmp_path / "results.jsonl"
    for wrong in (None, "", "0" * 64):
        with pytest.raises(InvalidSubmission, match="--confirm-public"):
            run_submissions(rig.client, rig.ledger, path, wrong, out, **NOW)
    path.write_text(path.read_text(encoding="utf-8").replace("Answer a", "Answer z"), "utf-8")
    with pytest.raises(InvalidSubmission):  # edited after the review
        run_submissions(rig.client, rig.ledger, path, digest, out, **NOW)
    assert rig.requests == [] and not out.exists()  # not one request, not one row
    with pytest.raises(InvalidSubmission, match="unique"):
        write_submissions(path, subs("a", "a"))


def test_a_failed_write_never_leaves_a_half_written_submissions_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "submissions.jsonl"
    digest = write_submissions(path, subs("a"))

    def crash(*_a: object) -> None:
        raise OSError("the machine went down mid-write")

    monkeypatch.setattr("currant.reppo_run.os.replace", crash)
    with pytest.raises(OSError):
        write_submissions(path, subs("a", "b"))
    assert [s.sub_id for s in load_confirmed(path, digest)] == ["a"]  # the reviewed file is intact


# --- the audit runner ----------------------------------------------------------------------------


def test_it_settles_in_order_then_resumes_without_resending(tmp_path: Path) -> None:
    out = tmp_path / "results.jsonl"
    rig = Rig(
        tmp_path, created("eval_a"), completed("eval_a"), created("eval_b"), completed("eval_b")
    )
    report = run(rig, tmp_path, ("a", "b"), out)
    assert (report.settled, report.stopped) == (2, None)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["eval_id"] for r in rows] == ["eval_a", "eval_b"] and rows[0]["score"] == 90
    assert rows[0]["route"] == "ship" and rows[0]["rubric"] == {"factual_accuracy": 50}
    assert rows[0]["credits"] == 440 and rows[0]["evaluators"] == 3
    again = run(rig, tmp_path, ("a", "b"), out)
    assert (again.settled, again.skipped, len(rig.requests)) == (0, 2, 4)


@pytest.mark.parametrize(
    "doubt",
    [
        [httpx.ReadTimeout("slow")],  # the submit may or may not have arrived
        [httpx.Response(402, text="not enough credits")],
        [created("eval_a"), httpx.Response(200, json={"id": "eval_a", "status": "PROCESSING"})],
        [created("eval_a"), httpx.Response(200, json={"id": "eval_a", "status": "COMPLETED"})],
        [created("eval_a"), httpx.Response(200, json={"id": "eval_a", "status": "FAILED"})],
    ],
)
def test_it_stops_at_the_first_thing_that_is_not_a_completed_verdict(
    tmp_path: Path, doubt: list[httpx.Response | Exception]
) -> None:
    out = tmp_path / "results.jsonl"
    rig = Rig(tmp_path, *doubt)
    report = run(rig, tmp_path, ("a", "b"), out, timeout=0, interval=1)
    assert report.settled == 0 and report.stopped and report.stopped.startswith("a:")
    assert not out.exists() and len(rig.requests) == len(doubt)  # "b" was never sent


def test_a_failed_evaluation_was_not_charged_so_the_next_run_sends_it_again(tmp_path: Path) -> None:
    out = tmp_path / "results.jsonl"
    failed = httpx.Response(200, json={"id": "eval_a", "status": "FAILED", "creditsCharged": 0})
    rig = Rig(tmp_path, created("eval_a"), failed, created("eval_a2"), completed("eval_a2"))
    first = run(rig, tmp_path, ("a",), out)
    assert first.stopped and "run again to resend" in first.stopped and not out.exists()
    second = run(rig, tmp_path, ("a",), out)
    assert second.settled == 1 and len(rig.requests) == 4  # the same text, sent a second time


def test_a_pending_evaluation_is_read_not_resubmitted_when_the_run_resumes(tmp_path: Path) -> None:
    out = tmp_path / "results.jsonl"
    pending = httpx.Response(200, json={"id": "eval_a", "status": "PROCESSING"})
    rig = Rig(tmp_path, created("eval_a"), pending, completed("eval_a"))
    first = run(rig, tmp_path, ("a",), out, timeout=0)
    assert first.stopped and "pending" in first.stopped
    second = run(rig, tmp_path, ("a",), out)
    assert second.settled == 1 and len(rig.requests) == 3  # one submit, two reads


def test_a_torn_results_line_does_not_stop_a_resume(tmp_path: Path) -> None:
    out = tmp_path / "results.jsonl"
    rig = Rig(
        tmp_path, created("eval_a"), completed("eval_a"), created("eval_b"), completed("eval_b")
    )
    assert run(rig, tmp_path, ("a",), out).settled == 1
    with out.open("ab") as handle:
        handle.write(b'{"sub_id": "b", "sc')  # a crash while appending the next row
    resumed = run(rig, tmp_path, ("a", "b"), out)
    assert (resumed.settled, resumed.skipped) == (1, 1)
    assert [json.loads(x)["sub_id"] for x in out.read_text(encoding="utf-8").splitlines()] == [
        "a",
        "b",
    ]


def test_a_ledger_failure_during_a_run_is_a_stop_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_a: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ReppoLedger, "rejected", fail)
    rig = Rig(tmp_path, httpx.Response(400, text="bad"))
    report = run(rig, tmp_path, ("a",), tmp_path / "results.jsonl")
    assert report.stopped and "disk full" in report.stopped


# --- the revise loop -----------------------------------------------------------------------------


def run_loop(
    tmp_path: Path,
    responses: Sequence[httpx.Response | Exception],
    seen: list[Verdict | None],
    **kw: Any,
) -> Any:
    rig = Rig(tmp_path, *responses)

    def propose(number: int, previous: Verdict | None) -> Proposal | None:
        seen.append(previous)
        return Proposal(f"Answer {number}.", "baseline" if number == 0 else "pull")

    return verdict_loop(rig.client, rig.ledger, "q1", propose, **NOW, **kw)


def test_a_review_route_asks_for_a_new_proposal_with_the_verdict_and_ship_ends_the_loop(
    tmp_path: Path,
) -> None:
    seen: list[Verdict | None] = []
    rounds = run_loop(
        tmp_path,
        [created("e0"), completed("e0", "review", 40), created("e1"), completed("e1", "ship", 95)],
        seen,
    )
    assert [r.label for r in rounds] == ["baseline", "pull"]
    assert seen[0] is None and seen[1] is not None and seen[1].score == 40  # it got the verdict
    assert [r.score for r in rounds] == [40, 95]


def test_the_loop_never_overrules_block_or_a_round_limit_or_a_doubt(tmp_path: Path) -> None:
    seen: list[Verdict | None] = []
    blocked = run_loop(tmp_path / "a", [created("e0"), completed("e0", "block", 5)], seen)
    assert len(blocked) == 1
    keeps_reviewing = [
        created("e0"),
        completed("e0", "review", 40),
        created("e1"),
        completed("e1", "review", 50),
    ]
    limited = run_loop(tmp_path / "b", keeps_reviewing, seen, max_rounds=2)
    assert len(limited) == 2
    doubt = run_loop(tmp_path / "c", [httpx.ReadTimeout("slow")], seen)
    assert len(doubt) == 1 and doubt[0].verdict is None and "unresolved" in (doubt[0].stopped or "")


def test_a_preference_pair_exists_only_for_a_revision_reppo_scored_higher(tmp_path: Path) -> None:
    seen: list[Verdict | None] = []
    better = run_loop(
        tmp_path / "a",
        [created("e0"), completed("e0", "review", 40), created("e1"), completed("e1", "ship", 95)],
        seen,
    )
    (pair,) = preference_pairs("What is the limit?", better)
    assert (pair["chosen"], pair["rejected"], pair["margin"]) == ("Answer 1.", "Answer 0.", 55)
    worse = run_loop(
        tmp_path / "b",
        [created("e0"), completed("e0", "review", 60), created("e1"), completed("e1", "block", 20)],
        seen,
    )
    assert preference_pairs("What is the limit?", worse) == []
