# results/

Raw outputs of live runs. Nothing here holds a key (keys are scrubbed before saving, and the
guardrails scan this directory). Which file backs which number:

| File | What it is | Backs |
| --- | --- | --- |
| `smoke/` | One-off live calls to SERV and Reppo | `docs/API_NOTES.md` "Observed" |
| `guard-fp/` | Prompt-guard false-positive run on the real corpus | `docs/API_NOTES.md` |
| `extract/*run1*.jsonl` | Raw model output of the full extraction (run 1; `...ABORTED-28-pages` is a stopped first attempt) | 1,011 claims, `docs/API_NOTES.md` |
| `items/dev-v3.jsonl` (+ `.meta.json`, `.raw.jsonl`) | Predictions on the 106 dev items with detector `detect-v2` (the meta records it) | precision 1.000 / recall 0.892 in the README and `docs/LIMITATIONS.md` |
| `items/dev-v2.jsonl` (+ `.meta.json`) | The same with `detect-v1` | the previous figures, precision 0.968 / recall 0.811 |
| `items/dev-full.jsonl` | The same run **before** unfinished items were treated as UNKNOWN. Three items in it have a failed pair. Superseded by `dev-v2.jsonl`; kept as the record of the 0.967 / 0.784 figures that were corrected | the correction note in `docs/LIMITATIONS.md` |
| `items/dev-trial1..4.jsonl` | The first six-item trials while the detector was being fixed (trial 1 and 2 predate the pairing and empty-reply fixes) | nothing; history only |
| `arms/dev-v1.jsonl` (+ `.meta.json`, `.raw.jsonl`) | Every arm's answer on the 106 dev items, k=1 and k=2, one repeat, with model and prompt versions and the raw model replies | the arms table in `docs/LIMITATIONS.md` |
| `arms/dev-v3.jsonl` (+ `.meta.json`, `.raw.jsonl`) | Five repeats per arm, all 106 items, detector `detect-v2` | the current five-repeat bullet in `docs/LIMITATIONS.md` |
| `arms/dev-v2.jsonl` (+ `.meta.json`, `.raw.jsonl`) | Five repeats with `detect-v1`; stopped for low memory at 105 of 106 items | the previous five-repeat bullet |
| `items/test-v1.jsonl` (+ `.meta.json`, `.raw.jsonl`) | **Held-out.** Predictions on the 93 test items with detector `detect-v2`, run after the freeze (2026-11-11T21:12:41Z) | precision 0.857 / recall 0.828 in `docs/LIMITATIONS.md` ("Held-out result") |
| `arms/test-v1.jsonl` (+ `.meta.json`, `.raw.jsonl`) | **Held-out.** Five repeats per arm, all 93 test items. The run was stopped by the system for low memory three times and resumed from the saved file each time (the scorer reports 93 records for 93 items, none unpredicted) | the held-out arms bullets in `docs/LIMITATIONS.md` |
| `arms/test-oracle-v1.jsonl` (+ `.meta.json`, `.raw.jsonl`) | **Held-out.** `baseline`, `pull` and `oracle_pull` (labels instead of detection: an upper bound), 5 repeats, all 93 test items; 125 new model calls, the rest from the cache. Scanned for secret shapes on 2026-11-12 (none; the `.raw.jsonl`, about 2.4 MB, is over the CI scanner's cap) | the oracle bullet in `docs/LIMITATIONS.md` |
| `audit/reppo-conflicts-v2.jsonl` | **Live Reppo re-audit of `answer-v2`, 2026-11-15.** 8 rows: 4 documentation conflicts (3 Reppo, 1 OpenServ), 2 arms. 7 are new evaluations; the `c03-baseline` row is a replay of the 2026-11-12 verdict (same `eval_id`), because its text was byte-identical to v1's and the ledger does not resend. Its `credits` field is copied per row, so the new spend is 3,080, not 3,520. `currant reppo-audit report --results` summarises it | the v2 audit numbers in the README |
| `audit/reppo-conflicts-v1.jsonl`, `audit/reppo-main-v1.jsonl` | **Live Reppo audit, 2026-11-12.** One row per settled verdict (score, route, confidence, rubric, Reppo's reason text), from the submission files in the git-ignored `docs/private/`. The conflict file has 6 rows (3 real Reppo documentation conflicts, 2 arms); the main file has 30 rows for 15 distinct evaluations (both arms gave identical text, so the second row reads the first's verdict, and its `credits` field is counted per row, 440 each). 21 evaluations, 9,240 credits in all. Reppo's reason text is third-party text | the audit bullet in `docs/LIMITATIONS.md` |
| `arms/dev-trial1.jsonl` | A six-item trial before the scorer learned to skip controls with non-numeric answers; history only | nothing |
| `injection/*.json` | Live prompt-injection runs: 14 payloads, guard on and off (typed answers and metadata, no page text). `20261111T114441Z` is the five-repeat baseline; `20261111T164003Z` re-measures with marker words lowered in page text (no real change, so that change was not kept) | `docs/THREAT_MODEL.md` |
| `relate-real.log` | Summary of the first real-corpus relation run (416 pairs) | `docs/LIMITATIONS.md` |
| `relate/*.raw.jsonl` (local only, git-ignored), `items/*.raw.jsonl` | Raw model replies, one line per call (hit, miss or error), from `currant relate` and `currant run-items` after 2026-11-06. **Absent for `dev-v2` and the first relate runs**, which predate the log (their replies are only in the local cache) | the audit trail for later runs |

`receipts/` (git-ignored, so absent from a clone) holds receipts built from real sponsor docs. They
can contain documentation conflicts not yet confirmed; confirmed ones are published in
`docs/drift/`. The shareable, replayable examples are `examples/demo/` and `examples/real/`.

Predictions are scored with `currant score`, which needs `data/evalset.db`. That file is not
committed, so the scores cannot be recomputed from a clone. The commit root over the labels
(`d80501c2…`) and the code fingerprint (`e1b31e9c…`) were published in
https://github.com/Dami904/currant/issues/1 before the freeze; they let anyone check a labels file
and the code against what was published, but only the author has held the labels so far. The
fingerprint changed to `aefbb02f…` on 2026-11-14 because of one comment-only edit to a docstring
(`docs/LIMITATIONS.md` says exactly what).

The arms files (`arms/dev-v1.jsonl.raw.jsonl`, about 1.5 MB; `arms/dev-v2.jsonl` and `arms/dev-v3.jsonl`, about 3 MB each, and their `.raw.jsonl`, about 3.9 MB each) are larger than the guardrail scanner's 1 MB
cap, so CI does not scan them (`arms/test-v1.jsonl` and its `.raw.jsonl`, about 2.6 MB and 3.8 MB, and `items/test-v1.jsonl.raw.jsonl`, about 1.1 MB, are in the same position). They were checked with the guardrails' secret patterns on 2026-11-10, 2026-11-11 and 2026-11-12 (none found), and they
contain model replies only, not prompts or keys.
