# Demo

A tiny, fully offline example of what Currant produces. No key, no network, no model.

```bash
uv run currant replay examples/demo/receipt.json --db examples/demo/store.db
uv run python scripts/build_demo.py --out /tmp/again    # rebuild: the same receipt id every time
```

What it contains:

- `store.db`: a claim store with three **invented** pages (`docs.example.com`), four claims and two
  verified relations.
- `receipt.json`: the receipt for the question "What are the API rate limit and the maximum upload
  size?" in `redact_pull` mode.
- `context.txt`: the exact text a model would be shown.

What the context shows: the stale rate-limit sentence (60 per minute) is cut because the changelog
says it replaces that value, and the changelog's sentence (120 per minute) is pulled in. The upload
size (10 MB vs 25 MB) has no evidence of order, so it is marked CONTESTED with both quotes and
nothing is cut.

**This is a fixture, not a measurement.** The claims were written by hand in
`scripts/build_demo.py`, not extracted by a model, so that the demo is deterministic. It shows the
mechanism and that replay works; it says nothing about how well the detector finds real conflicts.
