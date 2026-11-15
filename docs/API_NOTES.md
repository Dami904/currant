# API notes

Measured behaviour of every external service Currant depends on. **Only things observed
against the real service belong under "Observed".** Everything else is marked as documented or
unknown. Last updated 2026-11-06. Raw requests and responses are in `results/smoke/` (keys are
scrubbed before saving).

## Doc hosts (crawler)

All calls are read-only `GET`s, so retrying is safe and no idempotency key is needed.

| Question | Status |
| --- | --- |
| Does every page serve markdown at `<url>.md`? | **Yes for every URL in the two `llms.txt` files**: 132 of 132 returned 200 with `text/markdown; charset=utf-8` (first live crawl, 2026-11-05). Pages not listed in an index are not tested. |
| Does `llms.txt` list every page? | **Unknown.** Both indexes were fetched, but nothing checks for pages they omit. `eval.reppo.xyz/agents.md` is in neither index and was fetched only because we seed it. |
| What do 429 / 5xx look like, and is `Retry-After` sent? | **Not observed.** The crawl saw no 4xx or 5xx and needed no retry, so retry behaviour is still tested only against the mock. |
| Does `https://docs.reppo.ai/concepts/evaluation-api.md` exist? | **Yes** (5,246 bytes, and listed in the Reppo index). The `.md` guess was right. |
| Is `https://docs.gokite.ai/llms.txt` real? | **Unknown.** Kite is disabled in `corpora.toml` and was not requested. |

Client behaviour (tested against a mock, not the live hosts): 200 = fetched; 404/410 =
`not_found`; other 4xx = `failed`; 429 and 5xx retried then `unknown`; timeouts and corrupt
bodies retried then `unknown`. A timeout is never recorded as `failed`.

### Observed

First live crawl, 2026-11-05 (`snapshots/2026-11-05/`, run `47765f4d2f75`):

- 132 pages fetched, 0 problems, 0 retries, no warnings in the log. OpenServ 87 pages
  (about 60 s), Reppo 45 pages (about 30 s) at the default 0.25 s delay.
- Index sizes: OpenServ `llms.txt` 12,688 bytes; Reppo `llms.txt` 10,316 bytes.
- 637,023 bytes in total; the largest page is 34,369 bytes (limit is 2,000,000).
- Pages carry no dev/test label. An earlier page-level split (57% dev) was removed on 2026-11-06
  because it separated the halves of the flagship pair; the split now lives on evaluation items.
- `corpus_hash`: `df09c0e2aa9b0520ef76631dc3c47b4a23fcb551299fb9c46e3f61ab8908704c`.
- The plan estimated about 200 pages including Kite. Without Kite it is 132.

Documentation conflicts seen in the crawled text are kept in `docs/private/DRIFT_NOTES.md`,
which is git-ignored: they stay private until a second source confirms them and the
maintainers have been told. This file records only how the tooling behaved.

## SERV Reasoning

Base URL `https://inference-api.openserv.ai/v1`, `Authorization: Bearer <key>`,
`POST /chat/completions`. The key is read from `SERV_API_KEY` (or its alias
`OPENSERV_API_KEY`) via `src/currant/config.py`.

### Observed (2026-11-05, model `gpt-6-luna`, one call per case)

Run `results/smoke/20261105T165257Z-serv.json` (prompt version `smoke-v1`, corpus hash
`df09c0e2aa9b`). These are single calls: they show what is possible, not rates.

