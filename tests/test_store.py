from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from currant.crawl.config import Corpus
from currant.store import (
    SCHEMA_VERSION,
    ClaimRejected,
    ClaimStore,
    IngestError,
    SchemaMismatch,
    StoreError,
    normalize_key,
    value_key,
)
from tests.helpers import md
from tests.test_crawl import crawl

BASE = "https://docs.example.com"
REPO = Path(__file__).parents[1]


OLD_URL = f"{BASE}/old.md"
NEW_URL = f"{BASE}/new.md"
OLD_TEXT = "# Limits\nNew accounts get 10 free evaluations. Cost is $0.01 per call.\n"
NEW_TEXT = "# Limits \U0001f600\nAs of Nov 5, new accounts get 50 free evaluations.\n"
OLD_QUOTE = "New accounts get 10 free evaluations."
NEW_QUOTE = "new accounts get 50 free evaluations."


class World:
    """A store holding one ingested snapshot: an older page and (optionally) a newer one."""

    def __init__(self, tmp_path: Path, *, new_page: bool = True) -> None:
        urls = (OLD_URL, NEW_URL) if new_page else (OLD_URL,)
        corpus = Corpus("docs", True, (), (f"{BASE}/",), urls, 50)
        routes = {OLD_URL: lambda: md(OLD_TEXT), NEW_URL: lambda: md(NEW_TEXT)}
        crawl(tmp_path, routes, corpora=[corpus])
        self.snapshot_dir = tmp_path / "2026-11-05"
        self.store = ClaimStore(":memory:")
        self.ingest = self.store.ingest_snapshot(self.snapshot_dir)
        self.snapshot_id = self.ingest.snapshot_id
        self.old_doc = hashlib.sha256(OLD_TEXT.encode()).hexdigest()
        self.new_doc = hashlib.sha256(NEW_TEXT.encode()).hexdigest()


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def span(text: str, quote: str) -> tuple[int, int]:
    start = text.index(quote)
    return start, start + len(quote)


def add_old_claim(w: World, run: int, **overrides: Any) -> str:
    start, end = span(OLD_TEXT, OLD_QUOTE)
    args: dict[str, Any] = {
        "doc_id": w.old_doc,
        "start": start,
        "end": end,
        "quote": OLD_QUOTE,
        "subject": "New account",
        "attribute": "free evaluations",
        "value_text": "10 free evaluations",
        "value_type": "count",
        "value_number": 10.0,
        "stance": "current",
    }
    args.update(overrides)
    return w.store.add_claim(run, **args)


def add_new_claim(w: World, run: int, **overrides: Any) -> str:
    start, end = span(NEW_TEXT, NEW_QUOTE)
    args: dict[str, Any] = {
        "doc_id": w.new_doc,
        "start": start,
        "end": end,
        "quote": NEW_QUOTE,
        "subject": "new account",
        "attribute": "Free Evaluations",
        "value_text": "50 free evaluations",
        "value_type": "count",
        "value_number": 50.0,
        "stance": "current",
    }
    args.update(overrides)
    return w.store.add_claim(run, **args)


def extract_run(w: World) -> int:
    return w.store.start_run("extract", "gpt-6-luna", "extract-v1", w.snapshot_id)


def relate_run(w: World) -> int:
    return w.store.start_run("relate", "gpt-6-luna", "relate-v1", w.snapshot_id)


# --- schema and ingest -------------------------------------------------------------------


def test_a_new_store_has_the_schema_and_reopens_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "currant.db"
    with ClaimStore(path) as store:
        assert store.schema_version() == SCHEMA_VERSION
    with ClaimStore(path) as store:  # reopening an existing store must not rebuild or fail
        assert store.check_integrity() == []


def test_a_store_from_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with ClaimStore(path):
        pass
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 99")
    raw.commit()
    raw.close()
    with pytest.raises(SchemaMismatch):
        ClaimStore(path)


