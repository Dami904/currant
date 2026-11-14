"""Failure-path tests from the reliability audit: UNKNOWN is never FAILED, nothing is dropped,
nothing is cached that should be retried, and replay never raises."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.detect import SYSTEM_PROMPT as RELATE_PROMPT
from currant.detect import decide, record, run_detection
from currant.evalset import EvalStore, ItemRow
from currant.ground import ground
from currant.harness.run_items import is_unknown, load_predictions, run_item, run_items
from currant.harness.score import Outcome, pooled, score_item, summarize
from currant.harness.synth import generate
from currant.llmcache import CachingModel, json_object_reply
from currant.receipt import replay
from currant.serv import ModelError, ModelReply
from currant.store import StoreError
from tests.test_cli import patch_network
from tests.test_cli_ground import to_disk
from tests.test_detect import (
    TEXT_EXPLICIT,
    TEXT_OLD,
    Ctx,
    FakeModel,
    answer_reply,
    explicit_answer,
    fixed_content,
    relate_run,
)
from tests.test_ground import R10, S10, S50, U1, U2, World, simple
from tests.test_harness import Oracle
from tests.test_llmcache import Counting, ask
from tests.test_receipt import make, reseal
from tests.test_serv import Rig, ok_body
from tests.test_synth import Built


def no_sleep(_seconds: float) -> None:
    return None


def payloads(ctx: Ctx, kind: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload) for e in ctx.store.events() if e.kind == kind]


def status_of(ctx: Ctx, run_id: int) -> str:
    row = ctx.store.conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return str(row["status"])


# --- detector: a pair that was not decided is recorded, never dropped ------------------------


def failing(request_id: str = "req-9") -> FakeModel:
    def respond(_user: str) -> ModelReply:
        raise ModelError("http 503", transient=True, request_id=request_id)

    return FakeModel(respond)


def test_a_failed_pair_is_persisted_so_it_can_be_reconciled() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, failing(), sleep=no_sleep
    )
    (event,) = payloads(ctx, "pair_failed")
    assert {event["claim_a"], event["claim_b"]} == {ctx.old.claim_id, ctx.new.claim_id}
    assert event["attempts"] == 3 and event["transient"] is True
    assert event["request_id"] == "req-9" and "http 503" in event["reason"]
    assert summary.failed == 1


def test_a_run_with_an_undecided_pair_is_not_complete() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, failing(), sleep=no_sleep
    )
    assert status_of(ctx, summary.run_id) == "failed"


def test_unusable_model_output_also_leaves_the_pair_recorded_and_the_run_incomplete() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, fixed_content("not json"), sleep=no_sleep
    )
    (event,) = payloads(ctx, "pair_failed")
    assert "invalid JSON" in event["reason"] and event["attempts"] == 1
    assert status_of(ctx, summary.run_id) == "failed"


def test_every_retry_is_logged_with_its_request_id() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    state = {"n": 0}

    def flaky(_user: str) -> ModelReply:
        state["n"] += 1
        if state["n"] < 3:
            raise ModelError("http 503", transient=True, request_id=f"req-{state['n']}")
        return answer_reply(explicit_answer())

    run_detection(ctx.store, ctx.run, ctx.snapshot.snapshot_id, FakeModel(flaky), sleep=no_sleep)
    retries = payloads(ctx, "model_retry")
    assert [r["attempt"] for r in retries] == [1, 2]
    assert [r["request_id"] for r in retries] == ["req-1", "req-2"]
    assert payloads(ctx, "pair_failed") == []


def test_an_unexpected_error_fails_the_run_and_is_logged_before_it_propagates() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)

    def explode(_user: str) -> ModelReply:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_detection(
            ctx.store, ctx.run, ctx.snapshot.snapshot_id, FakeModel(explode), sleep=no_sleep
        )
    (event,) = payloads(ctx, "run_interrupted")
    assert "boom" in event["error"]
    row = ctx.store.conn.execute(
        "SELECT status FROM runs WHERE stage = 'relate' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "failed"


def test_a_relation_is_rejected_not_orphaned_when_recording_fails_midway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    run = relate_run(ctx)
    decision = decide(explicit_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    real = ctx.store.add_evidence
    calls = {"n": 0}

    def flaky_add(*args: Any, **kwargs: Any) -> bool:
        calls["n"] += 1
        if calls["n"] == 2:
            raise StoreError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(ctx.store, "add_evidence", flaky_add)
    result = record(ctx.store, run, ctx.old, ctx.new, decision)
    assert result.outcome == "rejected" and result.relation_id is not None
    assert ctx.store.relation_status(result.relation_id) == "rejected"


# --- the model client: request ids and malformed bodies --------------------------------------


def test_errors_carry_the_request_id_when_the_server_sent_one() -> None:
    headers = {"x-openserv-request-id": "req-x"}
    for response in (
        httpx.Response(503, headers=headers),
        httpx.Response(400, text="bad", headers=headers),
        httpx.Response(200, json=ok_body("", "stop"), headers=headers),
    ):
        with pytest.raises(ModelError) as raised:
            Rig(lambda _r, resp=response: resp).call()
        assert raised.value.request_id == "req-x"


@pytest.mark.parametrize(
    "body",
    [
        {"choices": ["oops"]},
        {"choices": [{"message": "oops", "finish_reason": "stop"}]},
        {"choices": [{"message": {"content": 5}, "finish_reason": "stop"}]},
        {"choices": [{"message": {"content": ["a"]}, "finish_reason": "stop"}]},
    ],
)
def test_a_malformed_200_body_is_a_transient_model_error_not_a_crash(body: dict[str, Any]) -> None:
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(200, json=body)).call()
    assert raised.value.transient is True


# --- the cache never keeps a reply that deserves another try ---------------------------------


def make_counting(reply: ModelReply) -> Counting:
    class One(Counting):
        def complete(self, *args: Any, **kwargs: Any) -> ModelReply:
            self.calls += 1
            return reply

    return One()


@pytest.mark.parametrize(
    "reply",
    [
        ModelReply('{"relation":"supers', "length", 10, 5, 3, "r"),  # truncated
        ModelReply("", "length", 10, 5, 3, "r"),
        ModelReply(None, None, 0, 0, 3, "r"),
        ModelReply(None, "stop", 0, 0, 3, "r"),  # the empty 200 that once poisoned the cache
        ModelReply("some text", "tool_calls", 10, 5, 3, "r"),
    ],
)
def test_only_complete_or_filtered_replies_are_cached(reply: ModelReply, tmp_path: Path) -> None:
    from currant.llmcache import CachingModel

    inner = make_counting(reply)
    with CachingModel(inner, tmp_path / "c.db") as model:
        ask(model)
        ask(model)
    assert inner.calls == 2  # the second ask went to the model again


# --- ground: it refuses runs it should not trust ---------------------------------------------


def finished(world: World) -> World:
    world.finish()
    return world


def test_ground_needs_a_relate_run_not_an_extract_run() -> None:
    world = finished(simple())
    with pytest.raises(ValueError, match="not a relate run"):
        ground(
            world.store, [world.doc(U1)], mode="redact",
            extract_run_id=world.extract, relate_run_id=world.extract,
        )  # fmt: skip


def test_ground_refuses_a_relate_run_from_another_snapshot() -> None:
    world = finished(simple())
    other = world.store.ingest_pages("other", [("https://docs.example.com/z.md", "# Z" + chr(10))])
    foreign = world.store.start_run("relate", "fake", "relate-v1", other.snapshot_id)
    world.store.finish_run(foreign)
    with pytest.raises(ValueError, match="different snapshot"):
        ground(
            world.store, [world.doc(U1)], mode="redact",
            extract_run_id=world.extract, relate_run_id=foreign,
        )  # fmt: skip


def test_ground_refuses_a_relate_run_that_is_unfinished_or_left_pairs_undecided() -> None:
    running = simple()  # still running: relations can only be added to a running run
    with pytest.raises(ValueError, match="did not complete"):
        ground(
            running.store, [running.doc(U1)], mode="redact",
            extract_run_id=running.extract, relate_run_id=running.relate,
        )  # fmt: skip
    failed = simple()
    failed.store.finish_run(failed.relate, "failed")
    with pytest.raises(ValueError, match="did not complete"):
        failed.ground("redact", [U1])


def test_a_replacement_loop_is_not_redacted_from_either_side() -> None:
    first = chr(10).join(
        ["# A", "", S10, "", "This replaces the previous value of 50 in earlier documentation."]
    )
    second = chr(10).join(["# B", "", S50, "", R10])
    world = World(
        (U1, first + chr(10), S10, 10, "current"), (U2, second + chr(10), S50, 50, "current")
    )
    world.supersede(U2, U1, R10)
    world.supersede(U1, U2, "This replaces the previous value of 50 in earlier documentation.")
    finished(world)
    result = world.ground("redact", [U1, U2])
    assert result.actions == [] and S10 in result.context and S50 in result.context


# --- replay: hostile numbers never raise -----------------------------------------------------


@pytest.mark.parametrize(
    "value", [10**30, float("inf"), float("nan"), "1", 1.0, True, None, [], {}, -1]
)
@pytest.mark.parametrize("stage", ["extract", "relate"])
def test_replay_survives_hostile_run_ids(value: Any, stage: str) -> None:
    world = simple()
    receipt = copy.deepcopy(make(world))
    receipt["runs"][stage]["run_id"] = value
    try:
        sealed = reseal(receipt)
    except (TypeError, ValueError):
        sealed = receipt  # NaN is not valid JSON; replay must still refuse it
    result = replay(world.store, sealed)
    assert result.ok is False and result.problems


# --- item runner: an item that did not finish is UNKNOWN, not a result ------------------------


class FailingRelate(Oracle):
    def complete(
        self, system: str, user: str, *, schema: dict[str, Any], schema_name: str,
        guard: bool, shadow_hint: str | None = None, max_completion_tokens: int | None = None,
    ) -> ModelReply:  # fmt: skip
        if system == RELATE_PROMPT:
            raise ModelError("200 with no content", transient=True)
        return super().complete(
            system, user, schema=schema, schema_name=schema_name, guard=guard,
            shadow_hint=shadow_hint, max_completion_tokens=max_completion_tokens,
        )  # fmt: skip


@pytest.fixture
def items_world(tmp_path: Path) -> tuple[EvalStore, list[ItemRow]]:
    evals = EvalStore(":memory:")
    generate(Built(tmp_path).store, Built(tmp_path).run, evals, seed=1, n_supersede=6, n_clean=4)
    return evals, evals.items()


def test_an_item_with_a_failed_pair_is_marked_unknown(
    items_world: tuple[EvalStore, list[ItemRow]],
) -> None:
    evals, items = items_world
    evals.freeze("inspect")
    explicit = next(i for i in items if evals.label(i.item_id)["scenario"] == "supersedes_explicit")
    prediction = run_item(explicit, FailingRelate(), sleep=no_sleep)
    assert prediction["status"] == "unknown" and is_unknown(prediction)
    assert run_item(explicit, Oracle(), sleep=no_sleep)["status"] == "complete"


def test_a_legacy_prediction_without_a_status_is_judged_by_its_counts() -> None:
    assert is_unknown({"detection": {"failed": 1}, "extraction": {"pages_failed": 0}})
    assert is_unknown({"detection": {"failed": 0}, "extraction": {"pages_failed": 2}})
    assert not is_unknown({"detection": {"failed": 0}, "extraction": {"pages_failed": 0}})


def test_resume_reruns_unknown_items_and_keeps_the_complete_ones(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    assert run_items(items, FailingRelate(), out, sleep=no_sleep) == 10
    first = load_predictions(out)
    unknown = [i for i, p in first.items() if is_unknown(p)]
    assert 0 < len(unknown) < 10  # clean items have no pairs, so they finished
    assert run_items(items, Oracle(), out, sleep=no_sleep) == len(unknown)  # only those again
    final = load_predictions(out)
    assert len(final) == 10 and not any(is_unknown(p) for p in final.values())


def test_scoring_excludes_unknown_items_from_the_no_harm_rates_and_counts_them_as_misses(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    evals, items = items_world
    out = tmp_path / "p.jsonl"
    run_items(items, FailingRelate(), out, sleep=no_sleep)
    evals.freeze("score")
    preds = load_predictions(out)
    outcomes = [score_item(i, evals.label(i.item_id), preds[i.item_id]) for i in items]
    summary = summarize(outcomes)
    assert summary["unknown"] == sum(o.unknown for o in outcomes) > 0
    assert summary["metrics"]["recall"] == 0.0  # an undecided pair is a miss, not a success


def test_an_unknown_clean_item_does_not_count_as_proof_of_no_harm() -> None:
    def clean(name: str, unknown: bool) -> Outcome:
        return Outcome(name, name, "clean", 0, 0, False, False, True, unknown)

    assert pooled([clean("a", False), clean("b", True)])["clean_false_cut"] == 0.0
    harmed = Outcome("h", "h", "clean", 1, 0, True, False, True, False)
    # one real false cut among one decided item: 1.0, not diluted by the unknown one
    assert pooled([harmed, clean("b", True)])["clean_false_cut"] == 1.0


# --- provenance and torn files ---------------------------------------------------------------


def test_predictions_record_their_provenance_and_refuse_a_mixed_resume(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    meta = {"model": "model-a", "extract_prompt": "extract-v1", "relate_prompt": "relate-v1"}
    run_items(items, Oracle(), out, limit=2, meta=meta, sleep=no_sleep)
    sidecar = tmp_path / "p.jsonl.meta.json"
    assert json.loads(sidecar.read_text(encoding="utf-8")) == meta
    run_items(items, Oracle(), out, limit=2, meta=meta, sleep=no_sleep)  # same: fine
    with pytest.raises(ValueError, match="different"):
        run_items(items, Oracle(), out, meta={**meta, "model": "model-b"}, sleep=no_sleep)


def test_a_torn_last_line_is_dropped_and_the_file_is_repaired_on_resume(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    run_items(items, Oracle(), out, limit=2, sleep=no_sleep)
    with out.open("a", encoding="utf-8") as handle:
        handle.write('{"item_id": "cut off mid-wri')  # an interrupted write, no newline
    assert len(load_predictions(out)) == 2  # the torn tail is ignored
    run_items(items, Oracle(), out, sleep=no_sleep)
    assert len(load_predictions(out)) == 10  # and every line is valid again


def test_a_corrupt_line_in_the_middle_is_an_error_not_silently_skipped(tmp_path: Path) -> None:
    out = tmp_path / "p.jsonl"
    out.write_text(
        '{"item_id": "a"}' + chr(10) + "garbage" + chr(10) + '{"item_id": "b"}' + chr(10),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2"):
        load_predictions(out)


def test_the_score_command_reports_unpredicted_and_unknown_items(
    items_world: tuple[EvalStore, list[ItemRow]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evals, items = items_world
    import sqlite3

    db = tmp_path / "evalset.db"
    disk = sqlite3.connect(db)
    evals.conn.backup(disk)
    disk.close()
    out = tmp_path / "p.jsonl"
    run_items(items, FailingRelate(), out, limit=6, sleep=no_sleep)
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    assert (
        cli.main(["score", "--evalset", str(db), "--predictions", str(out), "--split", "dev"]) == 0
    )
    printed = capsys.readouterr().out
    assert "unpredicted" in printed and "unknown" in printed


def test_predictions_with_no_provenance_record_cannot_be_resumed_with_new_settings(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "legacy.jsonl"
    run_items(items, Oracle(), out, limit=2, sleep=no_sleep)  # written without a record
    assert not (tmp_path / "legacy.jsonl.meta.json").exists()
    with pytest.raises(ValueError, match="no provenance record"):
        run_items(items, Oracle(), out, meta={"model": "model-a"}, sleep=no_sleep)


# --- A: an extract run that is not complete is never used downstream ---------------------------


def test_ground_refuses_an_extract_run_that_did_not_complete() -> None:
    world = finished(simple())
    open_run = world.store.start_run("extract", "fake", "extract-v1", world.snapshot_id)
    relate = world.store.start_run("relate", "fake", "relate-v1", world.snapshot_id)
    world.store.finish_run(relate)
    with pytest.raises(ValueError, match=r"extract run .* did not complete"):
        ground(
            world.store, [world.doc(U1)], mode="redact",
            extract_run_id=open_run, relate_run_id=relate,
        )  # fmt: skip


def test_relate_refuses_an_extract_run_that_did_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    open_run = world.store.start_run("extract", "fake", "extract-v1", world.snapshot_id)
    db = to_disk(world, tmp_path / "c.db")
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    cache, dotenv = str(tmp_path / "cache.db"), str(tmp_path / "no.env")
    args = ["relate", "--db", str(db), "--extract-run", str(open_run)]
    assert cli.main([*args, "--cache", cache, "--dotenv", dotenv]) == 2
    assert "did not complete" in capsys.readouterr().err


# --- B: items nobody ran are not proof of no harm ----------------------------------------------


def test_an_unpredicted_item_does_not_dilute_the_no_harm_rates() -> None:
    def clean(name: str, ran: bool) -> Outcome:
        return Outcome(name, name, "clean", 0, 0, False, False, ran, False)

    harmed = Outcome("h", "h", "clean", 1, 0, True, False, True, False)
    rates = pooled([harmed, clean("a", False), clean("b", False), clean("c", False)])
    assert rates["clean_false_cut"] == 1.0  # one decided clean item, and it was cut

    def implicit(name: str, ran: bool) -> Outcome:
        return Outcome(name, name, "contested_implicit", 0, 0, False, False, ran, False)

    assert pooled([implicit("a", False)])["implicit_false_cut"] is None  # nothing was run


# --- C: a reply the caller cannot use is not remembered ----------------------------------------


@pytest.mark.parametrize(
    ("content", "usable"),
    [
        ('{"a": 1}', True),
        ("{}", True),
        ("[1, 2]", False),
        ("not json", False),
        ('"text"', False),
        ("", False),
        (None, False),
    ],
)
def test_json_object_reply_accepts_only_objects(content: str | None, usable: bool) -> None:
    assert json_object_reply(ModelReply(content, "stop", 1, 1, 1, "r")) is usable


def test_the_caller_decides_what_is_usable_enough_to_cache(tmp_path: Path) -> None:
    for content, calls in (("not json", 2), ('{"ok": true}', 1)):
        inner = make_counting(ModelReply(content, "stop", 10, 5, 3, "r"))
        with CachingModel(inner, tmp_path / f"{calls}.db", accept=json_object_reply) as model:
            ask(model)
            ask(model)
        assert inner.calls == calls


# --- D: every model call lands in the raw log ----------------------------------------------------


def test_every_call_is_written_to_the_raw_log_hits_misses_and_errors(tmp_path: Path) -> None:
    inner = Counting()
    log = tmp_path / "raw.jsonl"
    with CachingModel(inner, tmp_path / "c.db", raw_log=log) as model:
        ask(model)  # a miss
        ask(model)  # a hit
        inner.fail = True
        with pytest.raises(ModelError):
            ask(model, user="a different request")
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["source"] for r in rows] == ["model", "cache", "model"]
    assert rows[0]["content"] == "answer 1" and rows[0]["cached"] is True
    assert rows[1]["content"] == "answer 1"
    assert "503" in rows[2]["error"] and rows[2]["cached"] is False
    assert len({r["cache_key"] for r in rows[:2]}) == 1


def test_a_reply_that_was_not_cached_is_still_in_the_raw_log(tmp_path: Path) -> None:
    log = tmp_path / "raw.jsonl"
    truncated = ModelReply('{"relation":"supers', "length", 10, 5, 3, "req-7")
    with CachingModel(make_counting(truncated), tmp_path / "c.db", raw_log=log) as model:
        ask(model)
    (row,) = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert row["cached"] is False and row["finish_reason"] == "length"
    assert row["content"] == '{"relation":"supers' and row["request_id"] == "req-7"


# --- smaller gaps ----------------------------------------------------------------------------


def test_a_refused_resume_does_not_modify_the_file(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    meta = {"model": "model-a"}
    run_items(items, Oracle(), out, limit=2, meta=meta, sleep=no_sleep)
    with out.open("ab") as handle:
        handle.write(b'{"item_id": "torn')
    before = out.read_bytes()
    with pytest.raises(ValueError, match="different"):
        run_items(items, Oracle(), out, meta={"model": "model-b"}, sleep=no_sleep)
    assert out.read_bytes() == before  # the torn tail was NOT repaired by a refused run


def test_resuming_without_settings_is_refused_when_a_record_exists(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    run_items(items, Oracle(), out, limit=2, meta={"model": "model-a"}, sleep=no_sleep)
    with pytest.raises(ValueError, match="provenance record"):
        run_items(items, Oracle(), out, sleep=no_sleep)


def test_a_failing_log_does_not_mask_the_original_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)

    def explode(_user: str) -> ModelReply:
        raise RuntimeError("boom")

    def broken_log(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the log itself failed")

    monkeypatch.setattr(ctx.store, "log_event", broken_log)
    with pytest.raises(RuntimeError, match="boom"):
        run_detection(
            ctx.store, ctx.run, ctx.snapshot.snapshot_id, FakeModel(explode), sleep=no_sleep
        )
    row = ctx.store.conn.execute(
        "SELECT status FROM runs WHERE stage = 'relate' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "failed"  # still closed even though the log write failed


def test_relate_reports_an_unexpected_error_instead_of_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db = to_disk(world, tmp_path / "c.db")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(cli, "run_detection", boom)
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    cache, dotenv = str(tmp_path / "cache.db"), str(tmp_path / "no.env")
    args = ["relate", "--db", str(db), "--extract-run", str(world.extract)]
    assert cli.main([*args, "--cache", cache, "--dotenv", dotenv]) == 2
    assert "detector exploded" in capsys.readouterr().err
