"""Gaps from the fourth reliability audit: the raw log must never cost a paid reply, an extract
run must say what it covered, a resume must not mix settings, and old cache rows must not outlive
the check that would reject them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.evalset import EvalStore, ItemRow
from currant.extract import run_extraction
from currant.ground import ground
from currant.harness.run_items import run_items
from currant.harness.synth import generate
from currant.llmcache import CachingModel, json_object_reply
from currant.serv import ModelError, ModelReply
from currant.store import StoreError
from tests.test_cli import patch_network
from tests.test_cli_ground import to_disk
from tests.test_extract import (
    FakeModel,
    crashing_on_second_page,
    good,
    no_sleep,
    ok_model,
    reply,
)
from tests.test_ground import U1, simple
from tests.test_harness import Oracle
from tests.test_llmcache import Counting, ask
from tests.test_reliability import finished
from tests.test_store import World as StoreWorld
from tests.test_synth import Built


@pytest.fixture
def items_world(tmp_path: Path) -> tuple[EvalStore, list[ItemRow]]:
    evals = EvalStore(":memory:")
    built = Built(tmp_path / "built")
    generate(built.store, built.run, evals, seed=1, n_supersede=6, n_clean=4)
    return evals, evals.items()


def returning(content: str, finish: str = "stop") -> Counting:
    reply = ModelReply(content, finish, 10, 5, 3, "r")

    class One(Counting):
        def complete(self, *args: Any, **kwargs: Any) -> ModelReply:
            self.calls += 1
            return reply

    return One()


# --- 1: a failing raw log never costs a paid reply -------------------------------------------


def broken_log(tmp_path: Path) -> Path:
    path = tmp_path / "raw_is_a_directory"
    path.mkdir()  # appending to a directory raises OSError on every platform
    return path


def test_a_failing_raw_log_still_caches_and_returns_the_reply(tmp_path: Path) -> None:
    inner = returning('{"ok": true}')
    with CachingModel(inner, tmp_path / "c.db", raw_log=broken_log(tmp_path)) as model:
        assert ask(model).content == '{"ok": true}'
        assert ask(model).content == '{"ok": true}'
        assert inner.calls == 1 and model.hits == 1  # the paid reply was cached despite the log
        assert model.log_errors >= 1


def test_a_failing_raw_log_does_not_replace_the_model_error(tmp_path: Path) -> None:
    inner = Counting()
    inner.fail = True
    with CachingModel(inner, tmp_path / "c.db", raw_log=broken_log(tmp_path)) as model:
        with pytest.raises(ModelError) as raised:
            ask(model)
        assert raised.value.transient is True  # not an OSError, so retries still work
        assert model.log_errors >= 1


# --- 3: a torn raw-log tail does not corrupt the next record ---------------------------------


def test_a_torn_raw_log_tail_is_repaired_before_appending(tmp_path: Path) -> None:
    log = tmp_path / "raw.jsonl"
    log.write_bytes(b'{"source": "model", "n": 1}' + bytes([10]) + b'{"source": "mod')  # torn
    with CachingModel(Counting(), tmp_path / "c.db", raw_log=log) as model:
        ask(model)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["source"] for line in lines] == ["model", "model"]  # all valid


def test_a_clean_raw_log_is_left_alone(tmp_path: Path) -> None:
    log = tmp_path / "raw.jsonl"
    log.write_bytes(b'{"n": 1}' + bytes([10]))
    with CachingModel(Counting(), tmp_path / "c.db", raw_log=log):
        pass
    assert log.read_bytes() == b'{"n": 1}' + bytes([10])


# --- 7: an old cache row is not served once the caller would reject it -----------------------


def test_a_stale_unusable_cache_row_is_not_served_and_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    with CachingModel(returning("not json"), path) as before_the_check_existed:
        ask(before_the_check_existed)  # cached: there was no accept check yet
    good = returning('{"ok": true}')
    with CachingModel(good, path, accept=json_object_reply) as model:
        assert ask(model).content == '{"ok": true}'  # the stale row was NOT served
        assert ask(model).content == '{"ok": true}'
    assert good.calls == 1  # and the good reply is now cached


def test_a_stale_row_is_deleted_even_if_the_new_reply_is_unusable_too(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    with CachingModel(returning("not json"), path) as first:
        ask(first)
    with CachingModel(returning("still not json"), path, accept=json_object_reply) as second:
        ask(second)
        ask(second)  # a miss again: nothing was kept
    with CachingModel(returning("x"), path) as third:
        assert third._db.execute("SELECT COUNT(*) FROM replies").fetchone()[0] == 0


# --- 2: an unwritable cache or log location is a clean error, not a traceback ----------------


def test_relate_reports_an_unwritable_results_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db = to_disk(world, tmp_path / "c.db")
    work = tmp_path / "cwd"
    work.mkdir()
    (work / "results").write_text("a file where a directory should be", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = ["relate", "--db", str(db), "--extract-run", str(world.extract)]
    code = cli.main([*args, "--cache", str(tmp_path / "cache.db"), "--dotenv", str(tmp_path / "x")])
    assert code == 2 and "error" in capsys.readouterr().err


def test_run_items_reports_an_unwritable_output_location(
    items_world: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sqlite3

    evals, _items = items_world
    db = tmp_path / "evalset.db"
    disk = sqlite3.connect(db)
    evals.conn.backup(disk)
    disk.close()
    blocker = tmp_path / "blocker"
    blocker.write_text("a file", encoding="utf-8")
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = ["run-items", "--evalset", str(db), "--split", "dev", "--out", str(blocker / "p.jsonl")]
    code = cli.main([*args, "--cache", str(tmp_path / "c.db"), "--dotenv", str(tmp_path / "x")])
    assert code == 2 and "error" in capsys.readouterr().err


# --- 5: a limited extract run does not pass for full coverage ---------------------------------


def test_a_limited_run_is_recorded_as_limited_only_when_it_truncated(tmp_path: Path) -> None:
    world = StoreWorld(tmp_path)  # two pages
    limited = run_extraction(world.store, world.snapshot_id, ok_model(), limit=1, sleep=no_sleep)
    assert world.store.run_meta(limited.run_id).params["limited"] is True
    roomy = run_extraction(world.store, world.snapshot_id, ok_model(), limit=5, sleep=no_sleep)
    assert world.store.run_meta(roomy.run_id).params["limited"] is False
    full = run_extraction(world.store, world.snapshot_id, ok_model(), sleep=no_sleep)
    assert world.store.run_meta(full.run_id).params["limited"] is False


def test_ground_and_relate_refuse_an_extract_run_that_covered_only_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = finished(simple())
    partial = world.store.start_run(
        "extract", "fake", "extract-v1", world.snapshot_id, {"limit": 1, "limited": True}
    )
    world.store.finish_run(partial)
    relate = world.store.start_run("relate", "fake", "relate-v1", world.snapshot_id)
    world.store.finish_run(relate)
    with pytest.raises(ValueError, match="only part of the snapshot"):
        ground(
            world.store,
            [world.doc(U1)],
            mode="redact",
            extract_run_id=partial,
            relate_run_id=relate,
        )
    db = to_disk(world, tmp_path / "c.db")
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = ["relate", "--db", str(db), "--extract-run", str(partial)]
    code = cli.main([*args, "--cache", str(tmp_path / "cache.db"), "--dotenv", str(tmp_path / "x")])
    assert code == 2 and "only part of the snapshot" in capsys.readouterr().err


# --- 6: a resume cannot mix models or settings in one run -------------------------------------


def crashed_run(world: StoreWorld) -> int:
    with pytest.raises(RuntimeError):
        run_extraction(world.store, world.snapshot_id, crashing_on_second_page(), sleep=no_sleep)
    return int(world.store.conn.execute("SELECT run_id FROM runs").fetchone()["run_id"])


def test_a_resume_with_a_different_model_is_refused(tmp_path: Path) -> None:
    world = StoreWorld(tmp_path)
    run_id = crashed_run(world)
    other = ok_model()
    other.model = "a-different-model"
    with pytest.raises(StoreError, match="different model"):
        run_extraction(world.store, world.snapshot_id, other, resume_run_id=run_id, sleep=no_sleep)


@pytest.mark.parametrize("option", ["shadow", "allow_unguarded_retry"])
def test_a_resume_with_different_settings_is_refused(tmp_path: Path, option: str) -> None:
    world = StoreWorld(tmp_path)
    run_id = crashed_run(world)
    with pytest.raises(StoreError, match="different settings"):
        run_extraction(
            world.store,
            world.snapshot_id,
            ok_model(),
            resume_run_id=run_id,
            sleep=no_sleep,
            shadow=option == "shadow",
            allow_unguarded_retry=option == "allow_unguarded_retry",
        )


# --- 8: no failure may mask the original error; the sidecar is written whole -------------------


def test_a_failing_event_log_does_not_mask_the_extraction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = StoreWorld(tmp_path)
    armed = {"on": False}
    real = world.store.log_event

    def log_event(*args: Any, **kwargs: Any) -> None:
        if armed["on"]:
            raise RuntimeError("the log itself failed")
        real(*args, **kwargs)

    monkeypatch.setattr(world.store, "log_event", log_event)
    calls = {"n": 0}

    def respond(_user: str, _guard: bool) -> ModelReply:
        calls["n"] += 1
        if calls["n"] == 2:
            armed["on"] = True  # from here the interrupted-run log write will fail
            raise RuntimeError("the machine ran out of memory")
        return reply([good()])

    with pytest.raises(RuntimeError, match="out of memory"):
        run_extraction(world.store, world.snapshot_id, FakeModel(respond), sleep=no_sleep)


def test_the_provenance_sidecar_is_written_atomically(items_world: Any, tmp_path: Path) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    run_items(items, Oracle(), out, limit=1, meta={"model": "m"}, sleep=no_sleep)
    mine = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("p.jsonl"))
    assert mine == ["p.jsonl", "p.jsonl.meta.json"]  # and no .tmp left behind


def test_an_unreadable_provenance_sidecar_is_a_clear_error(
    items_world: Any, tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    run_items(items, Oracle(), out, limit=1, meta={"model": "m"}, sleep=no_sleep)
    (tmp_path / "p.jsonl.meta.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        run_items(items, Oracle(), out, meta={"model": "m"}, sleep=no_sleep)


# --- found in review: resume + limit, and a stale settings file ----------------------------------


def test_a_resume_cannot_be_combined_with_a_limit(tmp_path: Path) -> None:
    # A limit on a resume would finish the run as complete with pages unprocessed, and the run's
    # "limited" flag (set when it started) could not record that.
    world = StoreWorld(tmp_path)
    run_id = crashed_run(world)
    with pytest.raises(StoreError, match="limit"):
        run_extraction(
            world.store, world.snapshot_id, ok_model(), resume_run_id=run_id, limit=1,
            sleep=no_sleep,
        )  # fmt: skip
    assert world.store.run_meta(run_id).status == "running"  # nothing was changed


def test_settings_left_by_a_run_that_made_no_predictions_do_not_block_a_new_run(
    items_world: tuple[EvalStore, list[ItemRow]], tmp_path: Path
) -> None:
    _evals, items = items_world
    out = tmp_path / "p.jsonl"
    (tmp_path / "p.jsonl.meta.json").write_text(
        '{"model": "old"}', encoding="utf-8"
    )  # a crashed start
    run_items(items, Oracle(), out, limit=1, meta={"model": "new"}, sleep=no_sleep)
    recorded = json.loads((tmp_path / "p.jsonl.meta.json").read_text(encoding="utf-8"))
    assert recorded == {"model": "new"}
