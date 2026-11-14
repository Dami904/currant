"""SQLite schema for the claim store.

The central invariant of the project is "nothing is cut, annotated or pulled unless a verbatim
quote supporting it was verified by our own code". This schema makes SQLite enforce it, so a
bug in our Python cannot write a claim whose quote is not in its document, or mark a relation
verified without the verbatim evidence for it.

Everything is keyed by content hash. History is append-only: documents, snapshots, claims,
evidence and events can never be updated or deleted, and a decided relation is frozen.

Vocabulary: claim stances (CURRENT is the only stance that can be "the
value"), a derived per-key state (CANON / CONTESTED / UNKNOWN), and an ordering-quality field.
"""

from __future__ import annotations

SCHEMA_VERSION = 2  # v2: no page-level dev/test split (it lives on evaluation items)

# Only CURRENT claims compete to be "the value". HISTORICAL ("previously X"), PROPOSED
# ("we plan to"), REJECTED and UNCERTAIN mentions are kept but are never cut and never conflict.
STANCES = ("current", "historical", "proposed", "rejected", "uncertain")
VALUE_TYPES = ("number", "money", "duration", "count", "version", "date", "boolean", "enum", "text")
NUMERIC_VALUE_TYPES = ("number", "money", "duration", "count")
RELATION_KINDS = ("same", "supersedes", "contradicts", "unrelated")
# How the order of two values is known. 'unknown' can never support a supersession.
ORDERING_BASES = ("explicit_text", "dated", "crawl_diff", "unknown")
EVIDENCE_ROLES = ("newer", "older", "ordering", "other")
RUN_STAGES = ("extract", "relate")
RUN_STATUSES = ("running", "complete", "failed")
RELATION_STATUSES = ("proposed", "verified", "rejected")

