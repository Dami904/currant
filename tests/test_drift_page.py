"""The public drift page (docs/drift/) lists only documentation disagreements that were reported to
the maintainers, and every quote on it must be found verbatim in the committed snapshots. These
tests rebuild the page, tamper with the data, and check that each guard fails when it is removed."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "drift" / "reppo-eval-api.json"
PAGE = ROOT / "docs" / "drift" / "REPPO_EVAL_API.md"


def load_builder() -> ModuleType:
    path = ROOT / "scripts" / "build_drift_page.py"
    spec = importlib.util.spec_from_file_location("build_drift_page", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return loaded


def test_the_committed_page_is_what_the_data_builds_and_every_quote_is_verbatim() -> None:
    builder = load_builder()
    rebuilt = builder.build(data(), ROOT / "snapshots")  # raises if any quote is not verbatim
    assert PAGE.read_text(encoding="utf-8").replace("\r\n", "\n") == rebuilt


def test_a_quote_that_is_not_in_the_snapshot_page_is_refused() -> None:
    builder = load_builder()
    tampered = copy.deepcopy(data())
    tampered["findings"][0]["sides"][0]["quote"] += " (edited)"
    with pytest.raises(ValueError, match="not found verbatim"):
        builder.build(tampered, ROOT / "snapshots")


def test_a_page_outside_the_reported_hosts_is_refused() -> None:
    builder = load_builder()
    tampered = copy.deepcopy(data())
    tampered["findings"][0]["sides"][0]["url"] = (
        "https://docs.openserv.ai/vibecode/sdk/typescript.md"
    )
    with pytest.raises(ValueError, match="not a reported host"):
        builder.build(tampered, ROOT / "snapshots")


def test_a_quote_must_be_checked_in_every_snapshot_it_claims() -> None:
    # The "cap of 5" sentence exists only in the first snapshot: claiming the second must fail.
    builder = load_builder()
    tampered = copy.deepcopy(data())
    peer = next(f for f in tampered["findings"] if f["id"] == "peer-cap")
    cap5 = next(s for s in peer["sides"] if "cap of 5" in s["quote"])
    assert cap5["snapshots"] == ["2026-11-05"]
    cap5["snapshots"] = ["2026-11-05", "2026-11-11"]
    with pytest.raises(ValueError, match="not found verbatim"):
        builder.build(tampered, ROOT / "snapshots")


def test_every_finding_says_whether_it_is_a_conflict_and_why() -> None:
    kinds = {f["kind"] for f in data()["findings"]}
    assert kinds <= {"conflict", "resolved-by-removal", "not-a-conflict"}
    assert all(f["note"].strip() for f in data()["findings"])
    assert "conflict" in kinds  # the page is not only the detector's mistakes
