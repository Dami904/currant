# A receipt from real documentation

Unlike `examples/demo/` (hand-written pages), everything here comes from the real sponsor docs
crawled on 2026-11-05 (`snapshots/2026-11-05`), with claims a model extracted (`gpt-6-luna`,
`extract-v1`) and a relation the detector found and the database verified (`relate-v1`).

```bash
uv run currant replay examples/real/receipt.json --db examples/real/store.db
```

CI runs that command on every push.

- `store.db`: the 2026-11-05 snapshot, the 43 claims the extract run made on the two pages below,
  and the one verified relation between them, copied by `scripts/build_real_receipt.py`. The
  database re-checked every quote and relation as they went in.
- `receipt.json`: the receipt for "How many credits does a text-only Reppo evaluation cost?" over
  `docs.reppo.ai/api/eval/evaluations.md` and `eval.reppo.xyz/agents.md`, in `redact_pull` mode.
- `context.txt`: the exact text a model would be shown.

What the context shows: one page says 100 credits and the other says 440, and neither says which
is current, so Currant cuts nothing and marks the conflict CONTESTED with both quotes. (The live
API charged 440 on 2026-11-05 and 2026-11-11, see `docs/API_NOTES.md`, but that measurement is not
in the text, so the firewall does not claim a winner.)

Rebuilding needs the local claim store (`data/currant.db`, git-ignored), so CI only replays.
