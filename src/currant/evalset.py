"""Evaluation items and their sealed labels.

This is where the dev/test split lives. It is a split of EVALUATION ITEMS (a labelled stale-vs-
current pair, or a question about one), grouped by cluster, not a split of pages: a pair spans
two pages, so a page-level split put the two halves of the flagship pair on opposite
sides.

Rules, each enforced by code or by the database:

* A cluster is the unit of splitting: every item about one underlying fact, or built from one
  template and source page, lands on the same side. A trigger refuses a cluster that straddles.
* Synthetic items are assigned `dev` (60%) or `test` by a hash of the cluster id.
* Real items are never tuned on. A real item nobody had studied is `heldout`, always. An item
  that was studied before it was labelled (the sample drift pairs from the plan) is `dev`,
  and so is any new item that shares a cluster with one, because the cluster is contaminated.
* Each label is hash-committed (salted) when the item is created. Dev labels can be read at any
  time; test and heldout labels raise `EvalLocked` until `freeze()`, which is permanent and
  closes the item set.
* This module lives in its own database file, and pipeline code (crawl, extract, store, serv)
  must not import it: `currant.guardrails` fails CI if it does. The pipeline never sees a label.

Limit: the lock guards this API, not the file, and the commit root is self-attested. To make it
external evidence, publish `commit_root()` (a commit message, a post) before tuning starts.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from currant.obs import utc_now

SCHEMA_VERSION = 1
SPLIT_RULE_VERSION = "cluster-sha256-v1"
DEV_PERCENT = 60
KINDS = ("synthetic", "real")
SPLITS = ("dev", "test", "heldout")
FREEZE_KEY = "frozen_at"


class EvalError(RuntimeError):
    """Something the evaluation store refuses to do."""


class EvalLocked(EvalError):
    """A sealed label was requested before `freeze()`."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def split_for_cluster(cluster_id: str) -> str:
    """The synthetic-item rule: a pure function of the cluster id."""
    digest = hashlib.sha256(f"{SPLIT_RULE_VERSION}:{cluster_id}".encode()).digest()
    return "dev" if int.from_bytes(digest[:8], "big") % 100 < DEV_PERCENT else "test"


def assign_split(kind: str, cluster_id: str, *, seen: bool) -> str:
    """Real items are never tuned on, whatever the hash says: unseen means heldout, seen means
    dev. Only synthetic items are split by the hash."""
    if kind == "real":
        return "dev" if seen else "heldout"
    return split_for_cluster(cluster_id)


def label_commit(salt: str, label: dict[str, Any]) -> str:
    """SHA-256 over the salt and the canonical label: binds a label before anyone can tune."""
    return hashlib.sha256(f"{salt}\n{_canonical(label)}".encode()).hexdigest()


_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE items (
    item_id      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('synthetic', 'real')),
    cluster_id   TEXT NOT NULL CHECK (cluster_id != ''),
    split        TEXT NOT NULL CHECK (split IN ('dev', 'test', 'heldout')),
    seen         INTEGER NOT NULL CHECK (seen IN (0, 1)),
    spec         TEXT NOT NULL,
    label_commit TEXT NOT NULL CHECK (length(label_commit) = 64),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Real items are never tuned on: unseen means heldout, seen means dev. Synthetic items
    -- are dev or test, never heldout.
    CHECK ((kind = 'synthetic' AND split IN ('dev', 'test') AND seen = 0)
        OR (kind = 'real' AND ((seen = 1 AND split = 'dev') OR (seen = 0 AND split = 'heldout'))))
) WITHOUT ROWID;
CREATE INDEX items_by_cluster ON items (kind, cluster_id);

CREATE TABLE labels (
    item_id TEXT PRIMARY KEY REFERENCES items (item_id),
    label   TEXT NOT NULL,
    salt    TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    kind     TEXT NOT NULL,
    payload  TEXT NOT NULL DEFAULT '{}'
);

CREATE TRIGGER items_guard BEFORE INSERT ON items
BEGIN
    SELECT RAISE(ABORT, 'the item set is closed after the freeze')
    WHERE EXISTS (SELECT 1 FROM meta WHERE key = 'frozen_at');
    SELECT RAISE(ABORT, 'a cluster cannot straddle splits')
    WHERE EXISTS (SELECT 1 FROM items
                  WHERE kind = NEW.kind AND cluster_id = NEW.cluster_id AND split != NEW.split);
