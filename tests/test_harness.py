from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.detect import SYSTEM_PROMPT as RELATE_PROMPT
from currant.evalset import EvalStore, ItemRow
from currant.extract import SYSTEM_PROMPT as EXTRACT_PROMPT
from currant.harness.run_items import load_predictions, run_item, run_items
from currant.harness.score import Outcome, cluster_bootstrap, overlaps, score_item, summarize
from currant.harness.synth import generate
from currant.serv import ModelReply
from tests.test_cli import patch_network
from tests.test_synth import Built

SENTENCE = re.compile(r"The request limit for the (\w+) widget is (\d+) requests per minute\.")
REPLACES = re.compile(r"This replaces the previous value of \d+ in earlier documentation\.")
LAST_UPDATED = re.compile(r"Last updated: \d{4}-\d{2}-\d{2}")
BOLD_DATE = re.compile(r"\*\*\d{4}-\d{2}-\d{2}\*\*")

World = tuple[Built, EvalStore, list[ItemRow]]


def page(user: str, label: str) -> str:
    opener = f"<<<BEGIN PAGE {label}>>>\n"
    start = user.index(opener) + len(opener)
    return user[start : user.index(f"\n<<<END PAGE {label}>>>")]


def reply(payload: dict[str, Any]) -> ModelReply:
    return ModelReply(json.dumps(payload), "stop", 300, 50, 5, "req")


def widget_name(text: str) -> str:
    found = SENTENCE.search(text)
    return found.group(1) if found else ""


def truth(text_a: str, text_b: str) -> dict[str, Any]:
    """What a perfect classifier says about two widget pages."""
    base: dict[str, Any] = {
        "relation": "contradicts", "basis": "none", "ordering_quote": None,
        "date_quote_a": None, "date_quote_b": None, "explanation": "oracle",
    }  # fmt: skip
    if widget_name(text_a) != widget_name(text_b):
        return {**base, "relation": "unrelated"}
    for text in (text_a, text_b):
        found = REPLACES.search(text)
        if found:
            return {**base, "relation": "supersedes", "basis": "explicit_text",
                    "ordering_quote": found.group(0)}  # fmt: skip
    quote_a = LAST_UPDATED.search(text_a) or BOLD_DATE.search(text_a)
    quote_b = LAST_UPDATED.search(text_b) or BOLD_DATE.search(text_b)
    if quote_a and quote_b:
        return {**base, "relation": "supersedes", "basis": "dated",
                "date_quote_a": quote_a.group(0), "date_quote_b": quote_b.group(0)}  # fmt: skip
    return base


class Oracle:
    """A perfect extractor, plus a pluggable classifier, for the widget pages, offline."""

    model = "oracle"

    def __init__(self, relate: Any = truth) -> None:
        self.relate = relate

    def complete(
        self, system: str, user: str, *, schema: dict[str, Any], schema_name: str,
        guard: bool, shadow_hint: str | None = None, max_completion_tokens: int | None = None,
    ) -> ModelReply:  # fmt: skip
        if system == EXTRACT_PROMPT:
            text = user.split("<<<BEGIN PAGE>>>\n", 1)[1]
            claims = [
                {"quote": m.group(0), "subject": f"{m.group(1)} widget",
                 "attribute": "request limit", "value_text": f"{m.group(2)} requests per minute",
                 "value_type": "count", "value_number": int(m.group(2)),
                 "unit": "requests per minute", "stance": "current", "asserted_at": None}
                for m in SENTENCE.finditer(text)
            ]  # fmt: skip
            return reply({"claims": claims})
        assert system == RELATE_PROMPT
        return reply(self.relate(page(user, "A"), page(user, "B")))


@pytest.fixture
def world(tmp_path: Path) -> World:
    built = Built(tmp_path)
    evals = EvalStore(":memory:")
    generate(built.store, built.run, evals, seed=1, n_supersede=6, n_clean=4)
    return built, evals, evals.items()


def score_all(
    evals: EvalStore, items: list[ItemRow], preds: dict[str, dict[str, Any]]
) -> list[Outcome]:
    evals.freeze("test the scorer")  # reading test labels needs the freeze
    return [score_item(i, evals.label(i.item_id), preds.get(i.item_id)) for i in items]