def test_ingest_stores_pages_documents_and_the_corpus_hash(world: World) -> None:
    assert world.ingest.pages == 2 and world.ingest.documents_added == 2
    assert world.ingest.already_ingested is False
    assert world.store.document_text(world.old_doc) == OLD_TEXT
    pages = world.store.pages(world.snapshot_id)  # every page: nothing is held back by a lock
    assert [(p.url, p.doc_id) for p in pages] == [
        (NEW_URL, world.new_doc),
        (OLD_URL, world.old_doc),
    ]


def test_ingest_is_idempotent(world: World) -> None:
    again = world.store.ingest_snapshot(world.snapshot_dir)
    assert again.already_ingested is True and again.snapshot_id == world.snapshot_id
    assert again.documents_added == 0


def test_a_changed_page_is_a_new_document_and_the_old_one_is_kept(
    world: World, tmp_path: Path
) -> None:
    corpus = Corpus("docs", True, (), (f"{BASE}/",), (OLD_URL, NEW_URL), 50)
    routes = {OLD_URL: lambda: md(OLD_TEXT + "Edited.\n"), NEW_URL: lambda: md(NEW_TEXT)}
    later = tmp_path / "later"
    crawl(later, routes, corpora=[corpus])
    second = world.store.ingest_snapshot(later / "2026-11-05")
    assert second.snapshot_id != world.snapshot_id
    assert second.documents_added == 1  # the unchanged page is reused by content hash
    assert world.store.document_text(world.old_doc) == OLD_TEXT  # history is not rewritten


def test_a_snapshot_that_does_not_verify_is_refused(world: World, tmp_path: Path) -> None:
    for page in (world.snapshot_dir / "pages").rglob("*.md"):
        page.write_bytes(b"tampered")
    fresh = ClaimStore(":memory:")
    with pytest.raises(IngestError, match="does not verify"):
        fresh.ingest_snapshot(world.snapshot_dir)


def test_the_committed_real_snapshot_ingests_and_round_trips() -> None:
    store = ClaimStore(":memory:")
    result = store.ingest_snapshot(REPO / "snapshots" / "2026-11-05")
    assert result.pages == 132
    assert len(store.pages(result.snapshot_id)) == 132
    assert store.check_integrity() == []  # every stored text still hashes to its doc_id


# --- claims ------------------------------------------------------------------------------


def test_a_verbatim_claim_is_stored_with_its_full_value_text(world: World) -> None:
    run = extract_run(world)
    claim_id = add_old_claim(world, run)
    (row,) = world.store.claims(run)
    assert row.claim_id == claim_id
    assert (row.quote, row.value_text, row.value_number) == (OLD_QUOTE, "10 free evaluations", 10.0)
    assert (row.subject_key, row.attribute_key) == ("new account", "free evaluations")


def test_adding_the_same_claim_twice_is_idempotent(world: World) -> None:
    run = extract_run(world)
    assert add_old_claim(world, run) == add_old_claim(world, run)
    assert len(world.store.claims(run)) == 1


def test_a_non_verbatim_quote_is_rejected(world: World) -> None:
    run = extract_run(world)
    with pytest.raises(ClaimRejected, match="verbatim"):
        add_old_claim(world, run, quote="New accounts get ten free evaluations.")


def test_a_span_that_does_not_match_its_quote_is_rejected(world: World) -> None:
    run = extract_run(world)
    start, end = span(OLD_TEXT, OLD_QUOTE)
    with pytest.raises(ClaimRejected):
        add_old_claim(world, run, start=start + 1, end=end + 1)
    with pytest.raises(ClaimRejected):
        add_old_claim(world, run, start=0, end=10**6)


def test_offsets_count_characters_not_bytes_even_after_an_emoji(world: World) -> None:
    run = extract_run(world)
    assert add_new_claim(world, run)  # NEW_TEXT has an emoji before the quote
    (row,) = world.store.claims(run)
    assert NEW_TEXT[row.start_char : row.end_char] == NEW_QUOTE


