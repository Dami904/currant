from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant.config import Secret
from currant.reppo import (
    InvalidSubmission,
    LedgerWriteError,
    ReadFailed,
    Rejected,
    ReppoClient,
    ReppoError,
    ReppoLedger,
    SubmitUnknown,
    UnresolvedSubmission,
    parse_evaluation,
    submission_key,
)

KEY = "reppo-test-key-123456"
ARGS: dict[str, Any] = {"text": "User prompt: Q\n\nAI response: A public answer."}
COMPLETED: dict[str, Any] = {
    "id": "eval_1", "status": "COMPLETED", "creditsCharged": 440,
    "completedAt": "2026-11-11T11:39:34.326Z",
    "result": {
        "score": 40, "decision": "reject", "route": "review", "confidence": "high",
        "reason": "score 40 < passAt 70",
        "rubric_scores": {"factual_accuracy": 0, "safety": 100},
        "consensus": {"evaluators": [{"model": "a"}, {"model": "b"}, {"model": "c"}]},
    },
}  # fmt: skip


class Rig:
    """A client over a scripted transport; the responses are served in order."""

    def __init__(self, tmp_path: Path, *responses: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self.ledger = ReppoLedger(tmp_path / "ledger.jsonl")
        self.unresolved_at_request: list[list[str]] = []
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            self.unresolved_at_request.append(self.ledger.unresolved())
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        self.client = ReppoClient(
            httpx.Client(transport=httpx.MockTransport(handler)), Secret("REPPO_API_KEY", KEY)
        )

    def submit(self, **overrides: Any) -> str:
        return self.client.submit(self.ledger, **{**ARGS, **overrides})


def created(eval_id: str = "eval_1") -> httpx.Response:
    return httpx.Response(201, json={"id": eval_id, "taskType": "response", "status": "QUEUED"})


# --- what may be sent: refused before anything is sent -----------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"task_type": "essay"},
        {"text": "   "},
        {"text": "x" * (50 * 1024 + 1)},
        {"text": "key " + "sk-" + "a" * 30},  # built, so no key-shaped literal is committed
        {"text": f"the key is {KEY}"},
        {"text": "key " + "sk-" + "​" + "a" * 30},  # zero-width character inside
        {"text": f"the key is {KEY[:6]}​{KEY[6:]}"},
    ],
)
def test_a_submission_that_must_not_go_out_is_refused_before_any_request(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    rig = Rig(tmp_path)
    with pytest.raises(InvalidSubmission):
        rig.submit(**overrides)
    assert rig.requests == [] and not rig.ledger.path.exists()


# --- submitting once -----------------------------------------------------------------------------


def test_the_intent_is_on_disk_before_the_request_and_a_repeat_is_not_sent(tmp_path: Path) -> None:
    rig = Rig(tmp_path, created())
    assert rig.submit() == "eval_1" and rig.submit() == "eval_1"
    assert len(rig.requests) == 1  # the repeat came from the ledger
    assert len(rig.unresolved_at_request[0]) == 1  # an intent existed while the request was made
    assert rig.ledger.unresolved() == []  # and the 201 resolved it
    (request,) = rig.requests
    assert request.url.path == "/api/v1/agents/evals"  # the current endpoint, not the removed one
    assert json.loads(request.content) == {"taskType": "response", "input": ARGS["text"]}
    assert request.headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ReadTimeout("slow"),
        httpx.Response(503),
        httpx.Response(502),  # documented as "not queued", but unmeasured: treated as unknown
        httpx.Response(429),
        httpx.Response(409),  # no longer documented: anything unexpected is unknown
        httpx.Response(201, json={}),
        httpx.Response(201, json={"id": "../x"}),
    ],
)
def test_an_unknown_submit_blocks_every_later_submit_until_resolved(
    tmp_path: Path, outcome: httpx.Response | Exception
) -> None:
    rig = Rig(tmp_path, outcome)
    with pytest.raises(SubmitUnknown):
        rig.submit()
    with pytest.raises(UnresolvedSubmission):
        rig.submit(text="A different answer.")
    with pytest.raises(UnresolvedSubmission):
        rig.submit()  # not even the same one: it may already exist
    assert len(rig.requests) == 1


def test_resolving_an_unknown_submit_unblocks_or_adopts_it(tmp_path: Path) -> None:
    rig = Rig(tmp_path, httpx.ReadTimeout("slow"), created("eval_2"))
    with pytest.raises(SubmitUnknown):
        rig.submit()
    key = rig.ledger.unresolved()[0]
    rig.ledger.resolve(key, None)  # the console shows nothing was created
    assert rig.submit() == "eval_2"
    other = Rig(tmp_path / "b", httpx.ReadTimeout("slow"))
    with pytest.raises(SubmitUnknown):
        other.submit()
    other.ledger.resolve(other.ledger.unresolved()[0], "eval_found")  # the console shows it
    assert other.submit() == "eval_found" and len(other.requests) == 1
    with pytest.raises(ReppoError, match="not unresolved"):
        other.ledger.resolve(key, None)