def no_sleep(_seconds: float) -> None:
    return None


# --- the whole pipeline, end to end, offline -----------------------------------------------


def test_a_perfect_model_scores_perfectly_on_every_scenario(world: World, tmp_path: Path) -> None:
    _built, evals, items = world
    out = tmp_path / "preds.jsonl"
    assert run_items(items, Oracle(), out, sleep=no_sleep) == 10
    summary = summarize(score_all(evals, items, load_predictions(out)))
    metrics = summary["metrics"]
    assert metrics["precision"] == 1.0 and metrics["recall"] == 1.0
    assert metrics["implicit_contested"] == 1.0 and metrics["implicit_false_cut"] == 0.0
    assert metrics["clean_false_cut"] == 0.0 and metrics["clean_false_contested"] == 0.0
    assert summary["by_scenario"]["clean"]["ran"] == 4


def test_the_pipeline_never_reads_a_label(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _built, _evals, items = world

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("the pipeline touched a label")

    monkeypatch.setattr(EvalStore, "label", forbidden)
    monkeypatch.setattr(EvalStore, "labels", forbidden)
    assert run_items(items, Oracle(), tmp_path / "p.jsonl", sleep=no_sleep) == 10


def test_invented_ordering_evidence_makes_no_cut(world: World, tmp_path: Path) -> None:
    _built, evals, items = world

    def liar(_a: str, _b: str) -> dict[str, Any]:
        quote = "This replaces the previous value of 999 in earlier documentation."
        return {
            "relation": "supersedes", "basis": "explicit_text", "ordering_quote": quote,
            "date_quote_a": None, "date_quote_b": None, "explanation": "trust me",
        }  # fmt: skip

    run_items(items, Oracle(relate=liar), tmp_path / "p.jsonl", sleep=no_sleep)
    metrics = summarize(score_all(evals, items, load_predictions(tmp_path / "p.jsonl")))["metrics"]
    assert metrics["cuts"] == 0 and metrics["precision"] is None
    assert metrics["recall"] == 0.0  # it missed every real supersession...
    assert metrics["clean_false_cut"] == 0.0  # ...but it did no harm


def test_a_reckless_classifier_still_cannot_make_a_cut_without_evidence(
    world: World, tmp_path: Path
) -> None:
    _built, evals, items = world

    def reckless(a: str, b: str) -> dict[str, Any]:
        answer = truth(a, b)
        if answer["relation"] == "contradicts":  # implicit pairs: no ordering evidence exists
            sentence = SENTENCE.search(b)
            answer = {**answer, "relation": "supersedes", "basis": "explicit_text",
                      "ordering_quote": sentence.group(0) if sentence else "x"}  # fmt: skip
        return answer

    run_items(items, Oracle(relate=reckless), tmp_path / "p.jsonl", sleep=no_sleep)
    metrics = summarize(score_all(evals, items, load_predictions(tmp_path / "p.jsonl")))["metrics"]
    # The "evidence" is just the claim's own sentence, which names no replaced value: downgraded.
    assert metrics["implicit_false_cut"] == 0.0 and metrics["precision"] == 1.0


def test_run_items_resumes_and_respects_limit(world: World, tmp_path: Path) -> None:
    _built, _evals, items = world
    out = tmp_path / "p.jsonl"
    assert run_items(items, Oracle(), out, limit=3, sleep=no_sleep) == 3
    assert run_items(items, Oracle(), out, sleep=no_sleep) == 7  # only the rest
    assert len(load_predictions(out)) == 10


def test_a_prediction_records_what_the_pipeline_did(world: World) -> None:
    _built, evals, items = world
    evals.freeze("inspect")
    explicit = next(i for i in items if evals.label(i.item_id)["scenario"] == "supersedes_explicit")
    prediction = run_item(explicit, Oracle(), sleep=no_sleep)
    assert prediction["item_id"] == explicit.item_id
    assert prediction["extraction"]["pages_ok"] == 2 and prediction["detection"]["supersedes"] == 1
    (relation,) = prediction["relations"]
    assert relation["kind"] == "supersedes" and relation["basis"] == "explicit_text"
    assert relation["newer"]["page"] != relation["older"]["page"]


# --- scoring ----------------------------------------------------------------------------------


def item(cluster: str = "c") -> ItemRow:
    return ItemRow("i", "synthetic", cluster, "dev", False, {})


LABEL: dict[str, Any] = {
    "scenario": "supersedes_explicit", "stale_page_id": "a", "update_page_id": "b",
    "stale_span": [100, 140], "current_value_number": 50.0,
}  # fmt: skip


def cut(
    older_page: str = "a",
    span: tuple[int, int] = (100, 140),
    newer_page: str = "b",
    value: float = 50.0,
) -> dict[str, Any]:
    return {
        "kind": "supersedes", "basis": "explicit_text",
        "older": {"page": older_page, "start": span[0], "end": span[1], "value_number": 10.0},
        "newer": {"page": newer_page, "start": 0, "end": 30, "value_number": value},
    }  # fmt: skip


def test_overlap_requires_a_shared_character() -> None:
    assert overlaps((0, 10), (9, 20)) and not overlaps((0, 10), (10, 20))


@pytest.mark.parametrize(
    ("relation", "correct", "on_stale"),
    [
        (cut(), 1, True),
        (cut(span=(120, 130)), 1, True),  # inside the stale span
        (cut(older_page="b", newer_page="a"), 0, False),  # the newer page was cut: wrong direction
        (cut(value=51.0), 0, True),  # right span, wrong current value
        (cut(span=(300, 340)), 0, False),  # a cut somewhere else on the page
    ],
)
def test_a_cut_is_correct_only_if_span_direction_and_value_all_match(
    relation: dict[str, Any], correct: int, on_stale: bool
) -> None:
    outcome = score_item(item(), LABEL, {"relations": [relation]})
    assert (outcome.cuts, outcome.correct_cuts, outcome.cut_on_stale) == (1, correct, on_stale)


def test_every_cut_counts_toward_precision_even_a_spurious_second_one() -> None:
    outcome = score_item(item(), LABEL, {"relations": [cut(), cut(span=(300, 340))]})
    assert (outcome.cuts, outcome.correct_cuts) == (2, 1)


def test_a_cut_on_an_implicit_or_clean_item_is_never_correct() -> None:
    for scenario in ("contested_implicit", "clean"):
        label = {
            **LABEL,
            "scenario": scenario,
            "update_page_id": None,
            "current_value_number": None,
        }
        outcome = score_item(item(), label, {"relations": [cut()]})
        assert (outcome.cuts, outcome.correct_cuts) == (1, 0)


def test_a_contradiction_on_the_stale_span_counts_as_contested() -> None:
    claims = [{"page": "a", "start": 100, "end": 140}, {"page": "b", "start": 0, "end": 30}]
    outcome = score_item(item(), LABEL, {"relations": [{"kind": "contradicts", "claims": claims}]})
    assert outcome.contested_on_stale and outcome.cuts == 0
    elsewhere = [{"page": "a", "start": 500, "end": 540}, {"page": "b", "start": 0, "end": 30}]
    other = score_item(item(), LABEL, {"relations": [{"kind": "contradicts", "claims": elsewhere}]})
    assert not other.contested_on_stale


def test_an_item_with_no_prediction_is_a_miss_not_a_harm() -> None:
    outcome = score_item(item(), LABEL, None)
    assert (outcome.ran, outcome.cuts) == (False, 0)


def outcomes(correct: int, wrong: int, cluster: str) -> list[Outcome]:
    def one(name: str, ok: int) -> Outcome:
        return Outcome(name, cluster, "supersedes_explicit", 1, ok, True, False, True)

    return [one(f"{cluster}r{i}", 1) for i in range(correct)] + [
        one(f"{cluster}w{i}", 0) for i in range(wrong)
    ]


def test_intervals_resample_whole_clusters_so_correlated_items_widen_them() -> None:
    # Ten items in two clusters, one all right and one all wrong. As items it looks like 50%; as
    # two clusters the honest interval is as wide as it can be.
    data = outcomes(5, 0, "good") + outcomes(0, 5, "bad")
    interval = cluster_bootstrap(data, rounds=500, seed=1)["precision"]
    assert interval == (0.0, 1.0)
    assert cluster_bootstrap(data, rounds=500, seed=1) == cluster_bootstrap(
        data, rounds=500, seed=1
    )


def test_many_independent_clusters_give_a_tight_interval() -> None:
    data = [o for i in range(40) for o in outcomes(1, 0, f"c{i}")]
    assert cluster_bootstrap(data, rounds=500, seed=1)["precision"] == (1.0, 1.0)


def test_summarize_reports_counts_per_scenario_and_cluster() -> None:
    summary = summarize(outcomes(2, 1, "x") + outcomes(1, 0, "y"))
    assert summary["items"] == 4 and summary["clusters"] == 2
    assert summary["by_scenario"]["supersedes_explicit"]["correct_cut"] == 3
    assert summary["metrics"]["precision"] == pytest.approx(3 / 4)


# --- the command line, end to end -------------------------------------------------------------


def chat_handler(oracle: Oracle, seen: list[int]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        seen.append(1)
        out = oracle.complete(system, user, schema={}, schema_name="", guard=True)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": out.content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return handler


def test_generate_run_and_score_through_the_command_line(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    built, _evals, _items = world
    db, evalset = tmp_path / "currant.db", tmp_path / "evalset.db"
    target = sqlite3.connect(db)
    built.store.conn.backup(target)
    target.close()
    base = ["--evalset", str(evalset)]
    assert cli.main(["make-synthetic", "--db", str(db), *base, "--run", str(built.run),
                     "--supersede", "6", "--clean", "4"]) == 0  # fmt: skip
    capsys.readouterr()

    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    seen: list[int] = []
    patch_network(monkeypatch, httpx.MockTransport(chat_handler(Oracle(), seen)))
    out = tmp_path / "dev.jsonl"
    cache = tmp_path / "cache.db"
    run = ["run-items", *base, "--split", "dev", "--out", str(out), "--cache", str(cache),
           "--dotenv", str(tmp_path / "no.env")]  # fmt: skip
    assert cli.main(run) == 0
    first_calls = len(seen)
    assert first_calls > 0 and "model calls:" in capsys.readouterr().out
    raw = out.with_name(out.name + ".raw.jsonl")
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    # one line per call: every request sent to the model, plus any answered from the cache
    assert sum(r["source"] == "model" for r in rows) == first_calls
    assert all(r["source"] in ("model", "cache") for r in rows)
    meta = json.loads(out.with_name(out.name + ".meta.json").read_text(encoding="utf-8"))
    assert {"model", "extract_prompt", "relate_prompt", "retries", "min_score", "top_k",
            "max_pairs", "raw_log"} <= set(meta)  # fmt: skip

    assert cli.main(run) == 0  # resumes: nothing left to run, nothing sent
    assert len(seen) == first_calls
    out.unlink()  # a fresh predictions file, but the cache remembers every answer
    assert cli.main(run) == 0
    assert len(seen) == first_calls  # served entirely from the cache
    capsys.readouterr()

    assert cli.main(["score", *base, "--predictions", str(out), "--split", "dev"]) == 0
    printed = capsys.readouterr().out
    assert "precision" in printed and "source pages" in printed


def test_test_items_cannot_be_run_or_scored_before_the_freeze(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _built, evals, _items = world
    evalset = tmp_path / "evalset.db"
    disk = sqlite3.connect(evalset)
    evals.conn.backup(disk)
    disk.close()
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = ["run-items", "--evalset", str(evalset), "--split", "test",
            "--cache", str(tmp_path / "c.db"), "--dotenv", str(tmp_path / "no.env")]  # fmt: skip
    assert cli.main(args) == 2
    assert "before the freeze" in capsys.readouterr().err
    preds = tmp_path / "p.jsonl"
    preds.write_text("", encoding="utf-8")
    assert (
        cli.main(
            ["score", "--evalset", str(evalset), "--predictions", str(preds), "--split", "test"]
        )
        == 2
    )
    assert "sealed" in capsys.readouterr().err