def test_claims_need_a_running_extract_run_over_the_right_snapshot(world: World) -> None:
    relate = relate_run(world)
    with pytest.raises(ClaimRejected, match="running extract run"):
        add_old_claim(world, relate)
    run = extract_run(world)
    world.store.finish_run(run)
    with pytest.raises(ClaimRejected, match="running extract run"):
        add_old_claim(world, run)
    stranger = world.store.start_run("extract", "m", "p", world.snapshot_id)
    with pytest.raises(ClaimRejected, match="not part of"):
        add_old_claim(world, stranger, doc_id="0" * 64)


@pytest.mark.parametrize(
    "overrides",
    [
        {"value_type": "colour"},
        {"stance": "maybe"},
        {"stance": "future"},
        {"subject": "  "},
        {"value_text": ""},
    ],
)
def test_invalid_claim_fields_are_rejected(world: World, overrides: dict[str, Any]) -> None:
    with pytest.raises(ClaimRejected):
        add_old_claim(world, extract_run(world), **overrides)


def test_normalize_key_is_stable() -> None:
    assert normalize_key("  Free\tEvaluations. ") == "free evaluations"
    assert normalize_key("\uff26ree  evaluations") == "free evaluations"  # fullwidth F, NFKC


def test_claims_are_found_by_key_through_an_index(world: World) -> None:
    run = extract_run(world)
    add_old_claim(world, run)
    found = world.store.claims_by_key(run, "New Account", "free evaluations")
    assert len(found) == 1
    plan = world.store.explain_claims_by_key()
    assert "claims_by_key" in plan and "SCAN" not in plan


# --- the database enforces the invariants, not just the Python wrapper -------------------


def raw(world: World) -> sqlite3.Connection:
    return world.store.conn


def test_the_database_itself_rejects_a_claim_whose_quote_is_not_in_the_document(
    world: World,
) -> None:
    run = extract_run(world)
    with pytest.raises(sqlite3.IntegrityError, match="verbatim"):
        raw(world).execute(
            "INSERT INTO claims (claim_id, doc_id, run_id, start_char, end_char, quote, subject,"
            " subject_key, attribute, attribute_key, value_text, value_type, stance)"
            " VALUES ('x', ?, ?, 0, 5, 'WRONG', 's', 's', 'a', 'a', 'v', 'text', 'current')",
            (world.old_doc, run),
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE claims SET quote = 'edited'",
        "DELETE FROM claims",
        "UPDATE documents SET text = 'edited'",
        "DELETE FROM documents",
        "DELETE FROM events",
        "UPDATE events SET kind = 'edited'",
        "UPDATE relation_evidence SET quote = 'edited'",
        "DELETE FROM snapshot_pages",
        "DELETE FROM snapshots",
    ],
)
def test_history_cannot_be_rewritten_or_deleted(world: World, statement: str) -> None:
    # Every table needs at least one row, or the statement touches nothing and proves nothing.
    relation, *_ = supersedes(world)
    evidence(world, relation, "older", world.old_doc, OLD_TEXT, OLD_QUOTE)
    world.store.log_event("note", {"x": 1})
    with pytest.raises(sqlite3.IntegrityError):
        raw(world).execute(statement)


# --- relations and the verified-quote invariant ------------------------------------------


def supersedes(w: World) -> tuple[str, str, str]:
    extract = extract_run(w)
    old, new = add_old_claim(w, extract), add_new_claim(w, extract)
    relate = relate_run(w)
    relation = w.store.propose_relation(relate, "supersedes", new, old, "explicit_text")
    return relation, new, old


def evidence(w: World, relation: str, role: str, doc: str, text: str, quote: str) -> bool:
    start, end = span(text, quote)
    return w.store.add_evidence(relation, doc, start, end, quote, role)


