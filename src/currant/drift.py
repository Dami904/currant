"""The documentation drift report: which pages disagree, quoted, with where each quote lives.

Built from the verified relations of one relate run, so every line is a verbatim quote our code
checked against the stored page (the same rule as everything else). Two kinds of finding:

* a SUPERSESSION: a newer sentence replaces an older one, with the ordering evidence quoted;
* a CONFLICT: two current sentences disagree and nothing shows which is right.

This is a lead for a person, not a verdict. A model proposed the relation and our code verified the
quotes, but "these two sentences are about the same fact" is still the model's judgement, so every
item must be confirmed by hand against its two sources, and the maintainers told, before anything is
published (CLAUDE.md). The command therefore writes under `docs/private/` (git-ignored) unless it
is explicitly told to publish.
"""

from __future__ import annotations

from currant.store import ClaimRow, ClaimStore

HEADER = """\
# Documentation drift report (UNCONFIRMED: private until checked)

Snapshot {date} (corpus hash `{corpus}`), extract run {extract}, relate run {relate}.

Every quote below was checked verbatim against the stored page by our code. Whether two quotes are
about the same fact is a model's judgement. Confirm each item by hand against both sources and tell
the maintainers before publishing any of it.
"""


def _quote(text: str) -> str:
    return " ".join(text.split())


def _where(store: ClaimStore, snapshot_id: int, claim: ClaimRow) -> str:
    return f"{store.url_of(snapshot_id, claim.doc_id)}"


def drift_report(store: ClaimStore, extract_run_id: int, relate_run_id: int) -> str:
    meta = store.run_meta(extract_run_id)
    relate = store.run_meta(relate_run_id)
    if meta.stage != "extract" or relate.stage != "relate":
        raise ValueError("pass an extract run and a relate run")
    if relate.snapshot_id != meta.snapshot_id:
        raise ValueError("the relate run belongs to a different snapshot than the extract run")
    if relate.status != "complete":
        # Undecided pairs are missing from it: a short report would read as "no more drift".
        raise ValueError(
            f"relate run {relate_run_id} did not complete (status {relate.status}); rerun "
            "`currant relate` (decided pairs come from the cache)"
        )
    claims = {c.claim_id: c for c in store.claims(extract_run_id)}
    out = [
        HEADER.format(
            date=meta.snapshot_date,
            corpus=meta.corpus_hash,
            extract=extract_run_id,
            relate=relate_run_id,
        )
    ]

    supersessions = [
        r
        for r in store.verified_relations(relate_run_id, "supersedes")
        if r.claim_a in claims and r.claim_b in claims
    ]  # the headings count what is listed
    out.append(f"## Replaced values ({len(supersessions)})\n")
    for relation in supersessions:
        newer, older = claims[relation.claim_a], claims[relation.claim_b]
        out.append(f"### {relation.relation_id[:12]}  ({relation.ordering_basis})\n")
        out.append(
            f"- Older: “{_quote(older.quote)}”  \n  {_where(store, meta.snapshot_id, older)}"
        )
        out.append(
            f"- Newer: “{_quote(newer.quote)}”  \n  {_where(store, meta.snapshot_id, newer)}"
        )
        for row in store.relation_evidence(relation.relation_id):
            if row.verified and row.role == "ordering":  # older/newer are quoted above
                out.append(f"- Ordering evidence ({row.role}): “{_quote(row.quote)}”")
        out.append("")
    if not supersessions:
        out.append("None found.\n")

    conflicts = [
        r
        for r in store.verified_relations(relate_run_id, "contradicts")
        if r.claim_a in claims and r.claim_b in claims
    ]
    out.append(f"## Conflicts with no order ({len(conflicts)})\n")
    for relation in conflicts:
        a, b = claims[relation.claim_a], claims[relation.claim_b]
        out.append(f"### {relation.relation_id[:12]}\n")
        out.append(f"- A: “{_quote(a.quote)}”  \n  {_where(store, meta.snapshot_id, a)}")
        out.append(f"- B: “{_quote(b.quote)}”  \n  {_where(store, meta.snapshot_id, b)}")
        out.append("")
    if not conflicts:
        out.append("None found.\n")
    return "\n".join(out)