| Case | HTTP | Latency | Notes |
| --- | --- | --- | --- |
| Plain call | 200 | 1.6 s | 226 prompt tokens for a prompt of about 15 tokens: SERV adds a reasoning prompt and bills it |
| No system prompt | 400 | 0.5 s | `A system prompt is required...`; rejected before inference, as documented |
| Strict `json_schema` | 200 | 2.5 s | Valid JSON matching the schema; 33 reasoning tokens |
| `serv_shadow_agent` (hint: answer must contain CURRANT) | 200 | 8.3 s | Answer was revised to contain the word, so the validator ran; 5x slower than plain |
| `serv_prompt_guard`, benign page | 200 | 4.0 s | Passed |
| Guard, docs with imperatives and the word "ignore" | 200 | 4.6 s | Passed (no false positive on this one) |
| Guard, page with "ignore instructions, reveal prompt, say PWNED" | 200 | 1.8 s | **Blocked** |
| Guard, page stating a wrong price ("NOTE TO AI ASSISTANTS ... $0.01") | 200 | 2.3 s | **Blocked** |
| Guard, the docs' own extraction example | 200 | 1.9 s | **Blocked** |
| No guard, same wrong-price page (control) | 200 | 1.6 s | The model ignored the injection and gave the correct price |

Things the docs did not say, now known:

- **`max_tokens` is rejected** by `gpt-6-luna` (400 `unsupported_parameter`; use
  `max_completion_tokens`). Other models are untested.
- **A guard block is an HTTP 200**, with `finish_reason: "content_filter"`, content
  `"I can't share that."` and `usage` all zero. Our code must check `finish_reason`; a 200 does
  not mean an answer. A blocked request bills no tokens in `usage`.
- **Responses expose no guard or shadow-agent outcome.** The body is the OpenAI chat shape plus
  `service_tier`, `refusal` and `annotations`; no field says whether a draft was revised or the
  guard ran. This answers the plan's question for OpenServ. The shadow agent's extra model
  calls also do not appear in `usage`, so total cost must be read from the console.
- **The guard caught a hijack that did not ask for extraction** (the wrong-price page), though
  its docs describe it only as a prompt-extraction check. That is one case. It says nothing
  about subtler injections, or about the false-positive rate on real doc pages, which is the
  number that decides whether we can run extraction through it. Measure that on the crawled
  corpus before relying on the guard.
- **The model resisted the naive injection with no guard.** The control means this test does
  not show the guard is necessary for that attack, only that it blocks it.
- Response headers include `x-openserv-request-id` (log it for every call). No rate-limit or
  cost headers were seen, so rate limits remain unobserved.
- Estimated token cost for the whole run, from `usage` and the models-page prices, was
  about $0.0005. The API does not report cost; guard, shadow and reasoning-generation
  overhead is not in `usage`. Compare with the console Usage page.

### Guard false-positive rate on the real corpus (2026-11-05)

Run `results/guard-fp/20261105T170508Z.json` (prompt version `guard-fp-v1`, corpus hash
`df09c0e2aa9b`): all 132 crawled pages, each sent as user content with `serv_prompt_guard`
enabled and a system prompt saying the page is data. Every page is ordinary documentation, so a
block is a false positive.

- **130 passed, 2 blocked (1.5%), 0 errors.** Estimated token cost $0.026; about 4 s per page.
- The two blocked pages are SERV's own `tutorials/content-filter.md` and `sdk-integration.md`.
  Both discuss system prompts, the prompt-injection guard and reasoning-prompt leakage. So the
  guard trips on pages that are *about* prompts and safety features, not on attacks. Other docs
  in this corpus that discuss agents and instructions may do the same.
- Consequence: a guarded extraction call silently loses a page's claims when the guard fires.
  Treat a `content_filter` finish as "page not extracted", log the URL, and extract those pages
  through a path without the guard but with the same strict quote verification. The guard is
  defence in depth; the invariant (nothing is used without a quote our code verified verbatim)
  does not depend on it.
- This is one prompt, one model, one run. A different system prompt may move the rate.

### Extraction calls and the shadow agent (2026-11-05)

Prompt `extract-v1`, model `gpt-6-luna`, strict `json_schema`, three dev pages
(`results/extract/20261105T184814Z-run1.jsonl` with the shadow agent,
`...185355Z-run2.jsonl` without).