def test_a_supersession_is_verified_only_with_verbatim_evidence_for_all_three_parts(
    world: World,
) -> None:
    relation, _new, _old = supersedes(world)
    assert world.store.verify_relation(relation) is False  # no evidence yet
    assert evidence(world, relation, "older", world.old_doc, OLD_TEXT, OLD_QUOTE)
    assert world.store.verify_relation(relation) is False  # still missing newer and ordering
    assert evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    assert world.store.verify_relation(relation) is False  # still missing the ordering evidence
    assert evidence(world, relation, "ordering", world.new_doc, NEW_TEXT, "As of Nov 5,")
    assert world.store.verify_relation(relation) is True
    assert world.store.relation_status(relation) == "verified"


def test_a_made_up_quote_is_recorded_unverified_and_cannot_support_a_relation(
    world: World,
) -> None:
    relation, *_ = supersedes(world)
    start, end = span(OLD_TEXT, OLD_QUOTE)
    ok = world.store.add_evidence(
        relation, world.old_doc, start, end, "a quote the model invented", "older"
    )
    assert ok is False  # kept for the precision count, but never counts as support
    evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    evidence(world, relation, "ordering", world.new_doc, NEW_TEXT, "As of Nov 5,")
    assert world.store.verify_relation(relation) is False


def test_evidence_from_the_wrong_document_does_not_count(world: World) -> None:
    relation, *_ = supersedes(world)
    evidence(
        world, relation, "older", world.new_doc, NEW_TEXT, NEW_QUOTE
    )  # not the old claim's doc
    evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    evidence(world, relation, "ordering", world.new_doc, NEW_TEXT, "As of Nov 5,")
    assert world.store.verify_relation(relation) is False


def test_a_crawl_diff_supersession_needs_no_ordering_quote(world: World) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    relation = world.store.propose_relation(relate_run(world), "supersedes", new, old, "crawl_diff")
    evidence(world, relation, "older", world.old_doc, OLD_TEXT, OLD_QUOTE)
    evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    assert world.store.verify_relation(relation) is True


def test_a_supersession_with_an_unknown_ordering_basis_cannot_even_be_proposed(
    world: World,
) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    with pytest.raises(StoreError):
        world.store.propose_relation(relate_run(world), "supersedes", new, old, "unknown")


def test_a_contradiction_needs_two_distinct_verbatim_quotes(world: World) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    relation = world.store.propose_relation(relate_run(world), "contradicts", old, new, "unknown")
    evidence(world, relation, "other", world.old_doc, OLD_TEXT, OLD_QUOTE)
    assert world.store.verify_relation(relation) is False  # one quote is not a CONTESTED answer
    evidence(world, relation, "other", world.new_doc, NEW_TEXT, NEW_QUOTE)
    assert world.store.verify_relation(relation) is True


def test_symmetric_relations_are_stored_once_whatever_the_argument_order(world: World) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    relate = relate_run(world)
    first = world.store.propose_relation(relate, "same", old, new, "unknown")
    second = world.store.propose_relation(relate, "same", new, old, "unknown")
    assert first == second


def test_a_decided_relation_is_frozen(world: World) -> None:
    relation, *_ = supersedes(world)
    world.store.reject_relation(relation, "classifier was wrong")
    assert world.store.relation_status(relation) == "rejected"
    with pytest.raises(StoreError):
        world.store.reject_relation(relation, "again")
    with pytest.raises(sqlite3.IntegrityError):
        raw(world).execute("UPDATE relations SET status = 'verified'")
    start, end = span(OLD_TEXT, OLD_QUOTE)
    with pytest.raises(StoreError, match="proposed"):
        world.store.add_evidence(relation, world.old_doc, start, end, OLD_QUOTE, "older")


