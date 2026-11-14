"""Build the committed demo: a tiny claim store, a receipt, and the grounded context.

Offline and deterministic: no network, no model, no key. The claims are written BY HAND here
(a model did not extract them) so that anyone can rebuild the same receipt and replay it:

    python scripts/build_demo.py            # rewrites examples/demo/
    currant replay examples/demo/receipt.json --db examples/demo/store.db

The pages are invented ("docs.example.com"), not any sponsor's documentation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from currant.detect import PROMPT_VERSION, decide, record
from currant.ground import Retrieved, ground
from currant.receipt import build_receipt
from currant.store import ClaimRow, ClaimStore

BASE = "https://docs.example.com"
LIMITS, CHANGELOG, FAQ = f"{BASE}/limits.md", f"{BASE}/changelog.md", f"{BASE}/faq.md"
RATE_OLD = "Each API key may make 60 requests per minute."
RATE_NEW = "Each API key may make 120 requests per minute."
UPLOAD_A = "Uploads can be up to 10 MB."
UPLOAD_B = "Uploads can be up to 25 MB."
REPLACES = "This replaces the previous value of 60 in earlier documentation."

PAGES = {
    LIMITS: f"# Limits\n\nRate limits and uploads.\n\n{RATE_OLD}\n\n{UPLOAD_A}\n",
    CHANGELOG: f"# Changelog\n\n{RATE_NEW}\n\n{REPLACES}\n",
    FAQ: f"# FAQ\n\n{UPLOAD_B}\n",
}
QUESTION = "What are the API rate limit and the maximum upload size?"
FIXED_TIME = datetime(2026, 11, 6, tzinfo=UTC)


def _claim(
    store: ClaimStore, run: int, url: str, sentence: str, subject: str, attribute: str,
    value_text: str, number: float, unit: str,
) -> ClaimRow:  # fmt: skip
    snapshot = store.run_meta(run).snapshot_id
    doc = next(p.doc_id for p in store.pages(snapshot) if p.url == url)
    start = PAGES[url].index(sentence)
    claim_id = store.add_claim(
        run, doc_id=doc, start=start, end=start + len(sentence), quote=sentence,
        subject=subject, attribute=attribute, value_text=value_text, value_type="count",
        value_number=number, unit=unit, stance="current",
    )  # fmt: skip
    return next(c for c in store.claims(run) if c.claim_id == claim_id)


def build(out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "store.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    store = ClaimStore(db, now=lambda: FIXED_TIME)
    snapshot = store.ingest_pages("demo", list(PAGES.items()))
    extract = store.start_run("extract", "hand-written", "demo-v1", snapshot.snapshot_id)
    rate_old = _claim(store, extract, LIMITS, RATE_OLD, "API key", "rate limit",
                      "60 requests per minute", 60, "requests per minute")  # fmt: skip
    rate_new = _claim(store, extract, CHANGELOG, RATE_NEW, "API key", "rate limit",
                      "120 requests per minute", 120, "requests per minute")  # fmt: skip
    up_a = _claim(store, extract, LIMITS, UPLOAD_A, "upload", "maximum size", "10 MB", 10, "MB")
    up_b = _claim(store, extract, FAQ, UPLOAD_B, "upload", "maximum size", "25 MB", 25, "MB")
    store.finish_run(extract)

    relate = store.start_run("relate", "hand-written", PROMPT_VERSION, snapshot.snapshot_id)
    explicit = {
        "relation": "supersedes", "basis": "explicit_text", "ordering_quote": REPLACES,
        "date_quote_a": None, "date_quote_b": None, "explanation": "the changelog says so",
    }  # fmt: skip
    cut = decide(explicit, rate_old, rate_new, PAGES[LIMITS], PAGES[CHANGELOG])
    clash = decide({"relation": "contradicts"}, up_a, up_b, PAGES[LIMITS], PAGES[FAQ])
    for decision, a, b in ((cut, rate_old, rate_new), (clash, up_a, up_b)):
        if record(store, relate, a, b, decision).outcome != "verified":
            raise RuntimeError(f"the demo relation was not verified: {decision.reason}")
    store.finish_run(relate)

    pages = [Retrieved(c.doc_id, url) for c, url in ((rate_old, LIMITS), (up_b, FAQ))]
    grounded = ground(
        store, pages, mode="redact_pull", extract_run_id=extract, relate_run_id=relate
    )
    receipt = build_receipt(
        store, grounded, question=QUESTION, extract_run_id=extract, relate_run_id=relate
    )
    store.close()
    # LF on every platform, so the file's own bytes hash to the receipt's context_sha256.
    (out_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "context.txt").write_text(grounded.context, encoding="utf-8", newline="\n")
    # The same receipt where `currant serve --receipts examples/demo/receipts` looks for it, so the
    # receipt viewer can be shown, with a live replay, without any key or network.
    kept = out_dir / "receipts"
    kept.mkdir(exist_ok=True)
    rid = str(receipt["receipt_id"])
    (kept / f"{rid}.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (kept / f"{rid}.context.txt").write_text(grounded.context, encoding="utf-8", newline="\n")
    return {"receipt_id": receipt["receipt_id"], "context_sha256": grounded.context_sha256}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out", type=Path, default=Path("examples/demo"))
    args = parser.parse_args(argv)
    result = build(args.out)
    print(f"receipt_id    {result['receipt_id']}")
    print(f"context       {result['context_sha256']}")
    print(f"wrote         {args.out}/ (store.db, receipt.json, context.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
