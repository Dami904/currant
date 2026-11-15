"""Crawl-diff supersession: order two values by when Currant itself saw them, with no model.

When the same URL has different content in two snapshots, a value that was on the old page and
is replaced on the new page was superseded at some point between the two crawl dates. That order
comes from our own observation, not from the page's wording, so it needs no model and no
"previously" sentence.

A pair is recorded only when our code confirms all of:

* both claims are `current` statements of the same kind of value (same unit), with different
  values, and they look like the same fact (the detector's similarity, `candidate_pairs`);
* the old claim's quote is gone from the new page, and the new claim's quote is not on the old
  page (so this is an edit, not two statements that were both there);
* each claim's quote is verbatim at its span in its own page version (re-checked here, and again
  by the database when the relation is verified).

What it does not do: the relation links claims from two extract runs, so `ground` (which plans
from one run's claims) does not act on it yet. It feeds the as-of view and the drift report, and
it is a source of real supersession pairs whose order no model decided.
"""

from __future__ import annotations

from dataclasses import dataclass

from currant.detect import candidate_pairs, enclosing_line, same_kind
from currant.store import ClaimRow, ClaimStore, StoreError

PROMPT_VERSION = "crawl-diff-v1"  # recorded as the relate run's prompt version; no model is used
MODEL = "none"
MIN_SCORE = 0.30


@dataclass(frozen=True)
class ChangedPage:
    url: str
    old_doc: str
    new_doc: str


@dataclass(frozen=True)
class DiffPair:
    url: str
    older: ClaimRow
    newer: ClaimRow
    score: float


@dataclass
class DiffSummary:
    run_id: int
    changed_pages: int
    pairs: list[DiffPair]
    verified: int = 0
    refused: int = 0


@dataclass(frozen=True)
class Change:
    older_quote: str
    newer_quote: str
    seen_old: str  # snapshot date the old value was last seen
    seen_new: str  # snapshot date the new value was first seen
    relation_id: str


@dataclass(frozen=True)
class AsOf:
    url: str
    date: str
    version_date: str | None  # the latest snapshot on or before `date` that has this URL
    doc_id: str | None
    changes: list[Change]  # verified crawl-diff changes on this URL, oldest first


def as_of(store: ClaimStore, url: str, date: str) -> AsOf:
    """What Currant observed for `url` as of `date`. Only what was seen on snapshot dates is
    known: a change is placed between the last snapshot with the old value and the first with
    the new one, never at a guessed moment inside that window."""
    versions = store.conn.execute(
        "SELECT s.snapshot_date, sp.doc_id FROM snapshot_pages sp"
        " JOIN snapshots s ON s.snapshot_id = sp.snapshot_id"
        " WHERE sp.url = ? AND s.snapshot_date <= ? ORDER BY s.snapshot_date DESC LIMIT 1",
        (url, date),
    ).fetchone()
    rows = store.conn.execute(
        "SELECT r.relation_id, r.run_id, older.quote AS older_quote, newer.quote AS newer_quote"
        " FROM relations r"
        " JOIN claims newer ON newer.claim_id = r.claim_a"
        " JOIN claims older ON older.claim_id = r.claim_b"
        " JOIN runs nr ON nr.run_id = newer.run_id"
        " JOIN snapshot_pages sp ON sp.snapshot_id = nr.snapshot_id AND sp.doc_id = newer.doc_id"
        " WHERE r.kind = 'supersedes' AND r.status = 'verified'"
        " AND r.ordering_basis = 'crawl_diff' AND sp.url = ?"
        " ORDER BY r.relation_id",
        (url,),
    ).fetchall()
    changes = []
    for row in rows:
        params = store.run_meta(int(row["run_id"])).params
        changes.append(
            Change(
                str(row["older_quote"]),
                str(row["newer_quote"]),
                str(params.get("old_snapshot")),
                str(params.get("new_snapshot")),
                str(row["relation_id"]),
            )
        )
    changes.sort(key=lambda c: (c.seen_new, c.relation_id))
    return AsOf(
        url,
        date,
        str(versions["snapshot_date"]) if versions else None,
        str(versions["doc_id"]) if versions else None,
        changes,
    )


