"""scripts/export_labels.py must refuse while the evaluation set is not frozen: until then the test
labels are sealed (CLAUDE.md), and publishing them would leak them. After the freeze it must refuse
a label that no longer matches its sealed commit, and a commit root that moved, writing nothing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from currant.evalset import EvalStore

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_labels", ROOT / "scripts" / "export_labels.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_store(path: Path) -> None:
    store = EvalStore(path)
    for i in range(3):
        store.add_item("synthetic", f"c{i}", {"q": f"question {i}"}, {"value": i}, salt=f"s{i}")
    store.freeze("test fixture")
    store.conn.close()


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path, Path]:
    module = load()
    db, out = tmp_path / "evalset.db", tmp_path / "labels"
    monkeypatch.setattr(module, "DB", db)
    monkeypatch.setattr(module, "OUT", out)
    return module, db, out


def test_an_unfrozen_set_is_never_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, _db, out = setup(tmp_path, monkeypatch)
    assert module.main() == 2
    assert "not frozen" in capsys.readouterr().out
    assert not out.exists()


def test_a_frozen_set_exports_every_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, db, out = setup(tmp_path, monkeypatch)
    frozen_store(db)
    assert module.main() == 0
    rows = (out / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(json.loads(r)["label"]["value"] for r in rows) == [0, 1, 2]
    assert not (out / "labels.jsonl.partial").exists()


def tamper(db: Path, table: str, sql: str, args: tuple[str, ...]) -> None:
    """Edit the file as someone bypassing the store would: drop its append-only trigger first."""
    conn = EvalStore(db).conn
    with conn:
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        conn.execute(sql, args)
    conn.close()


def edit_one_label(db: Path) -> None:
    tamper(db, "labels", "UPDATE labels SET label = ? WHERE item_id = "
           "(SELECT MIN(item_id) FROM labels)", (json.dumps({"value": 99}),))  # fmt: skip


def test_an_edited_label_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, db, out = setup(tmp_path, monkeypatch)
    frozen_store(db)
    edit_one_label(db)
    assert module.main() == 2
    assert "label no longer matches its commit" in capsys.readouterr().out  # the integrity check
    assert not (out / "labels.jsonl").exists()


def test_the_per_label_check_stands_without_the_integrity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The loop before writing is its own guard, not a repeat that can be deleted safely.
    module, db, out = setup(tmp_path, monkeypatch)
    frozen_store(db)
    edit_one_label(db)
    monkeypatch.setattr(EvalStore, "check_integrity", lambda _self: [])
    assert module.main() == 2
    assert "does not match its sealed commit" in capsys.readouterr().out
    assert not (out / "labels.jsonl").exists()


def test_a_commit_root_that_moved_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, db, out = setup(tmp_path, monkeypatch)
    frozen_store(db)
    tamper(db, "events", "UPDATE events SET payload = ? WHERE kind = 'eval_frozen'",
           (json.dumps({"note": "", "commit_root": "0" * 64}),))  # fmt: skip
    assert module.main() == 2
    assert "commit root" in capsys.readouterr().out
    assert not (out / "labels.jsonl").exists()