APPEND_ONLY = (
    "documents",
    "snapshots",
    "snapshot_pages",
    "claims",
    "relation_evidence",
    "events",
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_SLICE = (
    "substr((SELECT text FROM documents WHERE doc_id = NEW.doc_id),"
    " NEW.start_char + 1, NEW.end_char - NEW.start_char)"
)
_VERIFIED_EVIDENCE = "e.relation_id = NEW.relation_id AND e.verified = 1"

_TABLES = f"""
-- Content-addressed page text. doc_id is the SHA-256 of the raw bytes, as in the crawl manifest.
CREATE TABLE documents (
    doc_id     TEXT PRIMARY KEY CHECK (length(doc_id) = 64),
    text       TEXT NOT NULL,
    n_chars    INTEGER NOT NULL CHECK (n_chars = length(text)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) WITHOUT ROWID;

CREATE TABLE snapshots (
    snapshot_id   INTEGER PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    corpus_hash   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (snapshot_date, corpus_hash)
);

-- Which content each URL had in each snapshot (the history that as-of queries need). Pages carry
-- no dev/test label: that split lives on evaluation items, in currant.evalset.
CREATE TABLE snapshot_pages (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (snapshot_id),
    url         TEXT NOT NULL,
    corpus      TEXT NOT NULL,
    doc_id      TEXT NOT NULL REFERENCES documents (doc_id),
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, url)
) WITHOUT ROWID;
CREATE INDEX snapshot_pages_doc ON snapshot_pages (snapshot_id, doc_id);

-- One row per extraction or relation-detection run: the model, prompt version and snapshot
-- every output was produced with.
CREATE TABLE runs (
    run_id         INTEGER PRIMARY KEY,
    stage          TEXT NOT NULL CHECK (stage IN {_in(RUN_STAGES)}),
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    params         TEXT NOT NULL DEFAULT '{{}}',
    snapshot_id    INTEGER NOT NULL REFERENCES snapshots (snapshot_id),
    status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN {_in(RUN_STATUSES)}),
    started_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at    TEXT
);

-- A claim is a span of a document. The quote is checked against the document text by the
-- claims_guard trigger, so a claim can only exist if its quote is verbatim.
CREATE TABLE claims (
    claim_id      TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES documents (doc_id),
    run_id        INTEGER NOT NULL REFERENCES runs (run_id),
    start_char    INTEGER NOT NULL,
    end_char      INTEGER NOT NULL,
    quote         TEXT NOT NULL,
    subject       TEXT NOT NULL,
    subject_key   TEXT NOT NULL CHECK (subject_key != ''),
    attribute     TEXT NOT NULL,
    attribute_key TEXT NOT NULL CHECK (attribute_key != ''),
    value_text    TEXT NOT NULL CHECK (value_text != ''),
    value_key     TEXT NOT NULL DEFAULT '',
    value_type    TEXT NOT NULL CHECK (value_type IN {_in(VALUE_TYPES)}),
    value_number  REAL,
    unit          TEXT,
    stance        TEXT NOT NULL CHECK (stance IN {_in(STANCES)}),
    asserted_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (start_char >= 0 AND end_char > start_char),
    CHECK (length(quote) = end_char - start_char),
    CHECK (value_number IS NULL OR value_type IN {_in(NUMERIC_VALUE_TYPES)})
);
CREATE INDEX claims_by_key ON claims (run_id, subject_key, attribute_key);
CREATE INDEX claims_by_value ON claims (run_id, attribute_key, value_key);
CREATE INDEX claims_by_doc ON claims (doc_id);

-- claim_a is the newer claim for 'supersedes' (claim_b the older). Symmetric kinds store the
-- two claim ids in sorted order so each pair exists once.
CREATE TABLE relations (
    relation_id    TEXT PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES runs (run_id),
    kind           TEXT NOT NULL CHECK (kind IN {_in(RELATION_KINDS)}),
    claim_a        TEXT NOT NULL REFERENCES claims (claim_id),
    claim_b        TEXT NOT NULL REFERENCES claims (claim_id),
    ordering_basis TEXT NOT NULL CHECK (ordering_basis IN {_in(ORDERING_BASES)}),
    status         TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN {_in(RELATION_STATUSES)}),
    reject_reason  TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    decided_at     TEXT,
    CHECK (kind != 'supersedes' OR claim_a != claim_b),
    CHECK (kind != 'supersedes' OR ordering_basis != 'unknown'),
    CHECK (kind = 'supersedes' OR claim_a < claim_b),
    UNIQUE (run_id, kind, claim_a, claim_b)
);
CREATE INDEX relations_by_status ON relations (run_id, status, kind);

-- The quotes that justify a relation. verified = 1 only if the quote is verbatim at its span;
-- an invented quote is still recorded (verified = 0) so precision can be measured, but it can
-- never support a relation.
CREATE TABLE relation_evidence (
    evidence_id INTEGER PRIMARY KEY,
    relation_id TEXT NOT NULL REFERENCES relations (relation_id),
    doc_id      TEXT NOT NULL REFERENCES documents (doc_id),
    start_char  INTEGER NOT NULL,
    end_char    INTEGER NOT NULL,
    quote       TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN {_in(EVIDENCE_ROLES)}),
    verified    INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    CHECK (start_char >= 0 AND end_char > start_char)
);
CREATE INDEX relation_evidence_by_relation ON relation_evidence (relation_id, role);

-- Append-only audit log: ingests, runs, rejected proposals, decisions.
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    kind     TEXT NOT NULL,
    run_id   INTEGER REFERENCES runs (run_id),
    payload  TEXT NOT NULL DEFAULT '{{}}'
);
"""

# Each guard is ONE trigger whose statements run in order, so the error you get is
# deterministic (SQLite does not define the firing order of separate triggers).
_TRIGGERS = f"""
CREATE TRIGGER claims_guard BEFORE INSERT ON claims
BEGIN
    SELECT RAISE(ABORT, 'claims need a running extract run')
    WHERE (SELECT stage || ':' || status FROM runs WHERE run_id = NEW.run_id)
          IS NOT 'extract:running';
    SELECT RAISE(ABORT, 'document is not part of the run snapshot')
    WHERE NOT EXISTS (
        SELECT 1 FROM runs r JOIN snapshot_pages sp ON sp.snapshot_id = r.snapshot_id
        WHERE r.run_id = NEW.run_id AND sp.doc_id = NEW.doc_id);
    SELECT RAISE(ABORT, 'quote is not verbatim document text at [start, end)')
    WHERE {_SLICE} IS NOT NEW.quote;
END;

CREATE TRIGGER relations_insert_guard BEFORE INSERT ON relations
BEGIN
    SELECT RAISE(ABORT, 'relations start as proposed') WHERE NEW.status != 'proposed';
    SELECT RAISE(ABORT, 'relations need a running relate run')
    WHERE (SELECT stage || ':' || status FROM runs WHERE run_id = NEW.run_id)
          IS NOT 'relate:running';
    SELECT RAISE(ABORT, 'both claims of a relation must exist')
    WHERE (SELECT COUNT(*) FROM claims WHERE claim_id IN (NEW.claim_a, NEW.claim_b))
          < CASE WHEN NEW.claim_a = NEW.claim_b THEN 1 ELSE 2 END;
END;

CREATE TRIGGER relation_evidence_guard BEFORE INSERT ON relation_evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence can only be added to a proposed relation')
    WHERE (SELECT status FROM relations WHERE relation_id = NEW.relation_id) IS NOT 'proposed';
    SELECT RAISE(ABORT, 'verified evidence must be verbatim document text')
    WHERE NEW.verified = 1 AND {_SLICE} IS NOT NEW.quote;
END;

-- A relation only ever moves proposed -> verified | rejected, and 'verified' needs the
-- verbatim evidence for its kind.
CREATE TRIGGER relations_guard BEFORE UPDATE ON relations
BEGIN
    SELECT RAISE(ABORT, 'relations only move proposed -> verified or rejected')
    WHERE OLD.status != 'proposed'
       OR NEW.status NOT IN ('verified', 'rejected')
       OR NEW.relation_id IS NOT OLD.relation_id
       OR NEW.run_id IS NOT OLD.run_id
       OR NEW.kind IS NOT OLD.kind
       OR NEW.claim_a IS NOT OLD.claim_a
       OR NEW.claim_b IS NOT OLD.claim_b
       OR NEW.ordering_basis IS NOT OLD.ordering_basis;
    SELECT RAISE(ABORT, 'supersedes needs verified older, newer and ordering evidence')
    WHERE NEW.status = 'verified' AND NEW.kind = 'supersedes' AND NOT (
        EXISTS (SELECT 1 FROM relation_evidence e JOIN claims c ON c.claim_id = NEW.claim_a
                WHERE {_VERIFIED_EVIDENCE} AND e.role = 'newer' AND e.doc_id = c.doc_id)
        AND EXISTS (SELECT 1 FROM relation_evidence e JOIN claims c ON c.claim_id = NEW.claim_b
                WHERE {_VERIFIED_EVIDENCE} AND e.role = 'older' AND e.doc_id = c.doc_id)
        AND (NEW.ordering_basis = 'crawl_diff'
             OR EXISTS (SELECT 1 FROM relation_evidence e
                        WHERE {_VERIFIED_EVIDENCE} AND e.role = 'ordering')));
    SELECT RAISE(ABORT, 'contradicts needs two distinct verified quotes as evidence')
    WHERE NEW.status = 'verified' AND NEW.kind = 'contradicts' AND (
        SELECT COUNT(*) FROM (
            SELECT DISTINCT e.doc_id, e.start_char, e.end_char FROM relation_evidence e
            WHERE {_VERIFIED_EVIDENCE})) < 2;
    SELECT RAISE(ABORT, 'a verified relation needs verified evidence')
    WHERE NEW.status = 'verified' AND NEW.kind IN ('same', 'unrelated') AND NOT EXISTS (
        SELECT 1 FROM relation_evidence e WHERE {_VERIFIED_EVIDENCE});
END;

CREATE TRIGGER runs_guard BEFORE UPDATE ON runs
BEGIN
    SELECT RAISE(ABORT, 'a run only moves from running to complete or failed')
    WHERE OLD.status != 'running'
       OR NEW.status NOT IN ('complete', 'failed')
       OR NEW.run_id IS NOT OLD.run_id
       OR NEW.stage IS NOT OLD.stage
       OR NEW.model IS NOT OLD.model
       OR NEW.prompt_version IS NOT OLD.prompt_version
       OR NEW.params IS NOT OLD.params
       OR NEW.snapshot_id IS NOT OLD.snapshot_id;
END;

CREATE TRIGGER relations_no_delete BEFORE DELETE ON relations
BEGIN SELECT RAISE(ABORT, 'relations cannot be deleted'); END;

CREATE TRIGGER runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'runs cannot be deleted'); END;
"""


def _append_only_triggers() -> str:
    parts = []
    for table in APPEND_ONLY:
        for verb in ("UPDATE", "DELETE"):
            parts.append(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table}\n"
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
            )
    return "\n".join(parts)


DDL = _TABLES + _TRIGGERS + _append_only_triggers()