def test_the_database_refuses_to_mark_an_unsupported_relation_verified(world: World) -> None:
    relation, *_ = supersedes(world)
    with pytest.raises(sqlite3.IntegrityError, match="evidence"):
        raw(world).execute(
            "UPDATE relations SET status = 'verified' WHERE relation_id = ?", (relation,)
        )
    with pytest.raises(sqlite3.IntegrityError):
        raw(world).execute(
            "INSERT INTO relations (relation_id, run_id, kind, claim_a, claim_b, ordering_basis,"
            " status) SELECT 'z', run_id, 'same', claim_a, claim_b, 'unknown', 'verified'"
            " FROM relations"
        )


def test_the_database_refuses_verified_evidence_with_a_wrong_quote(world: World) -> None:
    relation, *_ = supersedes(world)
    with pytest.raises(sqlite3.IntegrityError, match="verbatim"):
        raw(world).execute(
            "INSERT INTO relation_evidence (relation_id, doc_id, start_char, end_char, quote,"
            " role, verified) VALUES (?, ?, 0, 5, 'WRONG', 'older', 1)",
            (relation, world.old_doc),
        )


# --- events and integrity -----------------------------------------------------------------


def test_events_record_what_happened_in_order(world: World) -> None:
    world.store.log_event("note", {"a": 1})
    world.store.log_event("note", {"b": 2})
    kinds = [(e.kind, json.loads(e.payload)) for e in world.store.events()]
    assert kinds[0][0] == "snapshot_ingested"
    assert kinds[-2:] == [("note", {"a": 1}), ("note", {"b": 2})]


def test_integrity_check_catches_corruption_that_bypasses_the_triggers(world: World) -> None:
    run = extract_run(world)
    add_old_claim(world, run)
    assert world.store.check_integrity() == []
    conn = raw(world)
    conn.execute("DROP TRIGGER claims_no_update")  # an attacker or a bug with raw access
    conn.execute("UPDATE claims SET quote = 'New accounts get 99 free evaluations.'")
    problems = "\n".join(world.store.check_integrity())
    assert "not verbatim" in problems


def test_integrity_check_catches_edited_document_text(world: World) -> None:
    conn = raw(world)
    conn.execute("DROP TRIGGER documents_no_update")
    conn.execute("UPDATE documents SET text = 'rewritten', n_chars = 9")
    assert "hash" in "\n".join(world.store.check_integrity())


# --- stance, dating and the derived state of a claim key (ideas borrowed from Canon) ------


@pytest.mark.parametrize("stance", ["current", "historical", "proposed", "rejected", "uncertain"])
def test_every_stance_in_the_shared_vocabulary_is_accepted(world: World, stance: str) -> None:
    assert add_old_claim(world, extract_run(world), stance=stance)


def test_a_claim_can_carry_the_date_it_was_asserted(world: World) -> None:
    run = extract_run(world)
    add_old_claim(world, run, asserted_at="2026-09-11")
    (row,) = world.store.claims(run)
    assert row.asserted_at == "2026-09-11"
    with pytest.raises(ClaimRejected, match="asserted_at"):
        add_old_claim(world, run, subject="other", asserted_at="11/09/2026")


def test_the_same_value_in_two_documents_is_one_value_not_a_conflict(world: World) -> None:
    run = extract_run(world)
    a = add_old_claim(world, run)
    b = add_new_claim(world, run, value_text="10 free evaluations", value_number=10.0)
    state = world.store.key_state(run, "new account", "free evaluations", relate_run_id=None)
    assert state.state == "CANON" and set(state.current_claim_ids) == {a, b}


def test_a_key_with_no_current_claim_is_unknown(world: World) -> None:
    run = extract_run(world)
    add_old_claim(world, run, stance="historical")
    add_old_claim(
        world, run, stance="proposed", value_text="20 free evaluations", value_number=20.0
    )
    state = world.store.key_state(run, "new account", "free evaluations", relate_run_id=None)
    assert state.state == "UNKNOWN" and state.current_claim_ids == ()


def test_two_current_values_with_no_verified_order_are_contested(world: World) -> None:
    run = extract_run(world)
    old, new = add_old_claim(world, run), add_new_claim(world, run)
    state = world.store.key_state(run, "new account", "free evaluations", relate_run_id=None)
    assert state.state == "CONTESTED" and set(state.contested_claim_ids) == {old, new}


