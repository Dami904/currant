# Claim store

A single SQLite file (`src/currant/store.py`, schema in `src/currant/store_schema.py`). It holds
what the crawler fetched, the claims extracted from it, and the relations between claims.
Nothing in it talks to a model or the network.

## The rule it exists to enforce

> Nothing is cut, annotated or pulled unless a verbatim quote supporting it was verified by our
> own code against the source text.

The model proposes; the store checks. The check is done by **SQLite triggers**, not only by
Python, so a bug in our code cannot write a claim whose quote is missing from its document or
mark a relation verified without its evidence. `ClaimStore.check_integrity()` re-checks all of it
from the data alone, which catches corruption that bypassed the triggers.

## Tables

| Table | What it holds |
| --- | --- |
| `documents` | Page text, keyed by the SHA-256 of the raw bytes (the crawl manifest's `content_sha256`). Never rewritten. |
| `snapshots`, `snapshot_pages` | Which content each URL had in each crawl. This is the history as-of queries need. Pages carry no dev/test label. |
| `runs` | One row per extraction or relation run: stage, model, prompt version, params, snapshot. Every output points at its run. |
| `claims` | A span `[start_char, end_char)` of a document, its verbatim `quote`, a typed value, and a stance. |
| `relations` | `same`, `supersedes`, `contradicts`, `unrelated` between two claims, with an `ordering_basis` and a status. |
| `relation_evidence` | The quotes that justify a relation, each marked `verified` only if verbatim at its span. |
| `events` | Append-only audit log: ingests, runs, refused claims, decisions. |

## What the database refuses

- A claim whose quote is not exactly the document text at its span; whose document is not in the
  run's snapshot; or whose run is not a running `extract` run.
- A relation that is not created as `proposed`, or whose run is not a running `relate` run.
- Verified evidence whose quote is not verbatim; evidence added to a decided relation.
- A relation marked `verified` without the evidence its kind needs:
  - `supersedes`: verified `older` evidence from the older claim's document, verified `newer`
    evidence from the newer claim's document, and either verified `ordering` evidence or an
    `ordering_basis` of `crawl_diff`;
  - `contradicts`: two distinct verified quotes (so a CONTESTED answer always has both sides);
  - `same` / `unrelated`: at least one verified quote.
- A `supersedes` relation with an `unknown` ordering basis: with no known order the answer is
  CONTESTED, never a guess.
- Any update or delete of documents, snapshots, snapshot pages, claims, evidence or events; any
  change to a decided relation; any delete of a relation or run; any change to the freeze.

Offsets count characters (code points), not bytes. A test puts an emoji before a quote to prove
SQLite and Python agree.

## Ideas taken from Canon, and what was left out

Taken: the stance vocabulary (`current`, `historical`, `proposed`, `rejected`, `uncertain`; only
`current` claims compete to be "the value", so a page saying "previously X, now Y" is neither a
conflict nor cut), a derived per-key state (`CANON` / `CONTESTED` / `UNKNOWN`), an ordering
quality field, and an `asserted_at` date on a claim.

Left out on purpose: evidence as a bare string with no offset (ours is checked against the
document), 56-bit hashed ids (ours are full SHA-256), string-only values (ours add a normalised
`value_key` with number and unit), and Canon's "most documents wins" corroboration tiebreak (it
is a guess; the plan says CONTESTED when the order is unknown).

## Derived state: `key_state`

For one (subject, attribute), using only claims with the `current` stance and only **verified**
`supersedes` relations:

1. No current claim: `UNKNOWN`.
2. One distinct value (compared by `value_key`, so the same value in two documents agrees):
   `CANON`.
3. Several values: values that a verified supersession replaces are retired. If exactly one value
   remains, `CANON` with the others retired. If two or more remain, or the verified orderings form a
   cycle, `CONTESTED`, with the claims on every side.

A proposed or rejected relation never changes the answer.

## No dev/test split here

The store holds the whole corpus and every claim extracted from it; nothing is locked. The dev/test
split belongs to **evaluation items**, in a separate database (`data/evalset.db`, see
`docs/EVALUATION_ITEMS.md`), and pipeline code is barred by a guardrail from importing it. A first
version split pages by URL hash and locked test pages here; it put the two halves of the flagship
SERV pair on opposite sides, so it was replaced (schema v2).

## Not built yet

Typed-value candidate-pair search (candidates are
found by text similarity today) and propagation of staleness through `same` relations (a page
repeating a stale value should itself be flagged). The relation detector (`detect.py`) and
receipts (`receipt.py`) are built.

The real database file is not committed (`data/` is gitignored). It is **not** rebuilt
deterministically from the snapshots: extraction needs a SERV key and the model's output
varies. The committed, reproducible store is `examples/demo/store.db`.
