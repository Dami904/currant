# Timeline

Git history here starts on 2026-11-14, when the work was moved into this repository. The work
itself began on 2026-11-05. Each date below is backed by a committed file whose name or contents
carry the timestamp, so it can be checked without trusting this page.

| Date (UTC) | What happened | Evidence |
|---|---|---|
| 2026-11-05 | First crawl of the SERV and Reppo docs (132 pages). Live probes of SERV and the Reppo API, and a prompt-guard false-positive check. First extraction run (`gpt-6-luna`, `extract-v1`). | `snapshots/2026-11-05/`, `results/smoke/20261105T*`, `results/guard-fp/`, `results/extract/20261105T*` |
| 2026-11-06 | Extraction resumed and completed (1,011 claims). First relation-detection runs. First dev-item runs. | `results/extract/20261106T*`, `results/relate/20261106T*`, `results/items/dev-full.jsonl`, `dev-v2.jsonl` |
| 2026-11-09 | More relation-detection runs. | `results/relate/20261109T*` |
| 2026-11-10 to 11 | Prompt-injection measurements against the live model. | `results/injection/` |
| 2026-11-11 | Second crawl. Proxy smoke tests. Dev run with `detect-v2`. Freeze note posted, then the held-out test split run once. | `snapshots/2026-11-11/`, `results/smoke/20261111T*`, `results/items/dev-v3.jsonl`, `results/items/test-v1.jsonl`, issue #1 |
| 2026-11-12 | Public trial on a second vendor's docs (unnamed until that vendor is told). | `results/external/`, `docs/LIMITATIONS.md` |
| 2026-11-14 | This repository's history begins. | `git log` |
| 2026-11-15 | Third crawl. Crawl-diff supersession and as-of view (one verified change). Exact candidate blocking. A second detector model on dev, which exposed a missing guard (`detect-v3`). A third documentation site crawled and extracted. A receipt from real docs replayed in CI. A receipt check page. | `snapshots/2026-11-15/`, `results/crawldiff/`, `results/scale/pairing.json`, `results/items/dev-v4*.jsonl`, `results/extract/kite-*`, `examples/real/` |

The 202 frozen labels were published on 2026-11-15 (`results/labels/`); their commit root equals the
one posted in issue #1 before the freeze. What is not on this timeline: the Reppo audit runs are
dated inside `results/audit/`, and the labels for the third site have not been written yet.