def test_an_unverified_supersession_does_not_resolve_a_conflict(world: World) -> None:
    relation, new, _old = supersedes(world)  # proposed, never verified
    relate = world.store.relation_run(relation)
    extract = world.store.claim_run(new)
    state = world.store.key_state(extract, "new account", "free evaluations", relate_run_id=relate)
    assert state.state == "CONTESTED"  # only verified relations may decide anything


def test_a_verified_supersession_makes_the_newer_value_current_and_retires_the_older(
    world: World,
) -> None:
    relation, new, old = supersedes(world)
    evidence(world, relation, "older", world.old_doc, OLD_TEXT, OLD_QUOTE)
    evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    evidence(world, relation, "ordering", world.new_doc, NEW_TEXT, "As of Nov 5,")
    assert world.store.verify_relation(relation)
    relate = world.store.relation_run(relation)
    state = world.store.key_state(
        world.store.claim_run(new),
        "new account",
        "free evaluations",
        relate_run_id=relate,
    )
    assert state.state == "CANON"
    assert state.current_claim_ids == (new,) and state.retired_claim_ids == (old,)


def test_a_historical_mention_is_neither_a_conflict_nor_retired(world: World) -> None:
    run = extract_run(world)  # "previously 10, now 50": the 10 is a historical mention
    add_old_claim(world, run, stance="historical")
    new = add_new_claim(world, run)
    state = world.store.key_state(run, "new account", "free evaluations", relate_run_id=None)
    assert state.state == "CANON" and state.current_claim_ids == (new,)
    assert state.retired_claim_ids == ()  # nothing here is eligible to be cut


def test_circular_orderings_are_contested_not_resolved(world: World) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    relate = relate_run(world)
    forward = world.store.propose_relation(relate, "supersedes", new, old, "crawl_diff")
    backward = world.store.propose_relation(relate, "supersedes", old, new, "crawl_diff")
    for rel, newer_doc, newer_text, newer_q, older_doc, older_text, older_q in (
        (forward, world.new_doc, NEW_TEXT, NEW_QUOTE, world.old_doc, OLD_TEXT, OLD_QUOTE),
        (backward, world.old_doc, OLD_TEXT, OLD_QUOTE, world.new_doc, NEW_TEXT, NEW_QUOTE),
    ):
        evidence(world, rel, "newer", newer_doc, newer_text, newer_q)
        evidence(world, rel, "older", older_doc, older_text, older_q)
        assert world.store.verify_relation(rel)
    state = world.store.key_state(extract, "new account", "free evaluations", relate_run_id=relate)
    assert state.state == "CONTESTED"


# --- gaps found by deleting each guard in turn and seeing no test fail ---------------------


def test_the_database_refuses_evidence_for_a_decided_relation(world: World) -> None:
    relation, *_ = supersedes(world)
    world.store.reject_relation(relation, "classifier was wrong")
    with pytest.raises(sqlite3.IntegrityError, match="proposed relation"):
        raw(world).execute(
            "INSERT INTO relation_evidence (relation_id, doc_id, start_char, end_char, quote,"
            " role, verified) VALUES (?, ?, 0, 5, 'x', 'older', 0)",
            (relation, world.old_doc),
        )


def test_relations_need_a_running_relate_run(world: World) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    with pytest.raises(StoreError, match="relate run"):
        world.store.propose_relation(extract, "same", old, new, "unknown")  # an extract run
    relate = relate_run(world)
    world.store.finish_run(relate)
    with pytest.raises(StoreError, match="relate run"):
        world.store.propose_relation(relate, "same", old, new, "unknown")  # a finished run