def test_a_refusal_leaves_nothing_unresolved_and_errors_do_not_leak_the_key(
    tmp_path: Path,
) -> None:
    rig = Rig(
        tmp_path,
        httpx.Response(402, text="not enough credits"),
        httpx.Response(400, text="taskType: Required"),
        httpx.Response(401, text="x" * 295 + KEY),  # the key straddles the 300-character cut
    )
    with pytest.raises(Rejected, match="credits"):
        rig.submit()
    with pytest.raises(Rejected, match="taskType"):
        rig.submit(text="another")
    with pytest.raises(Rejected) as raised:
        rig.submit(text="a third")
    assert KEY[:5] not in str(raised.value)  # not even the part before the 300-character cut
    assert rig.ledger.unresolved() == []


def test_a_ledger_that_cannot_record_a_success_still_reports_the_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, created("eval_lost"))
    logged: list[tuple[str, dict[str, Any]]] = []
    rig.client.log = lambda kind, data: logged.append((kind, data))

    def fail(*_a: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ReppoLedger, "submitted", fail)
    with pytest.raises(LedgerWriteError, match="eval_lost"):
        rig.submit()
    assert ("ledger_write_failed" in [k for k, _ in logged]) and any(
        d.get("eval_id") == "eval_lost" for _k, d in logged
    )


def test_the_key_depends_on_the_type_and_the_text() -> None:
    base = submission_key("response", "text")
    assert base == submission_key("response", "text")
    assert submission_key("claim", "text") != base and submission_key("response", "other") != base


# --- reading ----------------------------------------------------------------------


def test_a_read_retries_a_transient_failure_but_not_a_permanent_one(tmp_path: Path) -> None:
    flaky = Rig(
        tmp_path,
        httpx.Response(503),
        httpx.ReadTimeout("slow"),
        httpx.Response(200, json=COMPLETED),
    )
    evaluation = flaky.client.read("eval_1", sleep=lambda _s: None)
    assert flaky.requests[-1].url.path == "/api/v1/agents/evals/eval_1"
    verdict = evaluation.verdict
    assert verdict is not None and (verdict.route, verdict.decision) == ("review", "reject")
    assert verdict.needs_revision and verdict.evaluators == 3
    assert dict(verdict.rubric) == {"factual_accuracy": 0, "safety": 100}
    assert (verdict.score, evaluation.credits_charged) == (40, 440)
    missing = Rig(tmp_path / "m", httpx.Response(404, text='{"error":"Not found"}'))
    with pytest.raises(ReadFailed, match="404"):
        missing.client.read("nope", sleep=lambda _s: None)
    assert len(missing.requests) == 1
    exhausted = Rig(tmp_path / "e", *[httpx.Response(500)] * 3)
    with pytest.raises(ReadFailed):
        exhausted.client.read("eval_1", sleep=lambda _s: None)


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"score": 150, "decision": "reject", "route": "block"},
        {"score": True, "decision": "reject", "route": "block"},
        {"score": float("nan"), "decision": "reject", "route": "block"},
        {"score": 90, "decision": "revise", "route": "ship"},  # the old API's word is not valid now
        {"score": 90, "decision": "accept", "route": "ship-it"},
        {"score": 90, "decision": "accept"},
    ],
)
def test_a_completed_evaluation_with_an_unreadable_verdict_is_never_a_ship(result: Any) -> None:
    evaluation = parse_evaluation({"id": "e", "status": "COMPLETED", "result": result}, "e")
    assert evaluation.verdict is None and evaluation.problem


def test_a_rubric_score_that_is_not_a_number_is_dropped_not_kept() -> None:
    body = {
        "id": "e",
        "status": "COMPLETED",
        "result": {
            **COMPLETED["result"],
            "rubric_scores": {"bad": float("nan"), "worse": True, "fine": 5},
        },
    }
    verdict = parse_evaluation(body, "e").verdict
    assert verdict is not None and dict(verdict.rubric) == {"fine": 5}


def test_the_statuses_are_pending_failed_or_done() -> None:
    assert parse_evaluation({"id": "e", "status": "QUEUED"}, "e").pending
    assert parse_evaluation({"id": "e", "status": "PROCESSING"}, "e").pending
    failed = parse_evaluation({"id": "e", "status": "FAILED", "creditsCharged": 0}, "e")
    assert failed.failed and not failed.pending and failed.verdict is None


def test_waiting_that_times_out_returns_pending_not_a_failure(tmp_path: Path) -> None:
    pending = {"id": "eval_1", "status": "PROCESSING"}
    rig = Rig(tmp_path, *[httpx.Response(200, json=pending)] * 3)
    now = iter([0.0, 10.0, 20.0, 30.0, 40.0])
    evaluation = rig.client.wait(
        "eval_1", interval=1, timeout=15, sleep=lambda _s: None, clock=lambda: next(now)
    )
    assert evaluation.pending and evaluation.verdict is None
    done = Rig(
        tmp_path / "d", httpx.Response(200, json=pending), httpx.Response(200, json=COMPLETED)
    )
    assert done.client.wait("eval_1", sleep=lambda _s: None).status == "COMPLETED"


