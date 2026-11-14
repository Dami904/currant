from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from currant import cli
from currant.evalset import (
    DEV_PERCENT,
    SPLIT_RULE_VERSION,
    EvalError,
    EvalLocked,
    EvalStore,
    assign_split,
    label_commit,
    split_for_cluster,
)

SPEC = {"stale_doc": "a" * 64, "current_doc": "b" * 64, "question": "How many free evaluations?"}
LABEL = {"relation": "supersedes", "current_value": "50"}


@pytest.fixture
def store() -> EvalStore:
    return EvalStore(":memory:")


def synthetic_clusters() -> tuple[str, str]:
    """One cluster id the rule puts in dev, one in test."""
    ids = [f"template-{i}:source-{i}" for i in range(80)]
    return (
        next(c for c in ids if split_for_cluster(c) == "dev"),
        next(c for c in ids if split_for_cluster(c) == "test"),
    )


DEV_CLUSTER, TEST_CLUSTER = synthetic_clusters()


def add(
    store: EvalStore, cluster: str, kind: str = "synthetic", *, seen: bool = False, tag: object = ""
) -> str:
    spec = {**SPEC, "n": f"{cluster}|{kind}|{seen}|{tag}"}  # a distinct spec per call
    return store.add_item(kind, cluster, spec, LABEL, seen=seen)


# --- the split rule -------------------------------------------------------------------------

GOLDEN = {
    "template-a:source-1": "dev",
    "template-a:source-2": "dev",
    "template-b:source-1": "dev",
    "fact:deepseek-removed": "test",
    "fact:reppo-free-evals": "test",
    "template-c:source-9": "test",
}


def test_the_rule_is_pinned() -> None:
    assert (SPLIT_RULE_VERSION, DEV_PERCENT) == ("cluster-sha256-v1", 60)


def test_golden_assignments() -> None:
    assert {c: split_for_cluster(c) for c in GOLDEN} == GOLDEN


def test_split_proportion_is_close_to_the_rule() -> None:
    clusters = [f"template-{i}:source-{i % 7}" for i in range(2000)]
    dev = sum(split_for_cluster(c) == "dev" for c in clusters)
    assert 0.55 < dev / len(clusters) < 0.65


def test_real_items_are_never_tuned_on_unless_already_seen() -> None:
    for cluster in (DEV_CLUSTER, TEST_CLUSTER, "anything"):
        assert assign_split("real", cluster, seen=False) == "heldout"  # whatever the hash says
        assert assign_split("real", cluster, seen=True) == "dev"
    assert assign_split("synthetic", DEV_CLUSTER, seen=False) == "dev"
    assert assign_split("synthetic", TEST_CLUSTER, seen=False) == "test"


# --- items ----------------------------------------------------------------------------------


def test_an_item_gets_its_split_from_the_rule_and_exposes_only_its_inputs(store: EvalStore) -> None:
    item_id = add(store, TEST_CLUSTER)
    (item,) = store.items()
    assert (item.item_id, item.kind, item.split, item.seen) == (item_id, "synthetic", "test", False)
    assert item.spec["question"] == SPEC["question"]
    assert "current_value" not in json.dumps(item.spec)  # the answer is not part of the inputs


def test_items_of_one_cluster_always_share_a_split(store: EvalStore) -> None:
    ids = [add(store, DEV_CLUSTER, tag=i) for i in range(3)]
    assert {i.split for i in store.items() if i.item_id in ids} == {"dev"}