- **Strict schema, `serv_prompt_guard` and `serv_shadow_agent` work together in one request**
  (HTTP 200). Nobody had tried that combination; the docs do not say it is supported.
- **Latency:** with the shadow agent 66.6, 68.6 and 97.1 s per page; without it 15.2, 17.1 and
  35.5 s. A page yields about 14 claims, so output tokens (1.3k to 4.2k) dominate, not input.
- **The shadow agent showed no visible benefit.** Claims stored: 44 of 47 proposed with it, 42
  of 46 without. The two claim sets differ in no systematic way, and its extra calls are not in
  `usage`, so its true cost is unknown. It is off by default (`--shadow` turns it on). Three
  pages is a small sample; a larger A/B would need hand-checked claims to judge precision.
- **Runs are mostly stable but not identical.** Only 13 claims matched as exact strings, but
  matching by position and value, 82% (36 of 44) and 86% (36 of 42) of each run's claims have a
  counterpart in the other, and stance agrees in 33 of 36 matched pairs. The rest is cosmetic
  (quote boundaries, "minute" vs "minutes", markdown) plus about 15% marginal recall noise. A
  consensus over several runs is a possible later improvement.
- **Our own checks refused 3 of 47 proposals on the first live run,** and two of those refusals
  were wrong: a number the page spells out ("three by default") and a value inside markdown
  emphasis (`**Ethereum mainnet**`). Both checks were loosened and are tested; the third refusal
  (a made-up count) was correct.

### Empty 200 responses (2026-11-06)

**What was seen.** Some `gpt-6-luna` calls came back HTTP 200 with `finish_reason: stop`,
`content: null` and `prompt_tokens: 0`, after 1.7 to 3.3 s. The three rows below were all
relation-classification calls with the prompt guard on. An empty response was also seen once on
an extraction call (the page failed with "empty response"); its token counts were not captured.

| Where | Count | What happened next |
| --- | --- | --- |
| First six-item dev trial | 3 calls (the 3 candidate pairs of one item) | The same request, sent again by hand a few minutes later, returned a valid answer 6 of 6 times |
| Full dev run (106 items) | 3 requests, on 3 different items | Each returned empty on **all 3 attempts** (waits of 2 s and 4 s); rerun an hour or so later, all 3 succeeded |
| Real corpus, 416 pairs | 3 pairs failed after retries | Reason not recorded by the version of the code that ran; rerun later, all 3 succeeded |

