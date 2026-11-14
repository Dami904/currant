from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.store import ClaimStore
from tests.test_cli import patch_network
from tests.test_detect import explicit_answer
from tests.test_ground import R10, S10, S50, U1, U2, World, simple


def to_disk(world: World, path: Path) -> Path:
    world.finish()
    target = sqlite3.connect(path)
    world.store.conn.backup(target)
    target.close()
    return path


def ground_args(world: World, db: Path, out: Path, *extra: str) -> list[str]:
    return [
        "ground", "--db", str(db), "--extract-run", str(world.extract),
        "--relate-run", str(world.relate), "--question", "how many free evaluations?",
        "--out", str(out), *extra,
    ]  # fmt: skip


def test_ground_writes_a_receipt_and_the_context_and_replay_accepts_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db, receipt, context = tmp_path / "c.db", tmp_path / "r.json", tmp_path / "ctx.txt"
    to_disk(world, db)
    args = ground_args(world, db, receipt, "--mode", "redact", "--url", U1, "--url", U2,
                       "--context-out", str(context))  # fmt: skip
    assert cli.main(args) == 0
    shown = capsys.readouterr().out
    assert "redact" in shown and "receipt_id" in shown
    assert S10 not in context.read_text(encoding="utf-8") and S50 in context.read_text("utf-8")
    assert cli.main(["replay", str(receipt), "--db", str(db)]) == 0
    assert "REPLAY OK" in capsys.readouterr().out


def test_replay_rejects_an_edited_receipt_with_exit_code_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db, receipt = tmp_path / "c.db", tmp_path / "r.json"
    to_disk(world, db)
    assert cli.main(ground_args(world, db, receipt, "--mode", "redact", "--url", U1)) == 0
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["mode"] = "baseline"
    receipt.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["replay", str(receipt), "--db", str(db)]) == 1
    assert "REPLAY FAILED" in capsys.readouterr().out


def test_replay_of_an_unreadable_file_is_a_usage_error_not_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db = to_disk(world, tmp_path / "c.db")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cli.main(["replay", str(bad), "--db", str(db)]) == 2
    assert cli.main(["replay", str(tmp_path / "missing.json"), "--db", str(db)]) == 2
    assert "error" in capsys.readouterr().err


def test_ground_refuses_a_url_that_is_not_in_the_run_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db = to_disk(world, tmp_path / "c.db")
    args = ground_args(world, db, tmp_path / "r.json", "--mode", "redact", "--url", "https://x/y")
    assert cli.main(args) == 2
    assert "not in the snapshot" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()  # no receipt for a refused request


def test_ground_refuses_a_missing_database_instead_of_creating_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.db"
    out = str(tmp_path / "r.json")
    args = ["ground", "--db", str(missing), "--extract-run", "1", "--relate-run", "2"]
    code = cli.main([*args, "--question", "q", "--out", out, "--url", U1])
    assert code == 2 and not missing.exists()
    assert "no claim store" in capsys.readouterr().err


def test_relate_runs_the_detector_over_an_extract_run_and_stores_verified_relations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    texts = simple().texts
    world = World((U1, texts[U1], S10, 10, "current"), (U2, texts[U2], S50, 50, "current"))
    db = to_disk(world, tmp_path / "c.db")
    reply = explicit_answer(ordering_quote=R10)

    def handler(_request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {
            "choices": [{"message": {"content": json.dumps(reply)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
        return httpx.Response(200, json=body)

    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(handler))
    cache, dotenv = str(tmp_path / "cache.db"), str(tmp_path / "no.env")
    args = ["relate", "--db", str(db), "--extract-run", str(world.extract)]
    code = cli.main([*args, "--cache", cache, "--dotenv", dotenv])
    assert code == 0
    assert "supersedes" in capsys.readouterr().out
    store = ClaimStore(db)
    runs = [
        r["run_id"] for r in store.conn.execute("SELECT run_id FROM runs WHERE stage = 'relate'")
    ]
    new_run = max(runs)
    assert new_run != world.relate and len(store.verified_relations(new_run, "supersedes")) == 1


def test_relate_refuses_a_run_that_is_not_an_extract_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db = to_disk(world, tmp_path / "c.db")
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    cache, dotenv = str(tmp_path / "cache.db"), str(tmp_path / "no.env")
    args = ["relate", "--db", str(db), "--extract-run", str(world.relate)]
    code = cli.main([*args, "--cache", cache, "--dotenv", dotenv])
    assert code == 2 and "not an extract run" in capsys.readouterr().err


# --- ground without --url retrieves the pages from the question ---------------------------------


def test_ground_retrieves_the_pages_when_no_url_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db, receipt = tmp_path / "c.db", tmp_path / "r.json"
    to_disk(world, db)
    args = ground_args(world, db, receipt, "--mode", "redact")
    assert cli.main(args) == 0
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert {d["url"] for d in data["documents"]} == {U1, U2}  # both mention free evaluations
    assert cli.main(["replay", str(receipt), "--db", str(db)]) == 0
    assert "retrieved" in capsys.readouterr().out


def test_top_k_limits_how_many_pages_are_retrieved(tmp_path: Path) -> None:
    world = simple()
    db, receipt = tmp_path / "c.db", tmp_path / "r.json"
    to_disk(world, db)
    assert cli.main(ground_args(world, db, receipt, "--top-k", "1")) == 0
    assert len(json.loads(receipt.read_text(encoding="utf-8"))["documents"]) == 1


def test_a_question_that_matches_no_page_is_an_error_not_an_empty_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db, receipt = tmp_path / "c.db", tmp_path / "r.json"
    to_disk(world, db)
    args = ground_args(world, db, receipt)
    args[args.index("how many free evaluations?")] = "zebra quasar xylophone"
    assert cli.main(args) == 2
    assert "no page matched" in capsys.readouterr().err and not receipt.exists()


def test_choosing_pages_and_retrieving_at_once_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = simple()
    db, receipt = tmp_path / "c.db", tmp_path / "r.json"
    to_disk(world, db)
    assert cli.main(ground_args(world, db, receipt, "--url", U1, "--top-k", "3")) == 2
    assert "not both" in capsys.readouterr().err
