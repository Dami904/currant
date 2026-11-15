"""Build a receipt from REAL documentation, small enough to commit, so CI can replay it.

Offline: no key, no network, no model call. It reads the local claim store (git-ignored, made by
`currant extract` and `currant relate` on the committed 2026-11-05 snapshot) and copies, into a
new store under examples/real/:

* the committed snapshot, ingested and verified as usual;
* every claim the extract run made on the chosen pages, unchanged (the store re-checks each quote
  against the page text, so nothing can be copied that is not verbatim);
* every verified relation of the relate run between those claims, with its evidence (re-verified
  by the database triggers on the way in).

Then it grounds one question over those pages and writes the receipt and the exact context.
`currant replay examples/real/receipt.json --db examples/real/store.db` checks it.

    uv run python scripts/build_real_receipt.py --src data/currant.db --extract-run 1 --relate-run 7

The question is about a conflict that is already public and measured (README, "What it
catches"): what a text-only Reppo evaluation costs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from currant.ground import Retrieved, ground
from currant.receipt import build_receipt
from currant.store import ClaimStore

SNAPSHOT = Path("snapshots/2026-11-05")
QUESTION = "How many credits does a text-only Reppo evaluation cost?"
PAGES = (
    "https://docs.reppo.ai/api/eval/evaluations.md",
    "https://eval.reppo.xyz/agents.md",
)
OUT = Path("examples/real")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--extract-run", type=int, required=True)
    parser.add_argument("--relate-run", type=int, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    src = ClaimStore(args.src)
    ex_meta, rel_meta = src.run_meta(args.extract_run), src.run_meta(args.relate_run)
    by_url = {p.url: p.doc_id for p in src.pages(ex_meta.snapshot_id)}
    docs = {by_url[url] for url in PAGES}

    args.out.mkdir(parents=True, exist_ok=True)
    db = args.out / "store.db"
    if db.exists():
        db.unlink()
    dst = ClaimStore(db)
    snapshot_id = dst.ingest_snapshot(SNAPSHOT).snapshot_id
    origin = {"copied_from_run": args.extract_run, "source": "scripts/build_real_receipt.py"}
    ex_run = dst.start_run("extract", ex_meta.model, ex_meta.prompt_version, snapshot_id, origin)
    new_id: dict[str, str] = {}
    for c in src.claims(args.extract_run):
        if c.doc_id not in docs:
            continue
        new_id[c.claim_id] = dst.add_claim(
            ex_run, doc_id=c.doc_id, start=c.start_char, end=c.end_char, quote=c.quote,
            subject=c.subject, attribute=c.attribute, value_text=c.value_text,
            value_type=c.value_type, stance=c.stance, value_number=c.value_number,
            unit=c.unit, asserted_at=c.asserted_at,
        )  # fmt: skip
    dst.finish_run(ex_run)

    origin = {"copied_from_run": args.relate_run, "source": "scripts/build_real_receipt.py"}
    rel_run = dst.start_run("relate", rel_meta.model, rel_meta.prompt_version, snapshot_id, origin)
    copied = 0
    for kind in ("supersedes", "contradicts"):
        for rel in src.verified_relations(args.relate_run, kind):
            if rel.claim_a not in new_id or rel.claim_b not in new_id:
                continue
            rid = dst.propose_relation(
                rel_run, kind, new_id[rel.claim_a], new_id[rel.claim_b], rel.ordering_basis
            )
            for ev in src.relation_evidence(rel.relation_id):
                if ev.verified:
                    dst.add_evidence(rid, ev.doc_id, ev.start_char, ev.end_char, ev.quote, ev.role)
            if not dst.verify_relation(rid):
                raise SystemExit(f"the database refused relation {rel.relation_id[:12]}")
            copied += 1
    dst.finish_run(rel_run)

    retrieved = [Retrieved(by_url[url], url) for url in PAGES]
    grounded = ground(
        dst, retrieved, mode="redact_pull", extract_run_id=ex_run, relate_run_id=rel_run
    )
    receipt = build_receipt(
        dst, grounded, question=QUESTION, extract_run_id=ex_run, relate_run_id=rel_run
    )
    (args.out / "receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (args.out / "context.txt").write_text(grounded.context, encoding="utf-8", newline="\n")
    dst.close()
    print(f"claims: {len(new_id)}  relations: {copied}  actions: {len(grounded.actions)}")
    print(f"receipt_id: {receipt['receipt_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
