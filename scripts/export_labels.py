"""Publish the evaluation labels after the freeze, so anyone can check them and re-score.

Offline; reads data/evalset.db (git-ignored). Refuses to run before the freeze: until then the
test labels are sealed (CLAUDE.md). Writes results/labels/:

* labels.jsonl: one line per item: item_id, kind, split, cluster_id, label, salt, label_commit.
* manifest.json: frozen_at, the commit root recorded in the freeze event, the item count.

Each label_commit is SHA-256(salt + "\n" + canonical label), and the commit root is one hash over
every (item_id, label_commit). `tests/test_published_labels.py` recomputes both from these files,
so a label edited after the freeze fails CI.

    uv run python scripts/export_labels.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from currant.evalset import EvalStore, label_commit

DB = Path("data/evalset.db")
OUT = Path("results/labels")


def main() -> int:
    evals = EvalStore(DB)
    if not evals.is_frozen():
        print("refusing: the evaluation set is not frozen, so its test labels are sealed")
        return 2
    problems = evals.check_integrity()
    if problems:
        print("refusing: " + "; ".join(problems[:5]))
        return 2
    rows = evals.conn.execute(
        "SELECT i.item_id, i.kind, i.split, i.cluster_id, i.label_commit, l.label, l.salt"
        " FROM items i JOIN labels l USING (item_id) ORDER BY i.item_id"
    ).fetchall()
    frozen = evals.conn.execute(
        "SELECT ts, payload FROM events WHERE kind = 'eval_frozen' ORDER BY event_id LIMIT 1"
    ).fetchone()
    freeze_event = json.loads(frozen["payload"])
    root = evals.commit_root()
    if freeze_event.get("commit_root") != root:
        print("refusing: the commit root no longer matches the one recorded at the freeze")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "labels.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for r in rows:
            label = json.loads(r["label"])
            assert label_commit(r["salt"], label) == r["label_commit"]
            handle.write(
                json.dumps(
                    {
                        "item_id": r["item_id"],
                        "kind": r["kind"],
                        "split": r["split"],
                        "cluster_id": r["cluster_id"],
                        "label": label,
                        "salt": r["salt"],
                        "label_commit": r["label_commit"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    manifest = {
        "frozen_at": evals.conn.execute(
            "SELECT value FROM meta WHERE key = 'frozen_at'"
        ).fetchone()[0],
        "commit_root": root,
        "items": len(rows),
        "freeze_note": freeze_event.get("note", ""),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{len(rows)} labels -> {OUT}/labels.jsonl   commit root {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
