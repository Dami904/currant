"""The published labels (results/labels/) must be exactly the ones sealed before the freeze.

Every label commit is recomputed from its salt and label, and the commit root over all of them
must equal the root published in the freeze note (issue #1) before the labels were unlocked. A
label edited after the freeze fails here."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from currant.evalset import label_commit

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "results" / "labels"
PUBLISHED_ROOT = "d80501c25d5033ec93e4209236764d2eb57aa16617a1d67302885a92bd984e49"  # issue #1


def rows() -> list[dict[str, object]]:
    lines = (LABELS / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_every_published_label_matches_its_sealed_commit() -> None:
    for row in rows():
        assert isinstance(row["salt"], str) and isinstance(row["label"], dict)
        assert label_commit(row["salt"], row["label"]) == row["label_commit"], row["item_id"]


def test_the_commit_root_is_the_one_published_before_the_freeze() -> None:
    ordered = sorted(rows(), key=lambda r: str(r["item_id"]))
    text = "".join(f"{r['item_id']}\t{r['label_commit']}\n" for r in ordered)
    assert hashlib.sha256(text.encode()).hexdigest() == PUBLISHED_ROOT
    manifest = json.loads((LABELS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["commit_root"] == PUBLISHED_ROOT and manifest["items"] == len(ordered)


def test_an_edited_label_would_be_caught() -> None:
    row = rows()[0]
    label = dict(cast(dict[str, object], row["label"]))
    label["expected_state"] = "CANON" if label.get("expected_state") != "CANON" else "CONTESTED"
    assert label_commit(str(row["salt"]), label) != row["label_commit"]
