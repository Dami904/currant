from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from currant import cli
from currant.evalset import EvalStore, ItemRow
from currant.harness.synth import generate
from tests.test_arms import ArmsModel
from tests.test_cli import patch_network
from tests.test_harness import chat_handler
from tests.test_synth import Built


@pytest.fixture
def evalset(tmp_path: Path) -> Path:
    evals = EvalStore(":memory:")
    built = Built(tmp_path / "built")
    generate(built.store, built.run, evals, seed=1, n_supersede=6, n_clean=4)
    disk = sqlite3.connect(tmp_path / "evalset.db")
    evals.conn.backup(disk)
    disk.close()
    return tmp_path / "evalset.db"


def dev_items(db: Path) -> list[ItemRow]:
    with EvalStore(db) as evals:
        return evals.items("dev")


def arms_args(db: Path, tmp_path: Path, out: Path, *extra: str) -> list[str]:
    return [
        "run-arms", "--evalset", str(db), "--split", "dev", "--out", str(out),
        "--cache", str(tmp_path / "cache.db"), "--dotenv", str(tmp_path / "no.env"), *extra,
    ]  # fmt: skip


def test_run_then_score_arms_through_the_command_line(
    evalset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    seen: list[int] = []
    patch_network(monkeypatch, httpx.MockTransport(chat_handler(ArmsModel(), seen)))
    out = tmp_path / "arms.jsonl"
    args = arms_args(evalset, tmp_path, out, "--ks", "2", "--arms", "baseline,redact")
    assert cli.main(args) == 0
    shown = capsys.readouterr().out
    assert "model calls:" in shown and "raw outputs:" in shown
    meta = json.loads(out.with_name(out.name + ".meta.json").read_text(encoding="utf-8"))
    assert meta["arms"] == ["baseline", "redact"] and meta["ks"] == [2]
    assert {"model", "answer_prompt", "extract_prompt", "relate_prompt", "retrieval"} <= set(meta)
    assert out.with_name(out.name + ".raw.jsonl").exists()
    first_calls = len(seen)
    assert cli.main(args) == 0  # everything finished: nothing left to run, nothing sent
    assert len(seen) == first_calls

    assert cli.main(["score-arms", "--evalset", str(evalset), "--predictions", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "baseline" in printed and "redact" in printed and "unpredicted" in printed


def test_run_arms_refuses_unfrozen_test_items(
    evalset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = arms_args(evalset, tmp_path, tmp_path / "a.jsonl")
    args[args.index("dev")] = "test"
    assert cli.main(args) == 2 and "before the freeze" in capsys.readouterr().err


def test_score_arms_refuses_unfrozen_test_labels(
    evalset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = tmp_path / "p.jsonl"
    preds.write_text("", encoding="utf-8")
    code = cli.main(
        ["score-arms", "--evalset", str(evalset), "--predictions", str(preds), "--split", "test"]
    )
    assert code == 2 and "sealed" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [["--arms", "baseline,shred"], ["--ks", "0"], ["--repeats", "0"]])
def test_bad_options_are_usage_errors(evalset: Path, tmp_path: Path, bad: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(arms_args(evalset, tmp_path, tmp_path / "a.jsonl", *bad))
    assert raised.value.code == 2


def test_run_arms_reports_an_unwritable_output_location(
    evalset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file", encoding="utf-8")
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(monkeypatch, httpx.MockTransport(lambda _r: httpx.Response(500)))
    args = arms_args(evalset, tmp_path, blocker / "a.jsonl")
    assert cli.main(args) == 2 and "error" in capsys.readouterr().err
