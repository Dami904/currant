"""How often did the model copy a stored quote exactly? Offline: no key, no network.

Reads committed extraction logs (results/extract/*.jsonl) and the snapshot they ran on, and
re-runs the same checks the pipeline ran on every model-proposed claim. For each claim that would
be stored it reports whether the model's copy of the quote was byte-for-byte in the page, or
matched only up to whitespace runs and markdown backslash escapes.

Either way the quote that is stored, shown and hashed is the page's own text at the span: this
measures how loose the *match* was, not the evidence.

    uv run python scripts/quote_exactness.py snapshots/2026-11-05 \
        results/extract/20261106T115849Z-run1.jsonl \
        results/extract/20261106T124645Z-run1-resumed.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from currant.crawl.snapshot import load_manifest
from currant.extract import Accepted, locate, parse_claims, validate_proposal


def page_texts(snapshot: Path) -> dict[str, str]:
    manifest = load_manifest(snapshot)
    if manifest is None:
        raise SystemExit(f"no manifest in {snapshot}")
    return {
        page["content_sha256"]: (snapshot / page["path"]).read_bytes().decode("utf-8")
        for page in manifest["pages"]
        if page["status"] == "fetched"
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    texts = page_texts(Path(argv[0]))
    latest: dict[str, dict[str, object]] = {}
    for log in argv[1:]:  # later files win: a resumed run supersedes the failed page's row
        for line in Path(log).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("outcome") == "ok":
                latest[str(row["doc_id"])] = row
    exact = loose = missing = 0
    for doc_id, row in latest.items():
        text = texts.get(doc_id)
        if text is None:
            missing += 1
            continue
        raw = row.get("raw")
        claims = parse_claims(raw if isinstance(raw, str) else None)
        if isinstance(claims, str):
            continue
        for proposal in claims:
            if not isinstance(validate_proposal(text, proposal), Accepted):
                continue
            assert isinstance(proposal, dict)
            span = locate(text, str(proposal["quote"]))
            assert not isinstance(span, str)
            if span.exact:
                exact += 1
            else:
                loose += 1
    total = exact + loose
    print(f"pages: {len(latest)} (not in the snapshot: {missing})")
    print(f"claims that pass every check: {total}")
    if total:
        print(f"  model's copy exact:          {exact} ({exact / total:.1%})")
        print(f"  matched only loosely:        {loose} ({loose / total:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
