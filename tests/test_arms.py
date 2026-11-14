from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from currant.evalset import EvalStore, ItemRow
from currant.ground import Retrieved
from currant.harness.answer import SYSTEM_PROMPT as ANSWER_PROMPT
from currant.harness.arms import (
    ARMS,
    ORACLE_ARM,
    OracleHint,
    _oracle_pull,
    run_arms,
    run_arms_item,
)
from currant.harness.oracle import oracle_hints
from currant.harness.run_items import is_unknown, load_predictions
from currant.harness.synth import generate
from currant.serv import ModelError, ModelReply
from tests.test_harness import SENTENCE, Oracle
from tests.test_synth import Built

PULLED = re.compile(r"<<<PULLED EVIDENCE>>>(.*?)<<<END PULLED EVIDENCE>>>", re.DOTALL)
ANNOTATION = re.compile(r'\[SUPERSEDED: the current documentation says: "([^"]*)"')


def no_sleep(_s: float) -> None:
    return None


def answer_reply(payload: dict[str, Any]) -> ModelReply:
    return ModelReply(json.dumps(payload), "stop", 300, 20, 5, "req")


def read(context: str) -> dict[str, Any]:
    """A good-faith reader: pulled evidence and SUPERSEDED notes win, CONTESTED is honoured, and
    otherwise it takes the first value it sees."""
    if "<<<NOTICE: CONTESTED>>>" in context:
        return {"verdict": "contested", "value": None, "unit": None, "evidence": None}
    pulled = PULLED.search(context)
    annotated = ANNOTATION.search(context)
    text = pulled.group(1) if pulled else annotated.group(1) if annotated else context
    found = SENTENCE.search(text)
    if not found:
        return {"verdict": "unknown", "value": None, "unit": None, "evidence": None}
    return {
        "verdict": "answer",
        "value": int(found.group(2)),
        "unit": "rpm",
        "evidence": found.group(0),
    }


class ArmsModel(Oracle):
    def __init__(self) -> None:
        super().__init__()
        self.answer_calls: list[str] = []

    def complete(
        self, system: str, user: str, *, schema: dict[str, Any], schema_name: str,
        guard: bool, shadow_hint: str | None = None, max_completion_tokens: int | None = None,
    ) -> ModelReply:  # fmt: skip
        if system == ANSWER_PROMPT:
            self.answer_calls.append(user)
            return answer_reply(read(user.split("Documents:\n", 1)[1]))
        return super().complete(
            system, user, schema=schema, schema_name=schema_name, guard=guard,
            shadow_hint=shadow_hint, max_completion_tokens=max_completion_tokens,
        )  # fmt: skip


@pytest.fixture
def world(tmp_path: Path) -> tuple[EvalStore, list[ItemRow]]:
    evals = EvalStore(":memory:")
    built = Built(tmp_path / "built")
    generate(built.store, built.run, evals, seed=1, n_supersede=6, n_clean=4)
    return evals, evals.items()


def scenario_item(evals: EvalStore, items: list[ItemRow], scenario: str) -> ItemRow:
    evals.freeze("test")  # the test reads a label to pick an item; the pipeline never does
    return next(i for i in items if evals.label(i.item_id)["scenario"] == scenario)


def runs(record: dict[str, Any], *, k: int, arm: str) -> list[dict[str, Any]]:
    return [r for r in record["runs"] if r["k"] == k and r["arm"] == arm]


# --- one item ---------------------------------------------------------------------------------


def test_every_arm_and_k_is_run_and_recorded(world: tuple[EvalStore, list[ItemRow]]) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(1, 2), sleep=no_sleep)
    assert record["item_id"] == item.item_id and record["status"] == "complete"
    seen = {(r["k"], r["arm"]) for r in record["runs"] if r["status"] != "no_retrieval"}
    assert {a for _k, a in seen} == set(ARMS) and {k for k, _a in seen} <= {1, 2}
    sample = runs(record, k=2, arm="baseline")[0]
    assert {"retrieved", "actions", "context_sha256", "context_chars", "answer", "tokens"} <= set(
        sample
    )
    assert sample["status"] == "ok" and sample["answer"]["verdict"] in ("answer", "unknown")