END;

CREATE TRIGGER labels_guard BEFORE INSERT ON labels
BEGIN
    SELECT RAISE(ABORT, 'the item set is closed after the freeze')
    WHERE EXISTS (SELECT 1 FROM meta WHERE key = 'frozen_at');
END;

CREATE TRIGGER meta_freeze_is_permanent BEFORE UPDATE ON meta
WHEN OLD.key = 'frozen_at'
BEGIN SELECT RAISE(ABORT, 'the evaluation freeze cannot be changed'); END;

CREATE TRIGGER meta_freeze_cannot_be_deleted BEFORE DELETE ON meta
WHEN OLD.key = 'frozen_at'
BEGIN SELECT RAISE(ABORT, 'the evaluation freeze cannot be deleted'); END;
"""

_APPEND_ONLY = ("items", "labels", "events")
_TRIGGERS = "\n".join(
    f"CREATE TRIGGER {t}_no_{verb.lower()} BEFORE {verb} ON {t}\n"
    f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;"
    for t in _APPEND_ONLY
    for verb in ("UPDATE", "DELETE")
)


@dataclass(frozen=True)
class ItemRow:
    item_id: str
    kind: str
    cluster_id: str
    split: str
    seen: bool
    spec: dict[str, Any]


@dataclass(frozen=True)
class EventRow:
    kind: str
    payload: str


class EvalStore:
    def __init__(self, path: Path | str, *, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        tables = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        if version == 0 and tables == 0:
            self.conn.executescript(_DDL + _TRIGGERS)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
        elif version != SCHEMA_VERSION:
            self.conn.close()
            raise EvalError(f"evaluation store has schema {version}, expected {SCHEMA_VERSION}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> EvalStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _ts(self) -> str:
        return self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, kind, payload) VALUES (?, ?, ?)",
            (self._ts(), kind, _canonical(payload)),
        )

    def events(self) -> list[EventRow]:
        rows = self.conn.execute("SELECT kind, payload FROM events ORDER BY event_id").fetchall()
        return [EventRow(r["kind"], r["payload"]) for r in rows]

    # --- items -------------------------------------------------------------------------

    def add_item(
        self,
        kind: str,
        cluster_id: str,
        spec: dict[str, Any],
        label: dict[str, Any],
        *,
        seen: bool = False,
        salt: str | None = None,
    ) -> str:
        """Add an item and seal its label. `spec` is the pipeline's inputs only; `label` is the
        answer and is never returned by `items()`. Returns the item id."""
        if kind not in KINDS:
            raise EvalError(f"kind must be one of {KINDS}, got {kind!r}")
        if not cluster_id.strip():
            raise EvalError("cluster_id must not be blank")
        if not spec or not label:
            raise EvalError("an item needs a non-empty spec and a non-empty label")
        if self.is_frozen():
            raise EvalError("the item set is closed after the freeze")

        contaminated = False
        if kind == "real":
            siblings = self.conn.execute(
                "SELECT split FROM items WHERE kind = 'real' AND cluster_id = ?", (cluster_id,)
            ).fetchall()
            splits = {r["split"] for r in siblings}
            if seen and "heldout" in splits:
                raise EvalError(
                    f"cluster {cluster_id!r} already holds held-out items; a seen item cannot "
                    "join it without contaminating them"
                )
            if not seen and "dev" in splits:
                seen = contaminated = True  # a sibling was studied, so this one is too
        split = assign_split(kind, cluster_id, seen=seen)

        item_id = hashlib.sha256(_canonical([kind, cluster_id, spec]).encode()).hexdigest()
        salt = salt or secrets.token_hex(16)
        commit = label_commit(salt, label)
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO items (item_id, kind, cluster_id, split, seen, spec,"
                    " label_commit, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        kind,
                        cluster_id,
                        split,
                        int(seen),
                        _canonical(spec),
                        commit,
                        self._ts(),
                    ),
                )
                self.conn.execute(
                    "INSERT INTO labels (item_id, label, salt) VALUES (?, ?, ?)",
                    (item_id, _canonical(label), salt),
                )
                self._event(
                    "item_added",
                    {"item_id": item_id, "kind": kind, "cluster_id": cluster_id, "split": split},
                )
                if contaminated:
                    self._event("item_contaminated", {"item_id": item_id, "cluster_id": cluster_id})
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise EvalError(f"item {item_id[:12]} already exists; labels never change") from exc
            raise EvalError(f"item refused: {exc}") from exc
        return item_id

    def items(self, split: str | None = None) -> list[ItemRow]:
        """Items WITHOUT their labels. Specs are the pipeline's inputs, so they are not sealed."""
        sql = "SELECT item_id, kind, cluster_id, split, seen, spec FROM items"
        args: tuple[str, ...] = ()
        if split is not None:
            sql += " WHERE split = ?"
            args = (split,)
        rows = self.conn.execute(sql + " ORDER BY item_id", args).fetchall()
        return [
            ItemRow(
                r["item_id"],
                r["kind"],
                r["cluster_id"],
                r["split"],
                bool(r["seen"]),
                json.loads(r["spec"]),
            )
            for r in rows
        ]

    # --- sealed labels -----------------------------------------------------------------

    def _read_label(self, item_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT label FROM labels WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise EvalError(f"unknown item {item_id[:12]}")
        loaded: dict[str, Any] = json.loads(row["label"])
        return loaded

    def label(self, item_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT split FROM items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise EvalError(f"unknown item {item_id[:12]}")
        if row["split"] != "dev" and not self.is_frozen():
            raise EvalLocked(
                f"the label of a {row['split']} item stays sealed until freeze(): "
                "no looking at test or held-out answers while tuning"
            )
        return self._read_label(item_id)

    def labels(self, split: str) -> dict[str, dict[str, Any]]:
        if split not in SPLITS:
            raise EvalError(f"split must be one of {SPLITS}, got {split!r}")
        if split != "dev" and not self.is_frozen():
            raise EvalLocked(f"{split} labels stay sealed until freeze()")
        return {item.item_id: self._read_label(item.item_id) for item in self.items(split)}

    def is_frozen(self) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM meta WHERE key = ?", (FREEZE_KEY,)).fetchone()
            is not None
        )

    def commit_root(self) -> str:
        """One hash over every (item, label commit), independent of insertion order. Publish it
        before tuning starts and it becomes external evidence that no label changed."""
        rows = self.conn.execute(
            "SELECT item_id, label_commit FROM items ORDER BY item_id"
        ).fetchall()
        text = "".join(f"{r['item_id']}\t{r['label_commit']}\n" for r in rows)
        return hashlib.sha256(text.encode()).hexdigest()

    def freeze(self, note: str = "") -> str:
        """Unlock test and heldout labels, permanently, and close the item set."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (FREEZE_KEY,)).fetchone()
        if row is not None:
            return str(row["value"])
        stamp = self._ts()
        with self.conn:
            self.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (FREEZE_KEY, stamp))
            self._event(
                "eval_frozen",
                {
                    "note": note,
                    "commit_root": self.commit_root(),
                    "items": self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                },
            )
        return stamp

    # --- integrity ---------------------------------------------------------------------

    def check_integrity(self) -> list[str]:
        problems: list[str] = []
        status = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            problems.append(f"sqlite integrity_check: {status}")
        for row in self.conn.execute(
            "SELECT i.item_id, i.label_commit, l.label, l.salt FROM items i"
            " JOIN labels l ON l.item_id = i.item_id"
        ):
            if label_commit(row["salt"], json.loads(row["label"])) != row["label_commit"]:
                problems.append(f"item {row['item_id'][:12]}: label no longer matches its commit")
        for row in self.conn.execute(
            "SELECT item_id FROM items WHERE item_id NOT IN (SELECT item_id FROM labels)"
        ):
            problems.append(f"item {row['item_id'][:12]}: has no label")
        for row in self.conn.execute(
            "SELECT kind, cluster_id FROM items GROUP BY kind, cluster_id"
            " HAVING COUNT(DISTINCT split) > 1"
        ):
            problems.append(f"cluster {row['cluster_id']!r} straddles splits")
        return problems