def test_items_can_be_listed_by_split(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    add(store, TEST_CLUSTER)
    assert [i.split for i in store.items("dev")] == ["dev"]
    assert [i.split for i in store.items("test")] == ["test"]
    assert len(store.items()) == 2


def test_a_real_item_never_seen_is_held_out_and_a_seen_one_is_dev(store: EvalStore) -> None:
    unseen = add(store, "fact:alpha", kind="real")
    seen = add(store, "fact:beta", kind="real", seen=True)
    by_id = {i.item_id: i for i in store.items()}
    assert by_id[unseen].split == "heldout" and by_id[seen].split == "dev"


def test_a_sibling_of_a_seen_item_is_contaminated_and_becomes_dev(store: EvalStore) -> None:
    add(store, "fact:deepseek", kind="real", seen=True)
    sibling = add(store, "fact:deepseek", kind="real", tag="another page")
    item = next(i for i in store.items() if i.item_id == sibling)
    assert (item.split, item.seen) == ("dev", True)  # it was studied through its cluster
    assert any(e.kind == "item_contaminated" for e in store.events())


def test_a_seen_item_cannot_join_a_cluster_that_is_already_sealed(store: EvalStore) -> None:
    add(store, "fact:sealed", kind="real")
    with pytest.raises(EvalError, match="already holds held-out"):
        add(store, "fact:sealed", kind="real", seen=True, tag="late")


def test_an_item_cannot_be_added_twice_and_its_label_cannot_change(store: EvalStore) -> None:
    store.add_item("synthetic", DEV_CLUSTER, SPEC, LABEL)
    with pytest.raises(EvalError, match="already exists"):
        store.add_item("synthetic", DEV_CLUSTER, SPEC, {"relation": "same"})


def test_bad_input_is_refused(store: EvalStore) -> None:
    with pytest.raises(EvalError):
        store.add_item("other", "c", SPEC, LABEL)
    with pytest.raises(EvalError):
        store.add_item("synthetic", "  ", SPEC, LABEL)
    with pytest.raises(EvalError):
        store.add_item("synthetic", "c", {}, LABEL)
    with pytest.raises(EvalError):
        store.add_item("synthetic", "c", SPEC, {})


# --- sealed labels --------------------------------------------------------------------------


def test_dev_labels_are_readable_but_test_and_heldout_are_locked(store: EvalStore) -> None:
    dev = add(store, DEV_CLUSTER)
    test = add(store, TEST_CLUSTER)
    held = add(store, "fact:held", kind="real")
    assert store.label(dev) == LABEL
    for sealed in (test, held):
        with pytest.raises(EvalLocked):
            store.label(sealed)
    with pytest.raises(EvalLocked):
        store.labels("test")
    with pytest.raises(EvalLocked):
        store.labels("heldout")
    assert store.labels("dev") == {dev: LABEL}


def test_the_freeze_unlocks_every_label_and_is_permanent(store: EvalStore) -> None:
    test = add(store, TEST_CLUSTER)
    stamp = store.freeze("gate 2")
    assert store.label(test) == LABEL and store.is_frozen()
    assert store.freeze("again") == stamp
    conn = store.conn
    with pytest.raises(sqlite3.IntegrityError, match="freeze"):
        conn.execute("DELETE FROM meta WHERE key = 'frozen_at'")
    with pytest.raises(sqlite3.IntegrityError, match="freeze"):
        conn.execute("UPDATE meta SET value = 'x' WHERE key = 'frozen_at'")


def test_the_item_set_is_closed_at_the_freeze(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    store.freeze("gate 2")
    with pytest.raises(EvalError, match="closed"):
        add(store, DEV_CLUSTER, tag="late")


def test_a_label_commit_binds_the_label_to_a_salt() -> None:
    assert (
        label_commit("salt", LABEL)
        == hashlib.sha256(b'salt\n{"current_value":"50","relation":"supersedes"}').hexdigest()
    )
    assert label_commit("salt", LABEL) != label_commit("other", LABEL)
    assert label_commit("salt", {"relation": "supersedes", "current_value": "50"}) == label_commit(
        "salt", LABEL
    )  # key order does not matter


def test_the_commit_root_is_stable_and_changes_with_the_item_set(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    first = store.commit_root()
    assert store.commit_root() == first
    add(store, TEST_CLUSTER)
    assert store.commit_root() != first


def test_the_commit_root_does_not_depend_on_insertion_order() -> None:
    a, b = EvalStore(":memory:"), EvalStore(":memory:")
    items = [
        ("synthetic", DEV_CLUSTER, {**SPEC, "n": 1}),
        ("synthetic", TEST_CLUSTER, {**SPEC, "n": 2}),
    ]
    for kind, cluster, spec in items:
        a.add_item(kind, cluster, spec, LABEL, salt="s")
    for kind, cluster, spec in reversed(items):
        b.add_item(kind, cluster, spec, LABEL, salt="s")
    assert a.commit_root() == b.commit_root()


# --- the database enforces the rules ---------------------------------------------------------


def test_the_database_refuses_a_real_unseen_item_outside_heldout(store: EvalStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO items (item_id, kind, cluster_id, split, seen, spec, label_commit)"
            " VALUES ('x', 'real', 'c', 'dev', 0, '{}', ?)",
            ("0" * 64,),
        )


def test_the_database_refuses_a_synthetic_item_in_heldout(store: EvalStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO items (item_id, kind, cluster_id, split, seen, spec, label_commit)"
            " VALUES ('x', 'synthetic', 'c', 'heldout', 0, '{}', ?)",
            ("0" * 64,),
        )


def test_the_database_refuses_a_cluster_that_straddles_splits(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    with pytest.raises(sqlite3.IntegrityError, match="straddle"):
        store.conn.execute(
            "INSERT INTO items (item_id, kind, cluster_id, split, seen, spec, label_commit)"
            " VALUES ('x', 'synthetic', ?, 'test', 0, '{}', ?)",
            (DEV_CLUSTER, "0" * 64),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE items SET split = 'dev'",
        "DELETE FROM items",
        "UPDATE labels SET label = '{}'",
        "DELETE FROM labels",
        "DELETE FROM events",
        "UPDATE events SET kind = 'x'",
    ],
)
def test_items_labels_and_events_are_append_only(store: EvalStore, statement: str) -> None:
    add(store, DEV_CLUSTER)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(statement)


def test_integrity_check_catches_a_label_changed_after_sealing(store: EvalStore) -> None:
    add(store, TEST_CLUSTER)
    assert store.check_integrity() == []
    store.conn.execute("DROP TRIGGER labels_no_update")  # raw access, bypassing the guard
    store.conn.execute('UPDATE labels SET label = \'{"relation": "same"}\'')
    assert "no longer matches its commit" in "\n".join(store.check_integrity())


def test_events_record_items_and_the_freeze(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    store.freeze("gate 2")
    kinds = [e.kind for e in store.events()]
    assert kinds == ["item_added", "eval_frozen"]
    frozen = json.loads(store.events()[-1].payload)
    assert frozen["commit_root"] == store.commit_root() and frozen["items"] == 1


def test_a_file_backed_store_reopens(tmp_path: Path) -> None:
    path = tmp_path / "evalset.db"
    with EvalStore(path) as first:
        first.add_item("synthetic", DEV_CLUSTER, SPEC, LABEL)
    with EvalStore(path) as again:
        assert len(again.items()) == 1 and again.check_integrity() == []


# --- the command line ---------------------------------------------------------------------


def test_eval_freeze_needs_an_explicit_yes_and_prints_the_commit_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "evalset.db"
    with EvalStore(db) as seeded:
        seeded.add_item("synthetic", DEV_CLUSTER, SPEC, LABEL)
        root = seeded.commit_root()
    assert cli.main(["eval-freeze", "--db", str(db)]) == 2
    assert "cannot be undone" in capsys.readouterr().err
    assert cli.main(["eval-freeze", "--db", str(db), "--yes", "--note", "gate 2"]) == 0
    assert root in capsys.readouterr().out
    assert cli.main(["eval-freeze", "--db", str(db), "--yes"]) == 0  # idempotent
    with EvalStore(db) as after:
        assert after.is_frozen()


def test_eval_root_prints_the_root_and_counts_without_revealing_a_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "evalset.db"
    with EvalStore(db) as seeded:
        seeded.add_item("synthetic", DEV_CLUSTER, SPEC, LABEL)
        seeded.add_item("synthetic", TEST_CLUSTER, {**SPEC, "n": 2}, LABEL)
        seeded.add_item("real", "fact:z", {**SPEC, "n": 3}, LABEL)
        root = seeded.commit_root()
    assert cli.main(["eval-root", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert root in out and "dev: 1" in out and "test: 1" in out and "heldout: 1" in out
    assert "supersedes" not in out  # never a label


def test_the_database_refuses_new_items_and_labels_after_the_freeze(store: EvalStore) -> None:
    add(store, DEV_CLUSTER)
    store.freeze("gate 2")
    with pytest.raises(sqlite3.IntegrityError, match="closed"):
        store.conn.execute(
            "INSERT INTO items (item_id, kind, cluster_id, split, seen, spec, label_commit)"
            " VALUES ('late', 'synthetic', 'another', 'dev', 0, '{}', ?)",
            ("0" * 64,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="closed"):
        store.conn.execute("INSERT INTO labels (item_id, label, salt) VALUES ('late', '{}', 's')")