# --- the ledger itself ---------------------------------------------------------------------------


def test_a_late_rejection_never_undoes_a_submission_that_succeeded(tmp_path: Path) -> None:
    rig = Rig(tmp_path, created("eval_9"))
    assert rig.submit() == "eval_9"
    key = submission_key("response", ARGS["text"])
    rig.ledger.rejected(key, "a racing second attempt was refused")
    assert rig.ledger.states()[key].status == "submitted"
    assert rig.submit() == "eval_9" and len(rig.requests) == 1  # still not sent a second time


def test_a_failed_evaluation_can_be_sent_again_but_only_once_recorded_as_failed(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, created("eval_f"), created("eval_g"))
    assert rig.submit() == "eval_f"
    key = submission_key("response", ARGS["text"])
    rig.ledger.failed(key, "FAILED, not charged")
    assert rig.ledger.states()[key].status == "failed"
    assert (
        rig.submit() == "eval_g" and len(rig.requests) == 2
    )  # sent again, as Reppo did not charge
    never_sent = ReppoLedger(tmp_path / "other.jsonl")
    never_sent.failed(key, "x")  # a failure with no submission behind it changes nothing
    assert never_sent.states()[key].status == "intent"


def test_two_submits_cannot_be_inside_the_ledger_at_once(tmp_path: Path) -> None:
    ledger = ReppoLedger(tmp_path / "ledger.jsonl")
    with ledger.lock(), pytest.raises(ReppoError, match="another process"), ledger.lock():
        pass
    with ledger.lock(), pytest.raises(ReppoError, match="another process"):
        ledger.resolve("0" * 64, None)  # a resolve may not run while a submit is in flight
    with ledger.lock():  # and it was released afterwards
        pass


def test_a_torn_last_line_is_ignored_then_repaired_and_never_hides_an_unknown_submit(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, httpx.ReadTimeout("slow"))
    with pytest.raises(SubmitUnknown):
        rig.submit()
    with rig.ledger.path.open("ab") as handle:
        handle.write(b'{"event": "submit')  # a crash while writing the outcome
    assert len(rig.ledger.unresolved()) == 1  # the intact intent still blocks
    rig.ledger.resolve(rig.ledger.unresolved()[0], None)
    lines = rig.ledger.path.read_bytes().splitlines()
    assert all(json.loads(line) for line in lines) and rig.ledger.unresolved() == []
    lone = ReppoLedger(tmp_path / "lone.jsonl")
    lone.path.write_bytes(b'{"event": "inte')  # a torn INTENT: the request was never sent
    assert lone.states() == {}


def test_resolving_needs_a_real_key_and_a_real_id(tmp_path: Path) -> None:
    rig = Rig(tmp_path, httpx.ReadTimeout("slow"))
    with pytest.raises(SubmitUnknown):
        rig.submit()
    with pytest.raises(ReppoError, match="no submission has the key"):
        rig.ledger.resolve("0" * 64, None)
    with pytest.raises(ReppoError, match="not an evaluation id"):
        rig.ledger.resolve(rig.ledger.unresolved()[0], "../../x")
    with pytest.raises(ReppoError, match="not an evaluation id"):
        rig.client.read("a/b", sleep=lambda _s: None)
    with pytest.raises(ReppoError, match="not an evaluation id"):
        rig.client.read("eval_1" + chr(10), sleep=lambda _s: None)  # a trailing newline is no id
    assert len(rig.ledger.unresolved()) == 1


def test_if_the_intent_cannot_be_written_nothing_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path)

    def fail(*_a: object) -> None:
        raise OSError("read-only disk")

    monkeypatch.setattr(ReppoLedger, "intent", fail)
    with pytest.raises(ReppoError, match="nothing was sent"):
        rig.submit()
    assert rig.requests == []


def test_the_commands_show_an_unresolved_submission_and_resolve_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from currant import cli

    rig = Rig(tmp_path, httpx.ReadTimeout("slow"))
    with pytest.raises(SubmitUnknown):
        rig.submit()
    ledger = str(rig.ledger.path)
    assert cli.main(["reppo-status", "--ledger", ledger]) == 1  # unresolved is not a pass
    assert "1 unresolved" in capsys.readouterr().out
    key = rig.ledger.unresolved()[0]
    assert cli.main(["reppo-resolve", "--ledger", ledger, "--key", key, "--none"]) == 0
    assert cli.main(["reppo-status", "--ledger", ledger]) == 0
    assert cli.main(["reppo-resolve", "--ledger", ledger, "--key", key, "--none"]) == 2
