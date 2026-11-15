"""Candidate pairing: blocked vs all-pairs, on the real claim store and at synthetic scale.

Offline: no key, no network. Two parts:

1. Real claims: every complete extract run in the store is paired both ways; the results must be
   identical, and both timings are printed.
2. Scale: N synthetic claims over a Zipf-distributed docs vocabulary (so common words are common,
   as in real pages). All-pairs is timed only while it stays under a time budget.

    uv run python scripts/bench_pairing.py --db data/currant.db
    uv run python scripts/bench_pairing.py --sizes 1000 5000 20000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path

from currant.detect import candidate_pairs, enclosing_line
from currant.store import ClaimRow, ClaimStore, StoreError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_blocking import reference_pairs  # the spec lives with its test

VOCAB_SIZE = 3000
ALL_PAIRS_BUDGET_S = 120.0


def timed[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> tuple[R, float]:
    start = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - start


def real(db: Path) -> list[dict[str, object]]:
    store = ClaimStore(db)
    rows: list[dict[str, object]] = []
    for run_id in range(1, 200):
        try:
            meta = store.run_meta(run_id)
        except StoreError:
            continue
        if meta.stage != "extract" or meta.status != "complete":
            continue
        claims = store.claims(run_id)
        lines = {}
        for c in claims:
            text = store.document_text(c.doc_id)
            lines[c.claim_id] = enclosing_line(text, c.start_char, c.end_char)
        blocked, t_new = timed(candidate_pairs, claims, max_pairs=2000, lines=lines)
        reference, t_old = timed(reference_pairs, claims, max_pairs=2000, lines=lines)
        rows.append(
            {
                "run": run_id,
                "claims": len(claims),
                "pairs": len(blocked),
                "identical": blocked == reference,
                "blocked_s": round(t_new, 3),
                "all_pairs_s": round(t_old, 3),
            }
        )
    return rows


def synthetic(n: int, seed: int = 7) -> list[ClaimRow]:
    rng = random.Random(seed)
    weights = [1 / (rank + 1) for rank in range(VOCAB_SIZE)]
    vocab = [f"w{i}" for i in range(VOCAB_SIZE)]

    def words(k: int) -> str:
        return " ".join(rng.choices(vocab, weights, k=k))

    claims = []
    for i in range(n):
        quote = f"{words(10)} {rng.randint(1, 500)}"
        claims.append(
            ClaimRow(
                f"c{i:06d}", f"d{rng.randrange(max(1, n // 8))}", 1, 0, len(quote), quote,
                words(2), "s", words(2), "a", "v", f"v{rng.randrange(50)}", "count", None, None,
                "current", None,
            )
        )  # fmt: skip
    return claims


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--sizes", type=int, nargs="*", default=[1000, 2000, 5000, 10000, 20000])
    args = parser.parse_args(argv)
    report: dict[str, object] = {}
    if args.db:
        rows = real(args.db)
        report["real"] = rows
        for entry in rows:
            print(f"real run {entry['run']}: {json.dumps(entry)}")
    scale = []
    all_pairs_ok = True
    for n in args.sizes:
        claims = synthetic(n)
        blocked, t_new = timed(candidate_pairs, claims, max_pairs=10**9)
        row: dict[str, object] = {"claims": n, "pairs": len(blocked), "blocked_s": round(t_new, 3)}
        if all_pairs_ok:
            reference, t_old = timed(reference_pairs, claims, max_pairs=10**9)
            row |= {"all_pairs_s": round(t_old, 3), "identical": blocked == reference}
            all_pairs_ok = t_old < ALL_PAIRS_BUDGET_S / 4
        scale.append(row)
        print(f"synthetic: {json.dumps(row)}", flush=True)
    report["synthetic"] = scale
    out = Path("results/scale/pairing.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
