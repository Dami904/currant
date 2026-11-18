"""Lineage: what Currant verified about a corpus, as data a page can show.

For a relate run it exports every VERIFIED relation: for a supersession, the retired claim, the
claim that replaced it and the quotes that order them, linked into chains (A replaced by B replaced
by C); for a contradiction, both sides. Proposed and rejected relations are never exported.

Every quote is checked verbatim against the stored document text at export time, not trusted from
when it was recorded. One that no longer matches stops the export: a page must not show evidence
our own code cannot re-check (the same rule `ground` applies before acting on a relation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from currant.store import ClaimRow, ClaimStore

LINEAGE_VERSION = "lineage-v1"


class LineageError(Exception):
    """The store holds something the page must not show (a quote that is no longer verbatim)."""


@dataclass(frozen=True)
class Source:
    corpus: str  # shown on the page, e.g. "OpenServ and Reppo"
    relate_run: int


def _span(
    store: ClaimStore, doc_id: str, start: int, end: int, quote: str, url: str
) -> dict[str, Any]:
    text = store.document_text(doc_id)
    if not (0 <= start < end <= len(text) and text[start:end] == quote):
        raise LineageError(f"{url}: the quote at {start}-{end} is not verbatim in the stored text")
    return {"url": url, "start": start, "end": end, "quote": quote}


def _claim(store: ClaimStore, claim_id: str) -> ClaimRow:
    row = store.conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    if row is None:
        raise LineageError(f"relation names an unknown claim {claim_id[:12]}")
    return ClaimRow(**{k: row[k] for k in ClaimRow.__dataclass_fields__})


def export(store: ClaimStore, source: Source) -> dict[str, Any]:
    """The verified relations of one relate run, with chains, every quote re-checked."""
    meta = store.run_meta(source.relate_run)
    if meta.stage != "relate" or meta.status != "complete":
        raise LineageError(f"run {source.relate_run} is not a complete relate run")
    # Any snapshot: a crawl-diff relation pairs a claim of an earlier crawl with one of this one.
    # Prefer this run's own snapshot, then the latest crawl that served the document.
    urls: dict[str, str] = {}
    crawled: dict[str, str] = {}
    for r in store.conn.execute(
        "SELECT p.doc_id, p.url, s.snapshot_date, p.snapshot_id = ? AS own FROM snapshot_pages p"
        " JOIN snapshots s USING (snapshot_id) ORDER BY own, s.snapshot_date, p.url DESC",
        (meta.snapshot_id,),
    ):
        urls[r["doc_id"]], crawled[r["doc_id"]] = r["url"], r["snapshot_date"]

    def claim_view(claim_id: str) -> dict[str, Any]:
        c = _claim(store, claim_id)
        view = _span(store, c.doc_id, c.start_char, c.end_char, c.quote, urls[c.doc_id])
        return {"id": c.claim_id, "subject": c.subject, "attribute": c.attribute,
                "value": c.value_text, "stance": c.stance, "crawled": crawled[c.doc_id],
                **view}  # fmt: skip

    def evidence(relation_id: str) -> list[dict[str, Any]]:
        out = []
        for e in store.relation_evidence(relation_id):
            if e.verified:  # unverified quotes are stored for measurement, never shown
                span = _span(store, e.doc_id, e.start_char, e.end_char, e.quote, urls[e.doc_id])
                out.append({"role": e.role, **span})
        return out

    supersedes = [
        {"relation_id": r.relation_id, "basis": r.ordering_basis, "newer": claim_view(r.claim_a),
         "older": claim_view(r.claim_b), "evidence": evidence(r.relation_id)}
        for r in store.verified_relations(source.relate_run, "supersedes")
    ]  # fmt: skip
    contested = [
        {"relation_id": r.relation_id, "a": claim_view(r.claim_a), "b": claim_view(r.claim_b),
         "evidence": evidence(r.relation_id)}
        for r in store.verified_relations(source.relate_run, "contradicts")
    ]  # fmt: skip
    return {
        "corpus": source.corpus,
        "snapshot_date": meta.snapshot_date,
        "corpus_hash": meta.corpus_hash,
        "relate_run": {"model": meta.model, "prompt_version": meta.prompt_version},
        "chains": chains(supersedes),
        "supersedes": supersedes,
        "contested": contested,
    }


def chains(supersedes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replacement chains as claim ids, oldest first. A claim replaced by two different claims has
    no single latest value: each path is listed and every path from that start is marked
    `branched`, so the page never presents one winner the data does not have (`ground` likewise
    refuses to annotate or pull through a branch). A loop is cut where it repeats."""
    newer_of: dict[str, list[str]] = {}
    has_older: set[str] = set()
    for rel in supersedes:
        newer_of.setdefault(rel["older"]["id"], []).append(rel["newer"]["id"])
        has_older.add(rel["newer"]["id"])
    out: list[dict[str, Any]] = []
    for start in sorted(set(newer_of) - has_older):
        paths: list[list[str]] = []
        stack = [[start]]
        while stack:
            path = stack.pop()
            nexts = [n for n in newer_of.get(path[-1], []) if n not in path]
            if not nexts:
                paths.append(path)
            for n in sorted(nexts, reverse=True):
                stack.append([*path, n])
        branched = len({p[-1] for p in paths}) > 1
        out.extend({"claims": p, "branched": branched} for p in paths)
    return out


VERDICTS = frozenset(
    {
        "conflict",
        "resolved-by-removal",
        "not-a-conflict",
        "changed-between-crawls",
        "genuine",
        "false-positive",
    }
)


def apply_reviews(
    corpus: dict[str, Any], reviews: dict[str, dict[str, str]], held: frozenset[str]
) -> dict[str, Any]:
    """Keep only relations a person has reviewed, each carrying its verdict; drop held ones.

    Default-deny: a verified relation with neither a review nor a hold stops the build, so a new
    detection run cannot put an unread relation (or unpublished sponsor drift) on the page.
    Chains are rebuilt from the kept replacements."""

    def reviewed(rel: dict[str, Any]) -> dict[str, Any] | None:
        rid = rel["relation_id"]
        if rid in held:
            return None
        review = reviews.get(rid)
        if review is None:
            raise LineageError(f"relation {rid[:12]} has no review: review it or hold it")
        if review.get("verdict") not in VERDICTS or not review.get("note"):
            raise LineageError(f"relation {rid[:12]}: a review needs a known verdict and a note")
        return {**rel, "review": review}

    supersedes = [r for r in map(reviewed, corpus["supersedes"]) if r is not None]
    contested = [r for r in map(reviewed, corpus["contested"]) if r is not None]
    return {**corpus, "supersedes": supersedes, "contested": contested,
            "chains": chains(supersedes)}  # fmt: skip