def changed_pages(store: ClaimStore, old_snapshot: int, new_snapshot: int) -> list[ChangedPage]:
    """URLs present in both snapshots whose content differs, in URL order."""
    old = {p.url: p.doc_id for p in store.pages(old_snapshot)}
    new = {p.url: p.doc_id for p in store.pages(new_snapshot)}
    return [
        ChangedPage(url, old[url], new[url])
        for url in sorted(old.keys() & new.keys())
        if old[url] != new[url]
    ]


def _verbatim(store: ClaimStore, claim: ClaimRow) -> bool:
    return store.document_text(claim.doc_id)[claim.start_char : claim.end_char] == claim.quote


def diff_pairs(
    store: ClaimStore, page: ChangedPage, old_claims: list[ClaimRow], new_claims: list[ClaimRow]
) -> list[DiffPair]:
    """Supersession pairs on one changed page. Each old claim is paired with at most one new
    claim and vice versa, best score first."""
    old_text, new_text = store.document_text(page.old_doc), store.document_text(page.new_doc)
    olds = [c for c in old_claims if c.doc_id == page.old_doc and c.stance == "current"]
    news = [c for c in new_claims if c.doc_id == page.new_doc and c.stance == "current"]
    lines = {c.claim_id: enclosing_line(old_text, c.start_char, c.end_char) for c in olds}
    lines |= {c.claim_id: enclosing_line(new_text, c.start_char, c.end_char) for c in news}
    old_ids = {c.claim_id for c in olds}
    candidates = candidate_pairs(
        [*olds, *news], min_score=MIN_SCORE, top_k=1, max_pairs=10_000, lines=lines
    )
    used: set[str] = set()
    pairs: list[DiffPair] = []
    for cand in candidates:  # best score first
        older, newer = (cand.a, cand.b) if cand.a.claim_id in old_ids else (cand.b, cand.a)
        if older.claim_id not in old_ids or newer.claim_id in old_ids:
            continue  # both from the same version
        if older.claim_id in used or newer.claim_id in used:
            continue
        if not same_kind(older, newer):
            continue
        if older.quote in new_text or newer.quote in old_text:
            continue  # not an edit: the statement is on both versions
        if not (_verbatim(store, older) and _verbatim(store, newer)):
            continue
        used.update((older.claim_id, newer.claim_id))
        pairs.append(DiffPair(page.url, older, newer, cand.score))
    return pairs


def run_crawl_diff(store: ClaimStore, old_run: int, new_run: int) -> DiffSummary:
    """Compare two complete extract runs on two snapshots and record every crawl-diff
    supersession as a verified relation in a new relate run (on the newer snapshot)."""
    old_meta, new_meta = store.run_meta(old_run), store.run_meta(new_run)
    for meta in (old_meta, new_meta):
        if meta.stage != "extract" or meta.status != "complete":
            raise StoreError(f"run {meta.run_id} is not a complete extract run")
    if not old_meta.snapshot_date < new_meta.snapshot_date:
        raise StoreError(
            f"the old run's snapshot ({old_meta.snapshot_date}) must be earlier than the new "
            f"run's ({new_meta.snapshot_date})"
        )
    pages = changed_pages(store, old_meta.snapshot_id, new_meta.snapshot_id)
    old_claims, new_claims = store.claims(old_run), store.claims(new_run)
    run_id = store.start_run(
        "relate",
        MODEL,
        PROMPT_VERSION,
        new_meta.snapshot_id,
        {
            "basis": "crawl_diff",
            "old_run": old_run,
            "new_run": new_run,
            "old_snapshot": old_meta.snapshot_date,
            "new_snapshot": new_meta.snapshot_date,
            "min_score": MIN_SCORE,
        },
    )
    summary = DiffSummary(run_id, len(pages), [])
    try:
        for page in pages:
            for pair in diff_pairs(store, page, old_claims, new_claims):
                summary.pairs.append(pair)
                rid = store.propose_relation(
                    run_id, "supersedes", pair.newer.claim_id, pair.older.claim_id, "crawl_diff"
                )
                for claim, role in ((pair.older, "older"), (pair.newer, "newer")):
                    store.add_evidence(
                        rid, claim.doc_id, claim.start_char, claim.end_char, claim.quote, role
                    )
                if store.verify_relation(rid):
                    summary.verified += 1
                else:
                    summary.refused += 1
                    store.reject_relation(rid, "the database refused the crawl-diff evidence")
    except Exception:
        store.finish_run(run_id, "failed")
        raise
    store.finish_run(run_id, "complete")
    return summary