def test_a_verified_relation_cannot_be_flipped_afterwards(world: World) -> None:
    relation, *_ = supersedes(world)
    evidence(world, relation, "older", world.old_doc, OLD_TEXT, OLD_QUOTE)
    evidence(world, relation, "newer", world.new_doc, NEW_TEXT, NEW_QUOTE)
    evidence(world, relation, "ordering", world.new_doc, NEW_TEXT, "As of Nov 5,")
    assert world.store.verify_relation(relation)
    # The evidence rules would allow this; only the forward-only rule stops it.
    with pytest.raises(sqlite3.IntegrityError, match="only move"):
        raw(world).execute(
            "UPDATE relations SET status = 'rejected' WHERE relation_id = ?", (relation,)
        )


def test_a_proposed_relation_cannot_be_edited_without_being_decided(world: World) -> None:
    relation, *_ = supersedes(world)
    with pytest.raises(sqlite3.IntegrityError, match="only move"):
        raw(world).execute(
            "UPDATE relations SET reject_reason = 'x' WHERE relation_id = ?", (relation,)
        )


@pytest.mark.parametrize("kind", ["same", "unrelated"])
def test_same_and_unrelated_need_a_verbatim_quote_too(world: World, kind: str) -> None:
    extract = extract_run(world)
    old, new = add_old_claim(world, extract), add_new_claim(world, extract)
    relation = world.store.propose_relation(relate_run(world), kind, old, new, "unknown")
    assert world.store.verify_relation(relation) is False
    evidence(world, relation, "other", world.old_doc, OLD_TEXT, OLD_QUOTE)
    assert world.store.verify_relation(relation) is True


def test_a_run_only_moves_forward(world: World) -> None:
    run = extract_run(world)
    with pytest.raises(sqlite3.IntegrityError, match="running to complete"):
        raw(world).execute("UPDATE runs SET model = 'other' WHERE run_id = ?", (run,))
    world.store.finish_run(run)
    with pytest.raises(StoreError, match="cannot finish"):
        world.store.finish_run(run)
    with pytest.raises(sqlite3.IntegrityError, match="running to complete"):
        raw(world).execute("UPDATE runs SET status = 'running' WHERE run_id = ?", (run,))


def test_relations_and_runs_cannot_be_deleted(world: World) -> None:
    relation, *_ = supersedes(world)  # a relation with no evidence rows pointing at it
    conn = raw(world)
    conn.execute("PRAGMA foreign_keys = OFF")  # so only the delete trigger can be what refuses
    with pytest.raises(sqlite3.IntegrityError, match="relations cannot be deleted"):
        conn.execute("DELETE FROM relations WHERE relation_id = ?", (relation,))
    with pytest.raises(sqlite3.IntegrityError, match="runs cannot be deleted"):
        conn.execute("DELETE FROM runs")
    conn.execute("PRAGMA foreign_keys = ON")


def test_a_refused_claim_is_written_to_the_audit_log(world: World) -> None:
    run = extract_run(world)
    with pytest.raises(ClaimRejected):
        add_old_claim(world, run, quote="text that is not in the document")
    rejected = [e for e in world.store.events() if e.kind == "claim_rejected"]
    assert len(rejected) == 1
    assert "verbatim" in json.loads(rejected[0].payload)["reason"]


# --- keys ignore markdown noise and unit plurals (found on real pages) ---------------------


def test_markdown_emphasis_and_escapes_do_not_change_a_key() -> None:
    assert normalize_key("**Base**") == normalize_key("Base") == "base"
    assert normalize_key("`serv_prompt_guard`") == "serv_prompt_guard"
    assert normalize_key("\\$SERV holders") == "$serv holders"


def test_a_unit_is_the_same_in_singular_and_plural() -> None:
    assert value_key("15 minutes", 15, "minutes") == value_key("15-minute", 15, "minute")
    assert value_key("10 years", 10, "years") == value_key("10 year", 10, "year")
    assert value_key("15 minutes", 15, "minutes") != value_key("15 hours", 15, "hours")
    assert value_key("1 gas", 1, "gas") == "1|gas"  # short words are left alone