def test_the_arms_change_what_the_model_is_shown(world: tuple[EvalStore, list[ItemRow]]) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)  # both pages

    def kinds(arm: str) -> list[str]:
        return sorted(a["kind"] for a in runs(record, k=2, arm=arm)[0]["actions"])

    assert kinds("baseline") == []
    assert kinds("redact") == ["redact"] and kinds("annotate") == ["annotate"]
    assert kinds("pull") == []  # the winner is already in context: nothing to pull
    assert kinds("redact_pull") == ["redact"]
    shas = {a: runs(record, k=2, arm=a)[0]["context_sha256"] for a in ARMS}
    assert shas["redact"] != shas["baseline"] and shas["annotate"] != shas["baseline"]


def test_the_good_faith_reader_is_right_after_redaction_whichever_page_came_first(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    for scenario in ("supersedes_explicit", "supersedes_dated"):
        item = scenario_item(evals, items, scenario)
        record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)
        label = evals.label(item.item_id)
        for arm in ("redact", "annotate", "redact_pull"):
            answer = runs(record, k=2, arm=arm)[0]["answer"]
            assert (
                answer["verdict"] == "answer" and answer["value"] == label["current_value_number"]
            )


def test_a_contested_pair_is_reported_contested_by_every_grounded_arm(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "contested_implicit")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)
    for arm in ("redact", "annotate", "pull", "redact_pull"):
        run = runs(record, k=2, arm=arm)[0]
        assert [a["kind"] for a in run["actions"]] == ["contested"]
        assert run["answer"]["verdict"] == "contested"
    assert runs(record, k=2, arm="baseline")[0]["answer"]["verdict"] != "contested"


def test_a_clean_item_is_not_touched_by_any_arm(world: tuple[EvalStore, list[ItemRow]]) -> None:
    evals, items = world
    item = scenario_item(evals, items, "clean")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)
    base = runs(record, k=2, arm="baseline")[0]["context_sha256"]
    for arm in ARMS:
        run = runs(record, k=2, arm=arm)[0]
        assert run["actions"] == [] and run["context_sha256"] == base, arm


# --- the random-cut control -------------------------------------------------------------------


def test_random_cut_removes_as_many_spans_as_the_detector_does(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)
    detector = [a for a in runs(record, k=2, arm="redact")[0]["actions"] if a["kind"] == "redact"]
    random_cuts = runs(record, k=2, arm="random_cut")[0]["actions"]
    assert len(random_cuts) == len(detector) == 1
    assert all(a["kind"] == "redact" for a in random_cuts)


def test_random_cut_is_reproducible_and_depends_on_the_seed(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")

    def cuts(seed: int) -> Any:
        record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), seed=seed, sleep=no_sleep)
        return runs(record, k=2, arm="random_cut")[0]["actions"]

    assert cuts(0) == cuts(0)
    assert any(cuts(s) != cuts(0) for s in range(1, 12))  # some seed picks a different span


def test_random_cut_removes_nothing_when_the_detector_removes_nothing(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "clean")
    record = run_arms_item(item, ArmsModel(), ArmsModel(), ks=(2,), sleep=no_sleep)
    assert runs(record, k=2, arm="random_cut")[0]["actions"] == []


# --- repeats, retrieval, failures -------------------------------------------------------------


def test_repeats_are_separate_requests(world: tuple[EvalStore, list[ItemRow]]) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    model = ArmsModel()
    record = run_arms_item(
        item, ArmsModel(), model, ks=(2,), arms=("redact",), repeats=3, sleep=no_sleep
    )
    assert [r["repeat"] for r in runs(record, k=2, arm="redact")] == [0, 1, 2]
    assert (
        len(set(model.answer_calls)) == 3
    )  # three different messages, so a cache cannot merge them