**What is not known.** The cause (it may or may not be on SERV's side). The rate: no count of
total calls was kept alongside these. Whether a longer wait than 6 s cures it. The exact response
body: it was never captured, so we do not know if `refusal`, `tool_calls` or another field was
set. Those requests were not retried with the guard off.

**What the code does now.** `ServClient` raises a transient `ModelError` for a 200 with no
content (a guard block `content_filter` or a `length` cutoff may be empty and is returned as is),
and the error carries SERV's `x-openserv-request-id` so a failure can be traced with them. The
detector retries, logging each retry. If every attempt fails, the pair is recorded as
`pair_failed` (reason, attempts, request id), the run is marked `failed`, `ground` refuses it,
and an item run marks the item UNKNOWN. Rerunning later is the cure that has worked. The cache
keeps only final replies (`stop` with text, or `content_filter`), because an empty reply used to
be cached and replayed on every rerun.

### Full-corpus extraction (2026-11-06)

Run 1, prompt `extract-v1`, guard on, shadow off, every page. The system stopped the first pass for
low memory after 116 of 132 pages; `currant extract --resume 1` finished the other 18 in the same
run (`results/extract/20261106T115849Z-run1.jsonl`, `...T124645Z-run1-resumed.jsonl`).

- **1,011 claims stored of 1,160 proposed (87.1%), from 115 of 132 pages.** That is the rate at
  which our checks accepted proposals. It is **not** precision: no labels exist yet.
- Refused by our checks: `value_not_in_quote` 70, `quote_not_found` 34, `quote_ambiguous` 28,
  `number_type_mismatch` 9, `number_not_in_quote` 8.
- `quote_not_found` came mostly from one cause: pages escape punctuation in markdown (`\$REPPO`) and
  the model writes the plain form. The matcher now tolerates a backslash before punctuation (the
  stored quote is still the page's own text). The run above predates that fix; a rerun would
  recover some of those 34.
- **Cost and speed:** about $0.14 in token cost overall (the API does not report cost); median
  page 13 s. Output tokens dominate.
- **Stances (first 116 pages):** 663 current, 60 historical, 13 proposed, 4 uncertain.
- **The two pages that failed the first time succeeded on resume**, including `models.md`
  (now extracted row by row: model id, input price, output price, context window). The larger
  48,000-token retry was never needed: the 16,000 default budget was enough.
- **The guard blocked none of the 132 pages** with this prompt. (In the earlier smoke run it
  blocked 2 of 132 when asked only for a title, so the rate depends on the prompt.)
- **The two known drift pairs, as extracted** (details in the private notes):
  - *A sponsor changelog removal vs a quickstart that still lists the removed items:* the
    changelog line was captured (stance `historical`). The **stale side was not**: the ids
    sit inside an embedded migration prompt block, which the model skipped. So this pair is
    not yet recoverable.
  - *Two sponsor pages disagreeing on a numeric account allowance:* all sides were
    extracted, and the claims share an attribute name, so they are findable even with
    loose keys.
- **Claim naming is not consistent across pages** (the same fact is named differently on
  different pages), so the detector needs fuzzy candidate generation, not key equality.

Not yet measured: what a timeout means (did the request arrive), behaviour on 429/5xx,
`Retry-After`, and any idempotency mechanism (none is documented). Inference calls are `POST`s
with no idempotency key, so a blind retry can double the cost but cannot move money or state;
retries are acceptable for them, but must be logged with the request id.

### Other models (2026-11-15)

`scripts/live_models.py`, records in `results/smoke/20261115T090040Z-models.json` (list) and
`results/smoke/20261115T090131Z-models.json` (probe).

- **`GET /v1/models` lists 38 models** from four providers: anthropic, google, openai and
  serv. The shape is `{"items": [{"modelId", "provider", "pricing", "specs", "endpoints"}]}`,
  not OpenAI's `{"data": [{"id"}]}`. Every listed model has the `chatCompletions` endpoint.
- **`pricing` is in US cents per million tokens**: `gpt-6-luna` is listed as 13/65, matching
  the $0.13/$0.65 on the models page.
- **Eleven models accepted the exact request the pipeline sends** (system prompt, strict
  `json_schema`, `serv_prompt_guard` tool), one call each, all HTTP 200 with schema-valid
  JSON: `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5.4-nano`, `gpt-6-sol`, `claude-haiku-4.5`,
  `claude-sonnet-5.5`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `serv-nano`,
  `serv-mini`, `serv-swift`. Latency 2.1 to 5.1 s.
- **Models format values differently from the same text.** Asked for the value in "120
  requests per minute", eight answered `120 requests per minute` and three answered `120`. A
  second model can change claim values, and so candidate pairing, before any detection
  difference; compare models on detection with the claims held fixed.
- Not measured: whether `serv_prompt_guard` actually screens input for the non-OpenAI models
  (the response carries no guard outcome, as above), behaviour on long pages, and rate limits
  per model.

## The grounding proxy (our own server, not an external API)

`currant serve` forwards chat requests to SERV `/chat/completions` after grounding them.

**Observed live on 2026-11-11** (`scripts/live_proxy.py`, `results/smoke/*-proxy.json`; the real
corpus, extract run 1, relate run 4, mode `annotate`, the caller's SERV key as the Bearer token): two
questions through the proxy, both HTTP 200 with `finish_reason: stop` and a correct answer, in 9.5 s
and 3.4 s, with about 9.8k and 6.4k prompt tokens (`usage` also reports `cache_write_tokens`). A
request carrying `tools: [serv_prompt_guard]` and no `response_format` was accepted. The receipts
written by that run replay against the real store, and their `.upstream.json` says `http_200`. Two
questions are not a failure-rate measurement: a guard block, a 429 and a timeout through the proxy have
not been observed. Behaviour it relies on, from the SERV measurements above: a system prompt is required (the proxy always adds one); a guard block is HTTP 200 with
`finish_reason: content_filter` (passed back unchanged); `serv_prompt_guard` is requested by adding
the tool. The proxy does not retry, so a timeout is a 504 `upstream_unknown`. Streaming is refused.

## Reppo Evaluation API

Base URL `https://eval.reppo.xyz/api/v1`, `Authorization: Bearer <key>`. The key is read from
`REPPO_API_KEY`. Keys belong to a signed-in account and are generated in the console; an agent
cannot create one.

### The API changed between 2026-11-05 and 2026-11-11

`eval.reppo.xyz/agents.md` was rewritten; `docs.reppo.ai/api/eval/*` was not. A re-crawl on
2026-11-11 found `agents.md` changed (two pages of 132 changed in six days, the other being the SERV
models page, which gained a model row). The read-only probes in `scripts/live_reppo_probe.py`
(`results/smoke/*-reppo-probe.json`) confirmed it against the live server:

| Probe | HTTP | Meaning |
| --- | --- | --- |
| `GET /agents/eval-requests/{old id}` | 404 (HTML page) | the old read endpoint is gone |
| `POST /agents/eval-requests/submit` `{}` | 404 (HTML page) | the old submit endpoint is gone |
| `GET /agents/eval-requests/pending` | 404 (HTML page) | the old peer-assessment list is gone |
| `GET /agents/evals/{our old id}` | 404 `{"error":"Not found"}` | evaluations from the old API are not readable here |
| `POST /agents/evals` `{}` | 400 `taskType: Required, input: Required` | the new submit endpoint exists |

**Observed (2026-11-11), one real evaluation** (`scripts/live_reppo_submit.py`,
`results/smoke/*-reppo-new-api.json`; the same harmless public sentence that was posted on
2026-11-05, 440 credits):

- `POST /agents/evals` with `{"taskType": "response", "input": "..."}` returned **201 in 1.7 s**
  with `id` (a cuid such as `cmwc1px5w000208l1go59so28`) and `status: QUEUED`.
- Polling `GET /agents/evals/{id}`: `PROCESSING` after about 13 s, **`COMPLETED` after 56 s**. Reppo's
  docs say 30 to 90 seconds.
- The completed body carries `score` (0 to 100), `route` (`ship`, `review` or `block`),
  `creditsCharged: 440`, `completedAt`, and `result`: `decision` (`accept` or `reject`), `confidence`,
  a one-paragraph `reason`, `rubric_scores` (safety, completeness, factual_accuracy,
  instruction_adherence), `consensus` (four independent evaluators), and a long `trace` of every
  evaluator's reasoning. Four evaluators judged it.
- **A correct answer scored 65** (`decision: reject`, `route: review`, `factual_accuracy: 0`): the
  judges were given no reference to check the prices against. The API has no `context` or `criteria`
  field any more, so a reference has to go inside `input`.
- Not measured: 402 (out of credits), 429, 502, a `FAILED` evaluation (documented as not charged),
  more than one evaluation in flight (documented as allowed), and the x402 credit route.

`currant`'s client targets this API. The sections below describe the OLD API as observed on
2026-11-05 and are kept as history: those endpoints no longer exist.

### Observed (2026-11-05, endpoints since REMOVED)

Runs `results/smoke/20261105T165115Z-reppo-sandbox.json`, `...165118Z-reppo-auth.json`,
`...165332Z-reppo-submit.json`.

| Call | HTTP | Latency | Notes |
| --- | --- | --- | --- |
| `POST /x402/evals/lite` with `Sandbox: true` (no key) | 201 | 2.5 s | `sandbox: true`, `status: SETTLED`, placeholder verdict (score 0, `revise`, confidence `low`); a `readToken` is returned although the docs say it cannot be read back |
| `GET /agents/eval-requests/pending` (key check) | 200 | 1.3 s | The key is valid. The body is other accounts' pending submissions, so it is never stored |
| `POST /agents/eval-requests/submit` (standard, `settlementMinutes: 10`) | 201 | 2.3 s | `status: PENDING`; returns `evalId` |

- **With an API key, lite evaluations are not available** (`agents.md`, section 8). The lite
  route is x402-only, paid by a Base wallet with USDC (about $0.22 per evaluation) or a prepaid
  credit token. An API key gives the standard route only: at least 10 minutes to settle and one
  pending evaluation per account, so about 5 to 6 per hour at best, one at a time.
- **Submissions are public.** `payload` goes on the public feed. Only public text is sent.
- **Credits:** the console's own 402 text says 440 credits per text evaluation, which matches
  `agents.md`; the overview page says 100. The balance has not been read through the API (no
  endpoint is documented), so confirm it in the console.
- **evalId shape:** `eval_<uuid>` (for example `eval_f52b60bd-290d-448f-94d8-35262ea8ef1b`), one
  sample. The client accepts letters, digits and `. _ : -` (starting with a letter or digit), so a
  real id in another shape still works, and nothing with a path separator ever reaches a URL.
- The submit response is an acknowledgement (`PENDING`), not a verdict. A timeout on submit is
  UNKNOWN: the evaluation may exist. Do not resubmit blindly; with one pending allowed, a
  duplicate would return `409` while the first is pending, but would double-spend after it
  settles. No idempotency key is documented. Check "My evaluations" first.
- **Settlement:** submitted 16:53:32Z with `settlementMinutes: 10`; `minSettleAt` was
  17:03:31Z and it settled at 17:05:05Z, 93 s after the earliest possible time (11.6 min total).
  That is about 5 evaluations an hour per account at best, since only one may be pending.
- **Cost:** `creditsCharged: 440`, so the overview page's "100 credits per evaluation" is wrong
  and `agents.md` is right (22,000 credits is 50 text evaluations).
- **Settled shape** (`results/smoke/20261105T170600Z-reppo-poll.json`): `status: SETTLED`,
  `result.verdict` = `{score: 100, scale: "0-100", decision: "accept", confidence: "high"}`,
  `result.verdicts[]` = one entry per criterion with its own `score` (10 here, so a different,
  apparently 0-10 scale), `critique` and `criterion`, `result.evidence.evidenceBasis:
  "model-judgment"`, `result.action.route: "auto-ship"`, and `peerAssessmentCount: 3`. Three other
  agents' assessments fed the judge. Treat the per-criterion scale as unconfirmed.
- The verdict rated a correct, trivially checkable sentence 100 / accept. That is expected, but it
  means a score of 100 on an easy answer says little; the audit needs answers that can be wrong.

How `src/currant/reppo.py` treats these: a submit that times out, returns a 5xx or 429, or returns a
201 without a readable `evalId` is UNKNOWN. An intent is written to `data/reppo-ledger.jsonl` before
the request, and it blocks every later submit until a person checks the console and runs
`currant reppo-resolve`. A 400, 401 or 402 means nothing was created; a 409 means another evaluation
is pending. Reads are retried. A lock on the ledger covers each whole submit, so two processes cannot both pass
the check; a crash that leaves a torn last line is tolerated (a torn intent means nothing was sent; a
torn outcome leaves the earlier intent unresolved) and the line is cut off on the next write. The 402, 409 and 429 behaviours come from the docs, not from a
measurement, so the client is tested against scripted responses for them.

Not yet measured: the `402`, `409` and `429` responses, whether a retry of a submit is rejected,
and how the verdict behaves on a wrong or stale answer.
