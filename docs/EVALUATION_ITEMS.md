# Evaluation items and the split

Source: `src/currant/evalset.py`, stored in its own file (`data/evalset.db`). Decided Nov 6.

## Why items, not pages

Detection is judged on **pairs**: did the detector get this stale-versus-current pair right. A pair
spans two pages, so splitting pages breaks it. The first version split pages by URL hash and put
the stale quickstart on `dev` and the changelog that retired it on `test`:
the evidence needed to judge the pair was on the locked side. Splitting by corpus would have mixed
"does not generalise" with "Reppo's docs are written differently". Splitting items fits the thing
being measured, and lets every page be extracted with no lock.

## The rules

| Rule | How it is enforced |
| --- | --- |
| The unit of splitting is a **cluster**: everything about one underlying fact, or built from one template and source page, shares a split | A database trigger refuses a cluster that straddles |
| Synthetic items go to `dev` (60%) or `test` by a hash of the cluster id | `split_for_cluster`, pinned by a golden test |
| **Real items are never tuned on.** An unseen real item is `heldout`; one we had already studied is `dev` | A `CHECK` constraint: `real` + unseen can only be `heldout`; `real` + seen only `dev` |
| A new item in a cluster that already has a studied item is contaminated, so it becomes `dev` | `add_item` forces it and logs `item_contaminated` |
| A studied item cannot join a cluster that already holds sealed held-out items | `add_item` refuses |
| Each label is salted and hash-committed when the item is created, and never changes | `label_commit`; labels, items and events are append-only (triggers) |
| Dev labels are readable at any time; test and held-out labels raise `EvalLocked` until `freeze()` | `label()`, `labels()` |
| The freeze is permanent and closes the item set | Triggers on `meta`, `items` and `labels` |
| Pipeline code never sees a label | `currant.guardrails` fails CI if `crawl/`, `extract.py`, `store.py`, `store_schema.py`, `serv.py`, `config.py`, `detect.py`, `ground.py`, `receipt.py`, `llmcache.py` or `obs.py` import `currant.evalset`, or if `harness/run_items.py` (which imports the item type) calls a label accessor |

An item stores a **spec** (the pipeline's inputs only, readable any time) and a **label** (the
answer, sealed). Nothing in the spec may reveal the label.

## Commands

- `currant eval-root` prints the commit root and the number of items per split. It never prints a
  label. **Publish the root outside this machine (a commit message, a post) before tuning starts**:
  that is what turns the seal into evidence other people can check.
- `currant eval-freeze --yes` unlocks test and held-out labels for good and closes the item set. It
  is the Gate 2 act (Nov 11) and cannot be undone.

## What exists (2026-11-06)

`currant make-synthetic --run 1 --seed 1 --supersede 99 --clean 100` built **199 synthetic items**
from extraction run 1 (`src/currant/harness/synth.py`), reproducible from the seed:

| Scenario | Items | What is true |
| --- | --- | --- |
| `supersedes_explicit` | 33 | The update says it replaces the previous value. Current value: the new one |
| `supersedes_dated` | 33 | The stale page has a "Last updated" date; the update is a later dated changelog entry. Current value: the new one |
| `contested_implicit` | 33 | The update restates a different number with no date and no replacing wording. Nothing orders them, so the right answer is **CONTESTED** |
| `clean` | 100 | Nothing is stale; the second page is an unrelated real page. Original value stands, nothing is cut |

- **Split:** 106 dev and 93 test items, from 68 source-page clusters (41 dev, 27 test).
- **What the pipeline sees** (`spec`): two neutrally labelled pages and a question. The scenario,
  expected state, values and stale span are only in the sealed label. Cluster ids are hashes, so
  they reveal nothing.
- **Commit root of the synthetic set alone:** `58d84148ef3a568afd4048dbae89a30ac374edf5d10671640744b42d34b3210a`.
- **The frozen set (2026-11-11)** adds 3 real dev items from Reppo's docs (202 items: 109 dev, 93
  test). Its commit root `d80501c25d50…` was posted in issue #1 before the freeze, and all 202
  labels with their salts are in `results/labels/`; `tests/test_published_labels.py` recomputes
  the root. The plan's 40 real items were not reached.

## Limits

See `docs/LIMITATIONS.md`: the seal proves the labels did not change after the root was posted, not
that they are right; the lock guards the API and not the file; and tuning on synthetic items may
not transfer to real docs.