def test_a_question_that_retrieves_nothing_is_recorded_not_answered(
    world: tuple[EvalStore, list[ItemRow]], monkeypatch: pytest.MonkeyPatch
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    monkeypatch.setattr("currant.harness.arms.PageIndex.search", lambda *_a, **_k: [])
    model = ArmsModel()
    record = run_arms_item(item, ArmsModel(), model, ks=(1,), sleep=no_sleep)
    assert [r["status"] for r in record["runs"]] == ["no_retrieval"] and model.answer_calls == []


def test_an_item_whose_pipeline_failed_is_unknown_and_spends_no_answers(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")

    class FailingPipeline(ArmsModel):
        def complete(self, system: str, user: str, **kwargs: Any) -> ModelReply:
            if "compare two claims" in system:
                raise ModelError("200 with no content", transient=True)
            return super().complete(system, user, **kwargs)

    answerer = ArmsModel()
    record = run_arms_item(item, FailingPipeline(), answerer, ks=(1, 2), sleep=no_sleep)
    assert record["status"] == "unknown" and record["runs"] == [] and answerer.answer_calls == []
    assert is_unknown(record)


def test_an_answer_that_failed_makes_the_item_unknown_but_a_guard_block_does_not(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")

    class Failing(ArmsModel):
        def complete(self, system: str, user: str, **kwargs: Any) -> ModelReply:
            if system == ANSWER_PROMPT:
                raise ModelError("http 503", transient=True)
            return super().complete(system, user, **kwargs)

    class Blocked(ArmsModel):
        def complete(self, system: str, user: str, **kwargs: Any) -> ModelReply:
            if system == ANSWER_PROMPT:
                return ModelReply("I can't share that.", "content_filter", 0, 0, 5, "r")
            return super().complete(system, user, **kwargs)

    failed = run_arms_item(
        item, ArmsModel(), Failing(), ks=(2,), arms=("baseline",), sleep=no_sleep
    )
    assert failed["status"] == "unknown" and failed["runs"][0]["status"] == "failed"
    blocked = run_arms_item(
        item, ArmsModel(), Blocked(), ks=(2,), arms=("baseline",), sleep=no_sleep
    )
    assert blocked["status"] == "complete" and blocked["runs"][0]["status"] == "guard_blocked"


def test_the_runner_never_reads_a_label(
    world: tuple[EvalStore, list[ItemRow]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _evals, items = world

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("the arms runner touched a label")

    monkeypatch.setattr(EvalStore, "label", forbidden)
    monkeypatch.setattr(EvalStore, "labels", forbidden)
    run_arms_item(
        items[0], ArmsModel(), ArmsModel(), ks=(1,), arms=("baseline", "redact"), sleep=no_sleep
    )


def test_an_unknown_arm_is_refused(world: tuple[EvalStore, list[ItemRow]]) -> None:
    _evals, items = world
    with pytest.raises(ValueError, match="unknown arm"):
        run_arms_item(
            items[0], ArmsModel(), ArmsModel(), arms=("baseline", "shred"), sleep=no_sleep
        )


# --- many items, resumed ------------------------------------------------------------------------


def test_run_arms_resumes_and_reruns_only_unknown_items(
    world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = world
    out = tmp_path / "arms.jsonl"
    meta = {"model": "m", "arms": list(ARMS)}
    assert run_arms(items, ArmsModel(), ArmsModel(), out, limit=3, ks=(2,), arms=("baseline",),
                    meta=meta, sleep=no_sleep) == 3  # fmt: skip
    assert run_arms(items, ArmsModel(), ArmsModel(), out, ks=(2,), arms=("baseline",),
                    meta=meta, sleep=no_sleep) == len(items) - 3  # fmt: skip
    assert len(load_predictions(out)) == len(items)
    with pytest.raises(ValueError, match="different"):
        run_arms(
            items, ArmsModel(), ArmsModel(), out, meta={**meta, "model": "other"}, sleep=no_sleep
        )


def test_run_arms_retries_an_item_that_was_unknown(
    world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = world
    out = tmp_path / "arms.jsonl"

    class Failing(ArmsModel):
        def complete(self, system: str, user: str, **kwargs: Any) -> ModelReply:
            if system == ANSWER_PROMPT:
                raise ModelError("http 503", transient=True)
            return super().complete(system, user, **kwargs)

    first = run_arms(
        items[:2], ArmsModel(), Failing(), out, ks=(2,), arms=("baseline",), sleep=no_sleep
    )
    assert first == 2 and all(is_unknown(p) for p in load_predictions(out).values())
    again = run_arms(
        items[:2], ArmsModel(), ArmsModel(), out, ks=(2,), arms=("baseline",), sleep=no_sleep
    )
    assert again == 2 and not any(is_unknown(p) for p in load_predictions(out).values())


class HistoricalUpdates(ArmsModel):
    """An extractor that files the update notice's claims as historical (a change report)."""

    def complete(
        self, system: str, user: str, *, schema: dict[str, Any], schema_name: str,
        guard: bool, shadow_hint: str | None = None, max_completion_tokens: int | None = None,
    ) -> ModelReply:  # fmt: skip
        reply = super().complete(
            system, user, schema=schema, schema_name=schema_name, guard=guard,
            shadow_hint=shadow_hint, max_completion_tokens=max_completion_tokens,
        )  # fmt: skip
        if system == ANSWER_PROMPT or "replaces" not in user:
            return reply
        data = json.loads(reply.content or "{}")
        if "claims" not in data:
            return reply
        for claim in data["claims"]:
            claim["stance"] = "historical"
        return answer_reply(data)


def test_random_cut_only_ever_cuts_current_claims(world: tuple[EvalStore, list[ItemRow]]) -> None:
    evals, items = world
    item = scenario_item(evals, items, "supersedes_explicit")
    stale_page = evals.label(item.item_id)["stale_page_id"]
    for seed in range(16):
        record = run_arms_item(
            item, HistoricalUpdates(), ArmsModel(), ks=(2,), arms=("redact", "random_cut"),
            seed=seed, sleep=no_sleep,
        )  # fmt: skip
        assert runs(record, k=2, arm="redact")[0]["actions"], (
            "the detector still cuts the stale page"
        )
        for action in runs(record, k=2, arm="random_cut")[0]["actions"]:
            assert action["page"] == stale_page  # never the historical update notice


def test_the_oracle_arm_pulls_the_true_update_exactly_when_only_the_stale_page_was_retrieved(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    evals.freeze("test")  # the hints read labels; the sealed ones open only after the freeze
    hints = oracle_hints(evals, items)  # the only label reader; the runner just gets the hints
    stale_only_seen = 0
    for scenario in ("supersedes_explicit", "supersedes_dated"):
        item = scenario_item(evals, items, scenario)
        label = evals.label(item.item_id)
        record = run_arms_item(
            item, ArmsModel(), ArmsModel(), ks=(1, 2), arms=(ORACLE_ARM,),
            oracle=hints.get, sleep=no_sleep,
        )  # fmt: skip
        for k in (1, 2):
            run = runs(record, k=k, arm=ORACLE_ARM)[0]
            stale_only = (
                label["stale_page_id"] in run["retrieved"]
                and label["update_page_id"] not in run["retrieved"]
            )
            if stale_only:
                stale_only_seen += 1
                (action,) = run["actions"]
                assert action["kind"] == "pull" and action["source_page"] == label["update_page_id"]
                assert (action["start"], action["end"]) == tuple(label["stale_span"])
            else:
                assert run["actions"] == []  # both pages in context, or the stale one missing
    assert stale_only_seen > 0  # the case this arm exists for did occur in the fixture


def test_the_oracle_arm_does_nothing_for_a_clean_item_and_needs_hints(
    world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = world
    evals.freeze("test")  # the hints read labels; the sealed ones open only after the freeze
    hints = oracle_hints(evals, items)
    clean = scenario_item(evals, items, "clean")
    assert clean.item_id not in hints
    record = run_arms_item(
        clean, ArmsModel(), ArmsModel(), ks=(1, 2), arms=(ORACLE_ARM,), oracle=hints.get,
        sleep=no_sleep,
    )  # fmt: skip
    assert all(r["actions"] == [] for r in record["runs"] if r["status"] != "no_retrieval")
    with pytest.raises(ValueError, match="needs oracle hints"):
        run_arms_item(clean, ArmsModel(), ArmsModel(), arms=(ORACLE_ARM,), sleep=no_sleep)


def test_the_oracle_pulls_nothing_when_the_stale_page_is_not_in_context() -> None:
    class Store:
        def document_text(self, _doc: str) -> str:
            return "The limit is now 50."

        def url_of(self, _snapshot: int, doc: str) -> str:
            return f"https://docs.example.com/{doc}"

    hint = OracleHint("a", 0, 8, "The limit", "b", "The limit is now 50.")
    pages = {"doc-a": "a", "doc-b": "b"}
    stale_only = [Retrieved("doc-a", "https://docs.example.com/doc-a")]
    assert [a.kind for a in _oracle_pull(hint, Store(), 1, stale_only, pages)] == ["pull"]
    assert _oracle_pull(hint, Store(), 1, [], pages) == []  # neither page retrieved
    assert _oracle_pull(None, Store(), 1, stale_only, pages) == []
