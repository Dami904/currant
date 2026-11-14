from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.reppo_audit import (
    AuditError,
    Question,
    compose_input,
    load_questions,
    prepare,
    report,
)
from currant.reppo_run import write_submissions
from currant.serv import ModelReply
from tests.test_cli import patch_network
from tests.test_ground import simple
from tests.test_reppo import created
from tests.test_reppo_run import completed, subs

QUESTION = "How many free evaluations do new accounts get?"


class Reader:
    """An answering model that reads like the good-faith reader in the arms tests: it says 50 when
    the context carries a SUPERSEDED note and 10 otherwise."""

    model = "fake"

    def __init__(self, *, always: float | None = None, finish: str = "stop") -> None:
        self.always, self.finish = always, finish

    def complete(self, system: str, user: str, **_kw: Any) -> ModelReply:
        value = self.always if self.always is not None else (50 if "SUPERSEDED" in user else 10)
        body = {"verdict": "answer", "value": value, "unit": "evaluations", "evidence": "x"}
        return ModelReply(json.dumps(body), self.finish, 100, 10, 5, "req")


def world() -> Any:
    w = simple()
    w.finish()
    return w


def run_prepare(model: Reader, questions: list[Question], **kw: Any) -> Any:
    w = world()
    return prepare(w.store, w.extract, w.relate, model, questions, arm="annotate", top_k=2, **kw)


# --- preparing -----------------------------------------------------------------------------------


def test_each_question_is_answered_both_ways_and_judged_against_one_shared_reference() -> None:
    prepared = run_prepare(Reader(), [Question("q1", QUESTION)])
    first, second = prepared.submissions
    assert (first.sub_id, second.sub_id) == ("q1-baseline", "q1-annotate")
    assert first.text.startswith(
        f"User prompt: {QUESTION}"
    )  # the question, the reference, the answer
    assert "AI response: 10" in first.text and "AI response: 50" in second.text
    reference = first.text.split("\n\nAI response:")[0]
    assert reference == second.text.split("\n\nAI response:")[0] and "SUPERSEDED" in reference
    assert prepared.identical == []
    mine = run_prepare(Reader(), [Question("q1", QUESTION, reference="As of Nov 5: 50.")])
    assert all("As of Nov 5: 50." in s.text for s in mine.submissions)  # the person's yardstick


def test_the_reference_goes_inside_the_input_because_the_api_has_no_context_field() -> None:
    text = compose_input(Question("q", "Q?", notes=("Is the unit stated?",)), "REF", "ANSWER")
    assert text == (
        "User prompt: Q?\n\nReference (the current documentation, for checking the facts):\nREF"
        "\n\nCheck in particular:\n- Is the unit stated?\n\nAI response: ANSWER"
    )


def test_agreeing_arms_are_reported_because_they_would_share_one_evaluation() -> None:
    prepared = run_prepare(Reader(always=50), [Question("q1", QUESTION)])
    assert prepared.identical == ["q1"]


@pytest.mark.parametrize(
    ("question", "model", "problem"),
    [
        (Question("q1", "zebra quantum"), Reader(), "no stored page matches"),
        (Question("q1", QUESTION), Reader(finish="content_filter"), "guard_blocked"),
        (Question("q1", QUESTION, reference="x" * 60_000), Reader(), "over 51200 bytes"),
    ],
)
def test_a_question_that_cannot_be_prepared_stops_the_whole_audit(
    question: Question, model: Reader, problem: str
) -> None:
    with pytest.raises(AuditError, match=problem):
        run_prepare(model, [question])  # never a half-prepared set with unequal arms


def test_the_second_arm_cannot_be_the_baseline() -> None:
    w = world()
    with pytest.raises(AuditError, match="grounded arm"):
        prepare(w.store, w.extract, w.relate, Reader(), [], arm="baseline")


def test_questions_need_an_id_and_a_question_and_ids_are_unique(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    good = {"id": "a", "question": "Q?", "reference": "R"}
    path.write_text(json.dumps(good) + "\n", encoding="utf-8")
    assert [q.qid for q in load_questions(path)] == ["a"]
    for bad in ({**good, "question": " "}, {"id": "a"}, {**good, "notes": "not a list"}):
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        with pytest.raises(AuditError, match="not a question"):
            load_questions(path)
    path.write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    with pytest.raises(AuditError, match="unique"):
        load_questions(path)


# --- submitting and reporting through the commands -----------------------------------------------


def test_the_submit_command_sends_nothing_without_the_reviewed_hash_then_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REPPO_API_KEY", "placeholder-key-for-tests")
    sent: list[httpx.Request] = []
    script = iter([created("eval_a"), completed("eval_a", "review", 40)])

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return next(script)

    patch_network(monkeypatch, httpx.MockTransport(handler))
    path, results, ledger = tmp_path / "s.jsonl", tmp_path / "r.jsonl", tmp_path / "l.jsonl"
    digest = write_submissions(path, subs("a"))
    base = ["reppo-audit", "submit", "--submissions", str(path), "--results", str(results)]
    base += ["--ledger", str(ledger), "--dotenv", str(tmp_path / "no.env"), "--interval", "0"]
    assert cli.main([*base]) == 2 and "--confirm-public" in capsys.readouterr().err
    assert cli.main([*base, "--confirm-public", "0" * 64]) == 2 and sent == []
    assert cli.main([*base, "--confirm-public", digest]) == 0
    assert len(sent) == 2 and json.loads(results.read_text(encoding="utf-8"))["score"] == 40


def test_the_report_gives_each_arms_mean_and_the_paired_difference(tmp_path: Path) -> None:
    out = tmp_path / "r.jsonl"
    rows = [
        ("q1", "baseline", 40, "review"), ("q1", "annotate", 90, "ship"),
        ("q2", "baseline", 60, "review"), ("q2", "annotate", 70, "review"),
        ("q3", "baseline", None, "ship"), ("q3", "annotate", float("nan"), "ship"),
    ]  # fmt: skip
    out.write_text(
        "\n".join(
            json.dumps({"sub_id": f"{q}-{a}", "arm": a, "question_id": q, "score": s, "route": d})
            for q, a, s, d in rows
        )
        + "\n",
        encoding="utf-8",
    )
    text = report(out)
    assert (
        "baseline     n=2   mean score  50.0" in text
        and "annotate     n=2   mean score  80.0" in text
    )
    assert "+30.0" in text and "better on 2, worse on 0" in text and "few questions" in text
    assert (
        "2 rows skipped" in text and "4 completed verdicts" in text
    )  # null and NaN are not scores
    assert "'ship': 1" in text and report(tmp_path / "missing.jsonl") == "no settled verdicts yet"
