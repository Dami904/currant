"""scripts/export_labels.py must refuse while the evaluation set is not frozen: until then the test
labels are sealed (CLAUDE.md), and publishing them would leak them."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_labels", ROOT / "scripts" / "export_labels.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_unfrozen_set_is_never_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    out = tmp_path / "labels"
    monkeypatch.setattr(module, "DB", tmp_path / "evalset.db")
    monkeypatch.setattr(module, "OUT", out)
    assert module.main() == 2
    assert "not frozen" in capsys.readouterr().out
    assert not out.exists()
