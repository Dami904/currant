"""The claim store: a single SQLite file holding documents, claims, relations and an audit log.

This module is a thin, typed layer over `store_schema.py`. The rules that matter (a claim's
quote is verbatim, a relation is verified only with verbatim evidence, history is append-only,
a decided relation is frozen) are enforced by the database itself, so they
hold even if code here has a bug. This layer adds friendly errors, content-hash ids, and the
derived per-key state that Ground needs.

Nothing here talks to a model or the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, NoReturn

from currant.crawl.snapshot import load_manifest, verify_snapshot
from currant.obs import utc_now
from currant.store_schema import (
    DDL,
    EVIDENCE_ROLES,
    ORDERING_BASES,
    RELATION_KINDS,
    SCHEMA_VERSION,
    STANCES,
    VALUE_TYPES,
)

__all__ = [
    "SCHEMA_VERSION",
    "ClaimRejected",
    "ClaimRow",
    "ClaimStore",
    "EventRow",
    "IngestError",
    "IngestResult",
    "KeyState",
    "PageRow",
    "RunInfo",
    "SchemaMismatch",
    "StoreError",
    "normalize_key",
    "value_key",
]

_WHITESPACE = re.compile(r"\s+")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_BY_KEY_SQL = (
    "SELECT * FROM claims WHERE run_id = ? AND subject_key = ? AND attribute_key = ?"
    " ORDER BY claim_id"
)


class StoreError(RuntimeError):
    """Something the store refuses to do."""


class ClaimRejected(StoreError):
    """A proposed claim was refused. The refusal is also written to the audit log."""


class IngestError(StoreError):
    """A snapshot could not be ingested; nothing was written."""


class SchemaMismatch(StoreError):
    """The database file was created by a different schema version."""


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: int
    pages: int
    documents_added: int
    already_ingested: bool


@dataclass(frozen=True)
class PageRow:
    url: str
    corpus: str
    doc_id: str
    fetched_at: str


@dataclass(frozen=True)
class RunInfo:
    run_id: int
    stage: str
    status: str
    snapshot_id: int


@dataclass(frozen=True)
class ClaimRow:
    claim_id: str
    doc_id: str
    run_id: int
    start_char: int
    end_char: int
    quote: str
    subject: str
    subject_key: str
    attribute: str
    attribute_key: str
    value_text: str
    value_key: str
    value_type: str
    value_number: float | None
    unit: str | None
    stance: str
    asserted_at: str | None


@dataclass(frozen=True)
class EventRow:
    event_id: int
    ts: str
    kind: str
    run_id: int | None
    payload: str


@dataclass(frozen=True)
class RelationRow:
    relation_id: str
    run_id: int
    kind: str
    claim_a: str  # for 'supersedes' the NEWER claim
    claim_b: str  # for 'supersedes' the OLDER claim
    ordering_basis: str


@dataclass(frozen=True)
class EvidenceRow:
    doc_id: str
    start_char: int
    end_char: int
    quote: str
    role: str
    verified: bool


@dataclass(frozen=True)
class RunMeta:
    run_id: int
    stage: str
    model: str
    prompt_version: str
    snapshot_id: int
    snapshot_date: str
    corpus_hash: str
    status: str
    params: dict[str, Any]


@dataclass(frozen=True)
class KeyState:
    """What the store can say about one (subject, attribute): CANON means one current value
    won on verified evidence, CONTESTED means two or more current values remain with no verified
    order between them (answer with both quotes, never guess), UNKNOWN means no claim with a
    current stance exists."""

    state: str
    current_claim_ids: tuple[str, ...]
    retired_claim_ids: tuple[str, ...]
    contested_claim_ids: tuple[str, ...]
    why: str


_MARKDOWN = re.compile(r"[*`\\]")


def normalize_key(text: str) -> str:
    """Stable lookup key: NFKC, lower case, markdown emphasis and escapes removed, whitespace
    collapsed, edge punctuation stripped. "**Base**" and "Base" are the same key."""
    folded = _MARKDOWN.sub("", unicodedata.normalize("NFKC", text)).lower()
    return _WHITESPACE.sub(" ", folded).strip(" \t\n.,;:!?")


def _unit_key(unit: str | None) -> str:
    """A unit compared as a word: 'minute' and 'minutes' are the same unit."""
    key = normalize_key(unit or "")
    return key[:-1] if len(key) > 3 and key.endswith("s") else key


def value_key(value_text: str, value_number: float | None, unit: str | None) -> str:
    """Identity of a value: numeric values compare by number and unit, others by normalised text.
    Two documents stating the same value therefore agree instead of looking like a conflict."""
    if value_number is not None:
        return f"{value_number:.12g}|{_unit_key(unit)}"
    return normalize_key(value_text)


def _hash(parts: list[Any]) -> str:
    text = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _valid_date(text: str) -> bool:
    if not _ISO_DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _claim_row(row: sqlite3.Row) -> ClaimRow:
    return ClaimRow(**{name: row[name] for name in ClaimRow.__dataclass_fields__})


class ClaimStore:
    def __init__(self, path: Path | str, *, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._open_or_create()

    # --- lifecycle ---------------------------------------------------------------------

    def _open_or_create(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        tables = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        if version == 0 and tables == 0:
            self.conn.executescript(DDL)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
        elif version != SCHEMA_VERSION:
            self.conn.close()
            raise SchemaMismatch(
                f"store has schema version {version}, this code expects {SCHEMA_VERSION}"
            )

    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ClaimStore:
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

    # --- audit log ---------------------------------------------------------------------

    def _event(self, kind: str, payload: dict[str, Any], run_id: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, kind, run_id, payload) VALUES (?, ?, ?, ?)",
            (self._ts(), kind, run_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    def log_event(self, kind: str, payload: dict[str, Any], run_id: int | None = None) -> None:
        with self.conn:
            self._event(kind, payload, run_id)

    def events(self) -> list[EventRow]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY event_id").fetchall()
        return [
            EventRow(r["event_id"], r["ts"], r["kind"], r["run_id"], r["payload"]) for r in rows
        ]

    # --- snapshots and documents -------------------------------------------------------

    def ingest_snapshot(
        self, snapshot_dir: Path, *, allow_unreconciled: bool = False
    ) -> IngestResult:
        """Load a verified crawl snapshot. Safe to repeat: a snapshot is ingested once, and a
        document whose content hash is already stored is reused, never rewritten. Pages that
        were not fetched (failed, not found, blocked) are never loaded; `allow_unreconciled`
        accepts a snapshot that still has such records, as `currant verify` does."""
        problems = verify_snapshot(snapshot_dir, allow_unreconciled=allow_unreconciled)
        if problems:
            raise IngestError("snapshot does not verify: " + "; ".join(problems[:5]))
        manifest = load_manifest(snapshot_dir)
        if manifest is None:
            raise IngestError(f"no manifest in {snapshot_dir}")
        pages = sorted((p for p in manifest["pages"] if p["status"] == "fetched"), key=_url)

        existing = self.conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE snapshot_date = ? AND corpus_hash = ?",
            (manifest["snapshot_date"], manifest["corpus_hash"]),
        ).fetchone()
        if existing is not None:
            return IngestResult(int(existing[0]), len(pages), 0, True)

        prepared: list[tuple[dict[str, Any], str]] = []
        for page in pages:
            data = (snapshot_dir / page["path"]).read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise IngestError(f"{page['url']}: not valid UTF-8 ({exc.reason})") from exc
            if "\x00" in text:
                raise IngestError(f"{page['url']}: contains a NUL character")
            prepared.append((page, text))

        added = 0
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO snapshots (snapshot_date, corpus_hash, ingested_at) VALUES (?, ?, ?)",
                (manifest["snapshot_date"], manifest["corpus_hash"], self._ts()),
            )
            snapshot_id = int(cursor.lastrowid or 0)
            for page, text in prepared:
                inserted = self.conn.execute(
                    "INSERT OR IGNORE INTO documents (doc_id, text, n_chars, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (page["content_sha256"], text, len(text), self._ts()),
                )
                added += inserted.rowcount
                self.conn.execute(
                    "INSERT INTO snapshot_pages (snapshot_id, url, corpus, doc_id, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        snapshot_id,
                        page["url"],
                        page["corpus"],
                        page["content_sha256"],
                        page["fetched_at"],
                    ),
                )
            self._event(
                "snapshot_ingested",
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_date": manifest["snapshot_date"],
                    "corpus_hash": manifest["corpus_hash"],
                    "pages": len(prepared),
                    "documents_added": added,
                },
            )
        return IngestResult(snapshot_id, len(prepared), added, False)

    def ingest_pages(self, label: str, pages: list[tuple[str, str]]) -> IngestResult:
        """Load loose pages (url, text) as a snapshot called `label`: for evaluation items, whose
        pages are not part of any crawl. Same rules as a crawl: content-addressed, idempotent."""
        by_url: dict[str, str] = {}
        for url, text in pages:
            if "\x00" in text:
                raise IngestError(f"{url}: contains a NUL character")
            by_url[url] = text
        doc_ids = {
            url: hashlib.sha256(text.encode("utf-8")).hexdigest() for url, text in by_url.items()
        }
        corpus_hash = hashlib.sha256(
            "".join(f"{url}\t{doc_ids[url]}\n" for url in sorted(doc_ids)).encode()
        ).hexdigest()
        existing = self.conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE snapshot_date = ? AND corpus_hash = ?",
            (label, corpus_hash),
        ).fetchone()
        if existing is not None:
            return IngestResult(int(existing[0]), len(by_url), 0, True)
        added = 0
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO snapshots (snapshot_date, corpus_hash, ingested_at) VALUES (?, ?, ?)",
                (label, corpus_hash, self._ts()),
            )
            snapshot_id = int(cursor.lastrowid or 0)
            for url in sorted(by_url):
                text = by_url[url]
                inserted = self.conn.execute(
                    "INSERT OR IGNORE INTO documents (doc_id, text, n_chars, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (doc_ids[url], text, len(text), self._ts()),
                )
                added += inserted.rowcount
                self.conn.execute(
                    "INSERT INTO snapshot_pages (snapshot_id, url, corpus, doc_id, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (snapshot_id, url, label, doc_ids[url], self._ts()),
                )
            self._event(
                "pages_ingested", {"label": label, "pages": len(by_url), "documents_added": added}
            )
        return IngestResult(snapshot_id, len(by_url), added, False)

    def document_text(self, doc_id: str) -> str:
        row = self.conn.execute("SELECT text FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            raise StoreError(f"unknown document {doc_id[:12]}")
        return str(row["text"])

    def pages(self, snapshot_id: int) -> list[PageRow]:
        rows = self.conn.execute(
            "SELECT url, corpus, doc_id, fetched_at FROM snapshot_pages WHERE snapshot_id = ?"
            " ORDER BY url",
            (snapshot_id,),
        ).fetchall()
        return [PageRow(r["url"], r["corpus"], r["doc_id"], r["fetched_at"]) for r in rows]

    # --- runs --------------------------------------------------------------------------

    def start_run(
        self,
        stage: str,
        model: str,
        prompt_version: str,
        snapshot_id: int,
        params: dict[str, Any] | None = None,
    ) -> int:
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "INSERT INTO runs (stage, model, prompt_version, params, snapshot_id,"
                    " started_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        stage,
                        model,
                        prompt_version,
                        json.dumps(params or {}, sort_keys=True),
                        snapshot_id,
                        self._ts(),
                    ),
                )
                run_id = int(cursor.lastrowid or 0)
                self._event(
                    "run_started",
                    {"stage": stage, "model": model, "prompt_version": prompt_version},
                    run_id,
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"cannot start run: {exc}") from exc
        return run_id

    def run_info(self, run_id: int) -> RunInfo:
        row = self.conn.execute(
            "SELECT run_id, stage, status, snapshot_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown run {run_id}")
        return RunInfo(row["run_id"], row["stage"], row["status"], row["snapshot_id"])

    def finished_documents(self, run_id: int) -> set[str]:
        """Documents a run has finished with: extracted, or skipped because the guard blocked
        them. A page that failed is not finished, so a resumed run retries it."""
        rows = self.conn.execute(
            "SELECT payload FROM events WHERE run_id = ?"
            " AND kind IN ('page_extracted', 'page_guard_blocked')",
            (run_id,),
        ).fetchall()
        return {json.loads(r["payload"])["doc_id"] for r in rows}

    def finish_run(self, run_id: int, status: str = "complete") -> None:
        try:
            with self.conn:
                changed = self.conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                    (status, self._ts(), run_id),
                ).rowcount
                if changed == 0:
                    raise StoreError(f"unknown run {run_id}")
                self._event("run_finished", {"status": status}, run_id)
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"cannot finish run {run_id}: {exc}") from exc

    # --- claims ------------------------------------------------------------------------

    def _reject_claim(self, run_id: int, reason: str, details: dict[str, Any]) -> NoReturn:
        # A refused proposal is evidence about the extractor's precision, so it is logged.
        self.log_event("claim_rejected", {"reason": reason, **details}, run_id)
        raise ClaimRejected(reason)

    def add_claim(
        self,
        run_id: int,
        *,
        doc_id: str,
        start: int,
        end: int,
        quote: str,
        subject: str,
        attribute: str,
        value_text: str,
        value_type: str,
        stance: str,
        value_number: float | None = None,
        unit: str | None = None,
        asserted_at: str | None = None,
    ) -> str:
        """Store a claim and return its id. The quote must be the exact text of the document
        at [start, end); the database refuses anything else. Adding the same claim twice
        returns the same id."""
        context = {"doc_id": doc_id, "start": start, "end": end, "quote": quote[:200]}
        subject_key, attribute_key = normalize_key(subject), normalize_key(attribute)
        if value_type not in VALUE_TYPES:
            self._reject_claim(run_id, f"unknown value_type {value_type!r}", context)
        if stance not in STANCES:
            self._reject_claim(run_id, f"unknown stance {stance!r}", context)
        if not subject_key or not attribute_key:
            self._reject_claim(run_id, "subject and attribute must not be blank", context)
        if not value_text.strip():
            self._reject_claim(run_id, "value_text must not be blank", context)
        if asserted_at is not None and not _valid_date(asserted_at):
            self._reject_claim(run_id, "asserted_at must be a real YYYY-MM-DD date", context)

        vkey = value_key(value_text, value_number, unit)
        claim_id = _hash([run_id, doc_id, start, end, subject_key, attribute_key, vkey, stance])
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO claims (claim_id, doc_id, run_id, start_char, end_char, quote,"
                    " subject, subject_key, attribute, attribute_key, value_text, value_key,"
                    " value_type, value_number, unit, stance, asserted_at, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        claim_id, doc_id, run_id, start, end, quote, subject.strip(), subject_key,
                        attribute.strip(), attribute_key, value_text.strip(), vkey, value_type,
                        value_number, unit, stance, asserted_at, self._ts(),
                    ),
                )  # fmt: skip
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: claims.claim_id" in str(exc):
                return claim_id
            self._reject_claim(run_id, str(exc), context)
        return claim_id

    def claims(self, run_id: int) -> list[ClaimRow]:
        rows = self.conn.execute(
            "SELECT * FROM claims WHERE run_id = ? ORDER BY claim_id", (run_id,)
        ).fetchall()
        return [_claim_row(r) for r in rows]

    def claims_by_key(self, run_id: int, subject: str, attribute: str) -> list[ClaimRow]:
        rows = self.conn.execute(
            _BY_KEY_SQL, (run_id, normalize_key(subject), normalize_key(attribute))
        ).fetchall()
        return [_claim_row(r) for r in rows]

    def explain_claims_by_key(self) -> str:
        """The query plan for the by-key lookup, so a test can prove it uses the index."""
        plan = self.conn.execute("EXPLAIN QUERY PLAN " + _BY_KEY_SQL, (0, "", "")).fetchall()
        return " | ".join(str(row["detail"]) for row in plan)

    def claim_run(self, claim_id: str) -> int:
        row = self.conn.execute(
            "SELECT run_id FROM claims WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown claim {claim_id[:12]}")
        return int(row["run_id"])

    # --- relations ---------------------------------------------------------------------

    def propose_relation(
        self, run_id: int, kind: str, claim_a: str, claim_b: str, ordering_basis: str
    ) -> str:
        """Record a proposed relation. For 'supersedes', claim_a is the NEWER claim. A proposal
        is never used for anything until `verify_relation` succeeds."""
        if kind not in RELATION_KINDS:
            raise StoreError(f"unknown relation kind {kind!r}")
        if ordering_basis not in ORDERING_BASES:
            raise StoreError(f"unknown ordering basis {ordering_basis!r}")
        if kind == "supersedes":
            if ordering_basis == "unknown":
                raise StoreError(
                    "a supersession needs a known ordering basis (explicit_text, dated or "
                    "crawl_diff); with no known order the honest answer is CONTESTED"
                )
        elif claim_a > claim_b:
            claim_a, claim_b = claim_b, claim_a  # symmetric kinds: one canonical row per pair
        relation_id = _hash([run_id, kind, claim_a, claim_b])
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO relations (relation_id, run_id, kind, claim_a, claim_b,"
                    " ordering_basis, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (relation_id, run_id, kind, claim_a, claim_b, ordering_basis, self._ts()),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                return relation_id
            raise StoreError(f"relation refused: {exc}") from exc
        return relation_id

    def relation_status(self, relation_id: str) -> str:
        row = self.conn.execute(
            "SELECT status FROM relations WHERE relation_id = ?", (relation_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown relation {relation_id[:12]}")
        return str(row["status"])

    def relation_run(self, relation_id: str) -> int:
        row = self.conn.execute(
            "SELECT run_id FROM relations WHERE relation_id = ?", (relation_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown relation {relation_id[:12]}")
        return int(row["run_id"])

    def add_evidence(
        self, relation_id: str, doc_id: str, start: int, end: int, quote: str, role: str
    ) -> bool:
        """Attach a quote to a proposed relation. Returns True if the quote is verbatim at its
        span. A made-up quote is still stored (unverified) so the extractor's precision can be
        measured, but it can never support a relation."""
        if role not in EVIDENCE_ROLES:
            raise StoreError(f"unknown evidence role {role!r}")
        status = self.relation_status(relation_id)
        if status != "proposed":
            raise StoreError(
                f"evidence can only be added to a proposed relation, this one is {status}"
            )
        text = self.document_text(doc_id)
        verified = 0 <= start < end <= len(text) and text[start:end] == quote
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO relation_evidence (relation_id, doc_id, start_char, end_char,"
                    " quote, role, verified) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (relation_id, doc_id, start, end, quote, role, int(verified)),
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"evidence refused: {exc}") from exc
        return verified

    def verify_relation(self, relation_id: str) -> bool:
        """Try to mark a proposed relation verified. The database decides: it refuses unless the
        verbatim evidence for the relation's kind is present, and the relation then stays
        proposed. Returns whether it is now verified."""
        status = self.relation_status(relation_id)
        if status != "proposed":
            raise StoreError(f"only a proposed relation can be verified, this one is {status}")
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE relations SET status = 'verified', decided_at = ?"
                    " WHERE relation_id = ?",
                    (self._ts(), relation_id),
                )
                self._event("relation_verified", {"relation_id": relation_id})
        except sqlite3.IntegrityError as exc:
            self.log_event(
                "relation_verification_refused", {"relation_id": relation_id, "reason": str(exc)}
            )
            return False
        return True

    def reject_relation(self, relation_id: str, reason: str) -> None:
        status = self.relation_status(relation_id)
        if status != "proposed":
            raise StoreError(f"only a proposed relation can be rejected, this one is {status}")
        with self.conn:
            self.conn.execute(
                "UPDATE relations SET status = 'rejected', reject_reason = ?, decided_at = ?"
                " WHERE relation_id = ?",
                (reason, self._ts(), relation_id),
            )
            self._event("relation_rejected", {"relation_id": relation_id, "reason": reason})

    def verified_relations(self, run_id: int, kind: str) -> list[RelationRow]:
        """Relations of one run and kind that the database accepted as verified. Anything still
        proposed, or rejected, is not returned: nothing downstream may act on it."""
        rows = self.conn.execute(
            "SELECT relation_id, run_id, kind, claim_a, claim_b, ordering_basis FROM relations"
            " WHERE run_id = ? AND kind = ? AND status = 'verified' ORDER BY relation_id",
            (run_id, kind),
        ).fetchall()
        return [
            RelationRow(r["relation_id"], r["run_id"], r["kind"], r["claim_a"], r["claim_b"],
                        r["ordering_basis"])
            for r in rows
        ]  # fmt: skip

    def relation_evidence(self, relation_id: str) -> list[EvidenceRow]:
        rows = self.conn.execute(
            "SELECT doc_id, start_char, end_char, quote, role, verified FROM relation_evidence"
            " WHERE relation_id = ? ORDER BY evidence_id",
            (relation_id,),
        ).fetchall()
        return [
            EvidenceRow(r["doc_id"], r["start_char"], r["end_char"], r["quote"], r["role"],
                        bool(r["verified"]))
            for r in rows
        ]  # fmt: skip

    def run_meta(self, run_id: int) -> RunMeta:
        row = self.conn.execute(
            "SELECT r.run_id, r.stage, r.model, r.prompt_version, r.snapshot_id,"
            " s.snapshot_date, s.corpus_hash, r.status, r.params"
            " FROM runs r JOIN snapshots s USING (snapshot_id)"
            " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"unknown run {run_id}")
        return RunMeta(row["run_id"], row["stage"], row["model"], row["prompt_version"],
                       row["snapshot_id"], row["snapshot_date"], row["corpus_hash"],
                       row["status"], json.loads(row["params"]))  # fmt: skip

    def has_page(self, snapshot_id: int, doc_id: str, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM snapshot_pages WHERE snapshot_id = ? AND doc_id = ? AND url = ?",
            (snapshot_id, doc_id, url),
        ).fetchone()
        return row is not None

    def url_of(self, snapshot_id: int, doc_id: str) -> str:
        """The URL a document had in a snapshot (the first, if it appeared under several)."""
        row = self.conn.execute(
            "SELECT MIN(url) AS url FROM snapshot_pages WHERE snapshot_id = ? AND doc_id = ?",
            (snapshot_id, doc_id),
        ).fetchone()
        if row is None or row["url"] is None:
            raise StoreError(f"document {doc_id[:12]} is not in snapshot {snapshot_id}")
        return str(row["url"])

    # --- derived state -----------------------------------------------------------------

    def key_state(
        self,
        extract_run_id: int,
        subject: str,
        attribute: str,
        *,
        relate_run_id: int | None,
    ) -> KeyState:
        """Resolve one (subject, attribute) from current-stance claims and VERIFIED
        supersessions only. No majority vote and no "most documents wins" tiebreak: if the
        order between two current values is not established by verified evidence, the answer is
        CONTESTED."""
        claims = [
            c
            for c in self.claims_by_key(extract_run_id, subject, attribute)
            if c.stance == "current"
        ]
        if not claims:
            return KeyState("UNKNOWN", (), (), (), "no claim with a current stance")

        values = {c.value_key for c in claims}
        if len(values) == 1:
            ids = tuple(sorted(c.claim_id for c in claims))
            return KeyState("CANON", ids, (), (), "one value is asserted as current")

        superseded: set[str] = set()
        if relate_run_id is not None:
            by_id = {c.claim_id: c for c in claims}
            rows = self.conn.execute(
                "SELECT claim_a, claim_b FROM relations"
                " WHERE run_id = ? AND kind = 'supersedes' AND status = 'verified'",
                (relate_run_id,),
            ).fetchall()
            for row in rows:
                newer, older = by_id.get(row["claim_a"]), by_id.get(row["claim_b"])
                if newer and older and newer.value_key != older.value_key:
                    superseded.add(older.value_key)

        sinks = values - superseded
        if len(sinks) == 1:
            current = tuple(sorted(c.claim_id for c in claims if c.value_key in sinks))
            retired = tuple(sorted(c.claim_id for c in claims if c.value_key not in sinks))
            return KeyState("CANON", current, retired, (), "verified supersession picks one value")

        contested_values = sinks or values  # a cycle leaves no sink: nothing is established
        contested = tuple(sorted(c.claim_id for c in claims if c.value_key in contested_values))
        retired = tuple(
            sorted(c.claim_id for c in claims if sinks and c.value_key in superseded - sinks)
        )
        why = (
            "the verified supersessions form a cycle"
            if not sinks
            else f"{len(sinks)} current values have no verified order between them"
        )
        return KeyState("CONTESTED", (), retired, contested, why)

    # --- integrity ---------------------------------------------------------------------

    def check_integrity(self) -> list[str]:
        """Re-check everything the triggers guarantee, from the data alone. Meant to catch
        corruption that bypassed them (a dropped trigger, an edited file)."""
        problems: list[str] = []
        status = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            problems.append(f"sqlite integrity_check: {status}")
        for row in self.conn.execute("PRAGMA foreign_key_check").fetchall():
            problems.append(f"foreign key violation in {row[0]} (row {row[1]})")

        texts: dict[str, str] = {}
        for doc in self.conn.execute("SELECT doc_id, text, n_chars FROM documents"):
            texts[doc["doc_id"]] = doc["text"]
            if hashlib.sha256(doc["text"].encode("utf-8")).hexdigest() != doc["doc_id"]:
                problems.append(f"document {doc['doc_id'][:12]}: text does not match its hash")
            if doc["n_chars"] != len(doc["text"]):
                problems.append(f"document {doc['doc_id'][:12]}: n_chars is wrong")

        for claim in self.conn.execute(
            "SELECT claim_id, doc_id, start_char, end_char, quote FROM claims"
        ):
            if (
                texts.get(claim["doc_id"], "")[claim["start_char"] : claim["end_char"]]
                != claim["quote"]
            ):
                problems.append(f"claim {claim['claim_id'][:12]}: quote is not verbatim")
        for ev in self.conn.execute(
            "SELECT evidence_id, doc_id, start_char, end_char, quote FROM relation_evidence"
            " WHERE verified = 1"
        ):
            if texts.get(ev["doc_id"], "")[ev["start_char"] : ev["end_char"]] != ev["quote"]:
                problems.append(f"evidence {ev['evidence_id']}: verified quote is not verbatim")
        for rel in self.conn.execute(
            "SELECT relation_id FROM relations r WHERE status = 'verified' AND NOT EXISTS"
            " (SELECT 1 FROM relation_evidence e WHERE e.relation_id = r.relation_id"
            "  AND e.verified = 1)"
        ):
            problems.append(
                f"relation {rel['relation_id'][:12]}: verified with no verified evidence"
            )
        return problems


def _url(page: dict[str, Any]) -> str:
    return str(page["url"])
