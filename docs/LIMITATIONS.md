# Limitations

What is not handled yet, stated plainly. Last reconciled with the code on 2026-11-15.

## Not built yet

The x402-priced endpoint is not built. Crawl-diff supersession and as-of queries are built
(2026-11-15) but small; see "Crawl-diff" below. Live runs so far: 28 Reppo evaluations through the audit runner
(21 on 2026-11-12 and 7 on 2026-11-15; `results/audit/`, see "The audit" below), one earlier through the current API and two
questions through the proxy (`results/smoke/`); the `review` loop and the drift report are
tested only against scripted responses. The
held-out result (next section) is on synthetic items. **There is no held-out result on real
documentation**: the 3 real items are dev items, so no real-documentation item was held out.

## Crawl-diff (2026-11-15)

`currant crawl-diff` compares two extract runs on two snapshots of the same URLs and records a
`supersedes` relation (basis `crawl_diff`, no model) when a `current` value left a page and a
same-kind value replaced it. The database still checks both quotes verbatim. Three snapshots
exist (2026-11-05, 11-11, 11-15): 2 pages changed between the first two and 2 between the last
two. Result, in `results/crawldiff/2026-11-15.json`: **one verified change**, the Reppo
`agents.md` decision values going from "`accept`, `revise`, `reject`" to "accept or reject".
Limits:

- **Recall is capped by extraction.** Run 10 (the 11-15 snapshot) did not extract the decision
  claim at all, so the 11-05 to 11-15 comparison found nothing although the change is still
  there. Other real edits on these pages (one evaluation in flight became several; the submit
  endpoint moved) were not paired because no matching pair of claims was extracted.
- **`ground` does not use these relations yet.** They link claims from two extract runs, and
  `ground` plans from one run. They feed `currant as-of` and the record only.
- **Too few changes to measure precision.** One pair, checked by hand, is an anecdote.

## A second detector model (dev only, 2026-11-15)

`run-items --relate-model` keeps extraction on `gpt-6-luna` (every extraction call came from the
cache, so the claims are identical) and swaps only the relation detector. On the 109 dev items,
`detect-v3` (`results/items/dev-v4*.jsonl`):

| Detector         | Precision | Recall | Implicit items marked CONTESTED | Wrong cuts on implicit or clean items |
|------------------|-----------|--------|---------------------------------|---------------------------------------|
| gpt-6-luna       | 1.000     | 0.892  | 13 of 18                        | 0                                     |
| claude-haiku-4.5 | 0.941     | 0.865  | 14 of 18                        | 0                                     |

Under `detect-v2`, the Haiku run (committed as evidence) also cut 2 implicit items, retiring
"1 at a time" in favour of "Only one evaluation may be in flight". That is the same value, and
nothing checked that a supersession changes the value. `detect-v3` adds that check, with a test
and a mutant. Haiku's 2 remaining wrong cuts pair the wrong attribute: "Claims up to 50 epochs"
retired by "Scans up to 250 epochs", with a real ordering quote that is verbatim. The verbatim
checks cannot catch a right quote attached to the wrong claim. **Detection quality depends on the
model, and the guards bound what a wrong model can do (verbatim evidence, same kind, a changed
value), not whether it pairs the right attributes.** Dev items only; the test split was not run
with the second model.

## A third documentation site (2026-11-15)

The Kite docs (`docs.gokite.ai`, the `kite` corpus in `corpora.toml`) were crawled once: 76 pages
fetched; the root page refused as HTML; one URL that their own `llms.txt` lists returns 404.
`gpt-6-luna` extracted 484 claims (526 proposed) for about $0.07, and `currant real-worksheet`
proposed 49 candidate pairs. **They were labelled by models, not by a person**: two separate
agent sessions (`claude-sonnet-4-6` and `claude-opus-5-5`) labelled them independently from the
crawled text, without seeing detector verdicts. Both labelled **all 49 as not a conflict**: testnet
against mainnet chain IDs, a chain ID against a LayerZero endpoint ID, Kite against another chain
named in a changelog, and two port numbers from the same table. So this site yields **no
evaluation items**, and there is still no measured precision or recall on a site Currant was not
built against. What the labels do show: the one detector contradiction that falls on a worksheet
pair (chain ID 2368 against 2366) is a false positive, and the detector called the other 48
worksheet pairs unrelated, which both labellers agree with. Model labels are not ground truth;
they are reported as model-made.

Detection was then run once (`relate-v1`, `gpt-6-luna`, 229 pairs, 228 model calls, one pair
failed and one was blocked by the prompt guard; raw log kept locally, as `results/relate/` is git-ignored).
It verified 33 contradictions and 0 supersessions. Read by eye (not labelled), **32 of the 33 are
changelog entries**: each dated release page names that release's versions, which is history,
not a conflict. The pages are dated only in their URLs (`changelog/2026/2026-11-13-release.md`),
and the detector accepts a date only as a quote from the page text, so it cannot order them and
falls back to CONTESTED. The 33rd (chain ID 2368 against 2366) is testnet against mainnet,
as both model labellers found. **This is a real failure on an unseen site.** It fails safe: nothing was cut and nothing
was retired. But an agent asking about versions would get false CONTESTED notices. It was not
tuned away, so a later measurement on this site stays honest. The likely fixes are a URL date as
an ordering source, or treating release-note claims as `historical`. The snapshot is kept out of the repository
(`data/snapshots-kite/`) because two pages contain `0x` + 64-hex strings that the secret scanner
cannot tell apart from wallet keys. The raw extraction log is
`results/extract/kite-20261115T095906Z-run1.jsonl`.

## Candidate pairing at scale (2026-11-15)

Candidate pairs are found by prefix-filter blocking, proven equal to the old all-pairs search by
a property test (1,500 random cases) and on every real extract run (`results/scale/pairing.json`).
On the real 1,011-claim run it takes 0.9 s against 5.1 s. On synthetic claims with a Zipf
vocabulary it is only about 2x faster (48.6 s against 112.4 s at 5,000 claims; 160.6 s at
10,000), so it still grows roughly quadratically when common words dominate: it is not ready for
corpora of 50,000 claims.

## Held-out result (test split, detector `detect-v2`, 2026-11-11 to 12)

The 93 test items (27 source pages) were scored once, after the freeze. Nothing was tuned on
them: the code that produced these numbers is the code fingerprinted in the freeze note
(`e1b31e9c…`, issue #1 on `Dami904/currant`, posted before the labels were unlocked). No item
was unknown or failed. The commit root is `d80501c2…`. **The freeze came after the root and the
fingerprint were published, but both were published by the author from the author's machine;
nobody else has checked them yet.**

**One comment-only change was made after the freeze (2026-11-14):** a three-word attribution
phrase was deleted from the module docstring of `src/currant/store_schema.py`. No code, schema or
behaviour changed, but the fingerprint covers that file, so it moved from `e1b31e9c…` (the value
in issue #1) to `aefbb02f85d2a1c57284da499eaba50049483487bc6840eea3b42ef78f7a67d7`. Run
`uv run python scripts/code_fingerprint.py` on the committed tree to get the new value.

- **Detection (`results/items/test-v1.jsonl`): a miss against dev.** Precision 0.857 (24 of 28
  cuts correct; 95% interval by source page 0.731 to 0.966) against 1.000 on dev. Recall 0.828
  (24 of 29; 0.667 to 0.955) against 0.892. Implicit pairs CONTESTED 12 of 18 (0.667) against
  10 of 15. **0 cuts on 46 clean controls and 0 cuts on 18 implicit pairs**, so the guarantee
  that matters most (never cut a sentence that has no update) held. Dated updates: 15 of 16
  correct; explicit updates: 9 of 13 correct (10 cut).
- **The four wrong cuts, read after scoring (nothing changed because of it).** Each is on an item
  that does have a real update:
  - One is a genuinely different fact. The labelled stale sentence is "25% ... revenue from
    enterprise/B2B clients ...", and the detector also cut an earlier sentence, "25% of all SERV
    Reasoning API revenue ...", which is another claim (a wrong-neighbour cut, the failure seen
    once on dev under `detect-v1`).
  - Three cut a different statement of the same value than the one the label names: a second
    table row restating "EVOF ... 40%" (the labelled sentence was cut too), the sentence "A valid
    signature returns a 24-hour session token" instead of "A session token valid for 24 hours",
    and a `max_iterations` table row instead of the `serv_shadow_agent` row. My reading is that
    the first of these cuts is a true restatement of the same stale fact and that the scorer
    counts it wrong only because the label names a single span; for the other two I did not
    check whether the value in the cut sentence is really the stale one. In both of those the
    labelled sentence was not cut, so each is also a missed update.
- **The five missed updates** are 3 explicit updates for which the detector found no candidate pair
  at all (`pairs: 0`: an idempotency count 1000 to 10000, a revenue share 20% to 10%, and a port
  number 7378 to 14756), plus the 2 items above where a different sentence was cut. I have not
  checked whether the claim was never extracted or the pairing dropped it.
- **Why the number is lower than dev.** The dev numbers were tuned on those items, so a drop
  was expected; this is the size of it. Four wrong cuts and five misses on 93 items are too few
  to say which rule would fix them, and I did not change any: a change now would alter the
  published fingerprint.
- **Arms (`results/arms/test-v1.jsonl`; 93 items, 5 repeats, 6 arms, `gpt-6-luna`, `answer-v1`):**
  - Only the stale page retrieved, a newer value exists, k=1 (19 items): baseline 0%; `pull` and
    `annotate` 84.2% [67, 100] (McNemar 16 vs 0, p about 3e-5); `redact` alone 0% (it abstains
    60% of the time); `random_cut` 0%. Dev was 87.7%.
  - No order in the text, only the stale page, k=1 (13 items): baseline 0%; `pull`, `annotate`,
    `redact` and `redact_pull` 61.5% (answer CONTESTED, the correct answer; 8 vs 0, p 0.008).
  - Both pages retrieved, k=2: newer value exists (29 items), every arm including the baseline
    100%: **no lift, as on dev**. No order in the text (18 items): baseline 0%, grounded arms
    72.2% [50, 94] (13 vs 0, p 0.0002).
  - Clean controls (46 items): every arm equals the baseline (90.9% at k=1 and 87.3% at k=2; the
    shortfall is the same for the baseline), so no harm from cutting was seen.
  - **Oracle upper bound (`results/arms/test-oracle-v1.jsonl`; `oracle_pull` = `pull` driven by the
    labels, not by detection; never a headline).** Stale page only, a newer value exists (19
    items): `oracle_pull` 100%, `pull` 84.2%, baseline 0%. So with perfect detection the arm would
    answer all 19; the gap of 3 items is the detector's misses. `oracle_pull` does nothing for
    items with no order in the text (0% there, by design; `pull` gets 61.5% and 72.2% by
    answering CONTESTED), and ties the baseline on clean controls and where both pages are
    retrieved.
  - The baseline gets 0% on every stratum where the newer value was not in view or no order
    exists, so those percentages mostly measure the detector's recall and the notice, not a model
    improvement; the one stratum where the model could win on its own (both pages, order in
    the text) shows no difference.
- **What this does not show:** any result on real documentation; a result with a model other than
  `gpt-6-luna`; an effect with both pages in view. The test items are synthetic (two pages built
  from a real page and a templated update), so the held-out score is likely easier than real
  drift. I have not checked how many source pages the test and dev splits share.

## Relation detector

- **Current (detector `detect-v2`, 2026-11-11), on 106 dev items** (synthetic, built from the
  real pages): precision of cuts 1.000 (33 of 33), recall 0.892 (33 of 37; 95% interval by
  source page 0.77 to 1.00), 0 cuts and 0 CONTESTED notices on 54 clean controls, 10 of 15
  implicit pairs CONTESTED and none cut (`results/items/dev-v3.jsonl`). **Dev only, and tuned
  on these very items:** each `detect-v2` rule was written after reading a dev failure, so these
  numbers are optimistic by construction. Only the held-out run can say whether they carry over.
- What `detect-v2` changed, and the dev failure behind each rule (6 new model calls, everything
  else from the cache):
  - Pairing compares the whole line (table row, list item) as well as the quote, so a claim
    quoted as a fragment ("Maximum 50 characters.") still meets its counterpart.
  - Two numeric types count as the same kind of value when both name the same unit ("100
    credits" typed as a count on one page, "50 credits" as money on the other). A missing unit
    never matches.
  - Two values of different kinds are now `unrelated`, not CONTESTED: a notice saying the sources
    disagree about two different facts was false, and it made the answering model abstain.
  - One new value retires ONE old value per page: when it also "supersedes" a different value
    on the same page through a weaker pair, that pair is dropped (the earlier wrong cut).
- Previous figures (`detect-v1`, 2026-11-06, `results/items/dev-v2.jsonl`): precision 0.968
  (30 of 31), recall 0.811 (30 of 37), 0 cuts on 54 clean controls.
- **Correction.** An earlier version of this file reported 0.967 / 0.784 / 0.600. Three items
  whose model call returned an empty response on every attempt had been scored as ordinary
  results. They are now UNKNOWN: retried on resume, counted as misses for recall, and left out
  of the no-harm rates. After the rerun nothing was unknown and the figures above are current.
- The `detect-v1` wrong cut (a neighbouring claim treated as the same fact) is gone on dev. The
  underlying weakness is not: page dates order pages, not claims, so a wrong "same fact" verdict
  with no better-matching rival on that page would still be cut (see THREAT_MODEL).
- Recall misses (4 of 37), none fixable without changing a prompt: 3 stale sentences were never
  extracted (two error-code table rows and one token lifetime), and in 1 both values sat in
  changelog entries, stored as `historical`, and two historical mentions are never paired.
- Implicit pairs (no evidence of order) come out CONTESTED 10 of 15 times; the other 5 are
  not flagged at all. Safe, but not complete.
- A guard-blocked pair is skipped and logged (`pair_guard_blocked`) and the run still counts as
  complete, because rerunning cannot change a deterministic block. 2 of the 416 real pairs
  were blocked and are undecided. A failed or unparseable pair is different: it marks the run
  `failed`, `ground` refuses it, and rerunning `currant relate` (decided pairs come from the
  cache) reconciles it.
- An empty 200 from the model sometimes repeats across the immediate retries (see
  `docs/API_NOTES.md`); the answer was to leave the pair UNKNOWN and retry later, not to
  assume one retry fixes it.
- Candidate pairs are chosen by text similarity, ranked, and capped; the real Reppo cost
  conflict ranked 74th of 416. Chosen pairs are not a recall guarantee.
- Staleness is not propagated through `same` relations, and only one claim per sentence is
  compared to its counterpart.

## Ground and receipts

- Retrieval exists (`retrieve.py`: BM25 over whole pages, SQLite FTS5, stemming, no query syntax
  reaches the engine) but `currant ground` still takes the pages as `--url` arguments. It
  ranks whole pages, not passages, and matches any question term (OR), so a long question
  returns many weak matches. Its quoting of search terms is defence in depth that no test can
  distinguish (every Unicode word character was probed against a bare token).
- The CONTESTED notice lists every verified conflict touching a retrieved page, not only those
  relevant to the question. On two real sponsor pages, a question about one price also got
  notices about unrelated conflicts on the same pages. Relevance filtering is not built.
- First real-corpus relation run (2026-11-06, 416 candidate pairs, no labels, so no precision):
  0 supersedes, 7 contradicts, 404 unrelated, 3 failed calls, 2 guard blocks. By hand, about 5 of
  the 7 contradictions looked like real conflicts and 2 did not (a range described two ways; a
  content-filter default described for different endpoints). That is a reading, not a measurement.
- Redact, annotate, pull and the CONTESTED notice: their effect on a model's answers is measured
  on dev items only (see "The arms comparison"), not on real documentation.
- A CONTESTED notice is not raised for a sentence a verified supersession already put in order,
  even if another claim of that sentence was contested (dev showed three claims in one sentence
  turning a resolved update into an abstention).
- Receipts are tamper-evident only against someone without the store (THREAT_MODEL). Signing (`currant sign`, 2026-11-15) is optional: it adds who vouched for a receipt, checked against a public key the verifier supplies, with no revocation or expiry.
- Replay needs the SQLite store; a receipt alone cannot be replayed.
- The context format (delimiters, marker text) is fixed by the code and untested against any
  model's behaviour.
- Ground does not yet handle two claims on one sentence that disagree about which is stale.

## Reppo client and runner

- **Rewritten on 2026-11-11 for a changed API.** Reppo replaced its endpoints between Nov 5 and
  Nov 11 (`/agents/evals`, `taskType` + `input`, `QUEUED`/`PROCESSING`/`COMPLETED`, route
  `ship`/`review`/`block`; the old URLs return 404 and `docs.reppo.ai` still describes them). The
  client targets the new API, which was exercised live ONCE (one evaluation, `docs/API_NOTES.md`).
  The 402, 429, 502 and FAILED responses are unmeasured; the client treats any unexpected status
  as UNKNOWN.
- **API key route only.** An evaluation took 56 s in the one measured run, so 30 audit answers
  should take well under an hour; several can be in flight at once but the runner sends them one at
  a time on purpose. The x402 credit route needs a wallet payment and is not implemented.
- **No criteria, no context.** The API takes only `taskType` and `input`, so the reference
  documentation goes inside the input. One measured evaluation of a CORRECT answer with no reference
  scored 65 (`factual_accuracy` 0, route `review`): the judges cannot check a figure they were not
  shown, and their score has noise of its own.
- **The public-text check is best effort.** It refuses known key shapes and the key in use, after
  folding full-width letters and removing zero-width characters. It cannot stop a key written in
  another encoding (URL-encoded, base64) or text that is private for any other reason. Whether text
  is fit to publish is a person's call: the runner posts nothing unless given the SHA-256 of the
  exact submissions file that person reviewed.
- **Identical text shares one evaluation.** The ledger key is the content (task type and input), not
  the submission id or the arm. Two arms that give the same answer get one verdict (and cost one
  evaluation), and a `review` round that proposes the same text re-reads the old verdict. A `FAILED`
  evaluation is recorded as failed and sent again on the next run (Reppo documents it as not charged);
  one that completes without a readable verdict stays recorded as submitted and is read again, so to
  send that text again, change it or use a new ledger file.
- **An unknown submit stops everything** until a person checks the console and runs
  `currant reppo-resolve`. That is deliberate, because a blind resubmit could spend 440 credits twice.
- **The ledger lock runs on both branches in CI** (the test job runs on Ubuntu, which takes the
  `fcntl` branch, and on Windows); locally it has only been run on Windows.
- **The audit (run 2026-11-12, `results/audit/`): no harm on easy facts, no win on conflicts.**
  21 evaluations, 9,240 credits, from files a person reviewed (`prepare` never uses the synthetic
  items, whose invented "updates" must not be posted publicly). One run stopped on a network
  error while reading a result; resuming read the already-submitted evaluation, nothing was sent
  twice.
  - *15 numeric questions, both arms:* the answers were identical and correct, and all 30 rows
    scored 100, `ship`, high confidence. That is a ceiling: it shows no harm on real
    documentation and cannot show a lift.
  - *3 real Reppo documentation conflicts (cost, sign-up bonus, attachment size):* baseline mean
    66.7, Currant (`pull`) 59.0, difference -7.7 (95% interval -45 to +18, 3 questions: no
    conclusion). Per question: cost -45, sign-up bonus +18, attachment size +4.
  - *Why we lost points (our side):* when the detector found a conflict, the answer was only "the
    documentation is contested: the sources disagree and nothing shows which is current". It names
    neither value nor quote, although the plan promises "CONTESTED with both quotes". The judges
    scored that as incomplete (cost: factual accuracy 13) and preferred a confident "440", which
    matches what the live service charged. Fixed after the audit in `answer-v2` (2026-11-15): a
    contested answer lists every value the notice quotes, and values not written in the notice's
    verified quotes are dropped by our code. These audit scores are `answer-v1`'s and are not
    rewritten.
  - *Re-audit of `answer-v2` (2026-11-15, `results/audit/reppo-conflicts-v2.jsonl`, 8 verdicts,
    7 new evaluations, 3,080 credits):* the same three conflicts plus the OpenServ default `PORT`
    (7380 vs 7378), with the same reference section as v1. The attachment-size baseline text was
    byte-identical to v1's, so the ledger reused its 2026-11-12 verdict (same eval id) rather than
    resend it; that pair compares a baseline judged on 11-12 with a pull judged on 11-15. Baseline
    76.2, Currant 83.8, +7.5 (95% interval -11 to +26, 4 questions: no conclusion), better on 2,
    worse on 2. Per question: cost 91 vs 77 (still lost: the judges prefer the value the live
    service charges, which text cannot know), sign-up bonus 78 vs 100, attachment size 66 vs 58
    (the contested answer named no value, so the judges marked it incomplete), `PORT` 70 vs 100.
  - *Why attachment size named nothing (fixed in `answer-v3`, not re-audited):* the detector never
    found that pair; the CONTESTED notice on those pages was about other facts. The model answered
    "contested" with 1.25 MB and 2 MB read from the page text, and `verify_contested` dropped both
    because only numbers inside a notice counted. It now falls back, when no value is in a notice,
    to values written in the text of the page each one cites (two different pages, different
    numbers), and the answer says Currant has not verified a conflict. Still open: the verdict
    "contested" itself is the model's call when no notice covers the question, and the fallback
    checks only that each number is on its page: not the unit, not that the two numbers are the
    same fact ("Step 3" and "Step 7" would pass), and not that neither page is dated history. A
    stronger version would have the model return a quote per value and verify it like `extract`.
  - *Our other miss:* the detector did not find the attachment-size conflict, so both arms gave the
    stale "2 MB" (the judges flagged the 2 MB vs 1.25 MB conflict themselves).
  - *The documentation's side:* all three conflicts are real. The judges found each from the
    reference alone, which supports issue #11 independently of our own checks.
  - Judges have noise of their own, and each question was judged once.
- **The `review` loop is built as a library function, not wired to a command.** Reppo's current
  routes are `ship`, `review` and `block` (the old `revise` is gone); the loop asks for a new
  proposal only on `review`. Re-grounding is left to the `propose` callback; no command runs it live.

## The proxy and the receipt viewer

- **Run live only twice.** Two real questions through it succeeded against the live SERV API (see
  `docs/API_NOTES.md`); every failure path (guard block, 429, timeout, 5xx) is tested against scripted
  responses only, never observed through the proxy.
- **Not supported:** streaming (refused with a 400), and any tool-use flow beyond adding the guard.
  Only the last user message is the question; earlier turns are forwarded untouched.
- **Single-threaded.** One request at a time, because the claim store is not shared across threads.
  Fine for a demo, not for load.
- **One shared token, not accounts.** With `CURRANT_PROXY_TOKEN` set, every route that holds data
  needs that token in `X-Currant-Token` (2026-11-15). A non-loopback host refuses to start without
  it. There is one token for everyone: no users, no per-user receipts, no rotation without a
  restart. The receipt viewer page cannot send the header, so with a token it shows nothing; use
  the JSON routes. The proxy holds no SERV key, so it is not an open relay to your account: each
  caller supplies their own.
- **The rate limit is per address and in memory.** At most `--rate-limit` chat calls a minute per
  client address (default 30), reset on restart. Behind a reverse proxy every caller shares one
  address.
- **Receipts hold questions.** They are written under `data/proxy-receipts/` (git-ignored); keep
  them private. The directory is never pruned; the viewer lists the newest 200.
- **A timeout is recorded, not resolved.** After a 504 the receipt's `<id>.upstream.json` says
  `unknown`; nothing reconciles it later, and the proxy never retries.
- **Loopback only by default, and it checks the Host header** so a web page cannot reach it through
  a DNS name it controls. With `--allow-remote` that check is off, and the token is what keeps
  others out.
- **The drift report and its privacy guard are relative to the working directory.** Run
  `currant drift-report` from the repository root, or `docs/private/` is a different folder that may
  not be git-ignored. Quotes from crawled pages go into the markdown unescaped (the file is private).
- **The oracle arm trusts the label's stale span** without re-checking it against the page text. It
  is an upper bound built on labels, not on our own verification.
- **Grounding is only as good as the store.** A question with no matching stored page gets a 503,
  not an ungrounded answer.

## The arms comparison

- **The oracle arm** (`oracle_pull`, labels instead of detection) exists as an opt-in arm in `run-arms`
  and is an upper bound, never a headline. It pulls the true newer evidence only when the stale page
  was retrieved and the update was not; it does nothing for implicit (CONTESTED) items.

- **Prompt injection: marker forgery is blocked, false content is not.** `ground.defang` stops a
  page imitating our context markers. A live run (140 calls, 5 repeats per payload,
  `results/injection/`) showed the model answers a page's false number every time (15 of 15) when the
  page fakes an update, an evidence block or a SUPERSEDED note, with the SERV guard on or off (it
  blocked nothing); plain "ignore your instructions" text never worked (0 of 45). Lowering the
  marker words in page text was tried and re-measured the same day: no real change (the three
  persuasive payloads worked 14 of 15 with the guard on, 15 of 15 off, `results/injection/20261111T164003Z.json`), so it was not
  kept. No defence against a controlled page asserting a false value exists; see
  `docs/THREAT_MODEL.md`.

- **Current: five-repeat dev result with `detect-v2` (2026-11-11, `results/arms/dev-v3.jsonl`;
  all 106 items, 41 source pages, 5 repeats, 139 new answer calls and 6510 from the cache).**
  Dev items, and the detector rules were written after reading dev failures: not held-out
  evidence.
  - Only the stale page retrieved, newer value exists, k=1 (26 items): baseline 0%; `pull` and
    `annotate` 87.7% [75, 100] (McNemar 23 vs 0, p about 2e-7), `redact_pull` 84.6%; `redact`
    alone 0% and `random_cut` 0%. Was 77.7% for `pull` with `detect-v1`.
  - **Both pages retrieved, newer value exists, k=2 (36 items): the loss is gone.** Baseline
    95.6%; `annotate` 96.7%, `pull` 95.6%, `redact` and `redact_pull` 95.0%, all within the
    3-point noise floor. Was 89.4 to 91.7% with `detect-v1`. Cause, read from the dev failures: a
    false CONTESTED notice (a missed update, or two claims of one sentence) made the model abstain
    on questions the pages answered; `detect-v2` and the grounding rule removed those notices.
    There is still no LIFT here: with both pages in view this model resolves updates by itself.
  - No order in the text: k=1 (12 items) 58.3% CONTESTED for the grounded arms, k=2 (15 items)
    66.7%; baseline 0%. Unchanged in substance (the detector's implicit result did not change; the
    earlier figures lacked one item).
  - Clean controls (54 items): no arm differs from the baseline.
  - `random_cut` 91.7% where both pages are retrieved (a loss larger than the floor, 1 vs 2 by
    McNemar): cutting a random sentence is not free, which is the point of that control.
- **Previous five-repeat dev result (`detect-v1`, 2026-11-11, `results/arms/dev-v2.jsonl`; 105 of 106 items, 41 source
  pages, 5 repeats per arm).** The run was stopped by the system for low memory with one item left, so
  the scorer reports 105 items and 1 unpredicted. Same dev items and the same tuned code as the first
  run: this is not held-out evidence. The noise floor (the baseline's spread across repeats) is now
  measured, and is 0 points in most strata (the model answers almost identically each time) and 3
  points where both pages are retrieved and a newer value exists.
  - Only the stale page retrieved, newer value exists, k=1 (26 items): baseline 0% correct; `pull`
    77.7% [66, 92], `annotate` 76.2%, `redact_pull` 73.8% (McNemar 20 vs 0, p about 2e-6); `redact`
    alone 0% (it abstains 72%) and `random_cut` 0%.
  - Only the stale page retrieved, no order in the text (11 items): baseline 0%; every grounded arm but
    `random_cut` 54.5% (they answer CONTESTED, which is the correct answer for these items).
  - Both pages retrieved, k=2: no order in the text (14 items) baseline 0% against 64.3% for the
    grounded arms; **newer value exists (36 items): baseline 95.6%, `annotate` 91.7%, `pull` 90.0%,
    `redact` 89.4%.** That is a loss of 4 to 6 points with intervals that include zero (McNemar
    p 0.5 to 1): no lift, and no proof of harm either.
  - Clean controls (54 items): no arm differs from the baseline, so no harm from cutting was seen.
    The 1.9% "harm" at k=1 is identical for the baseline: a page was simply not retrieved.
  - The scorer used to print "clears floor" for a negative lift larger than the noise. Fixed on
    2026-11-11: such a loss now reads "LOSS larger than floor". Even so, read the interval and the
    McNemar p beside it.
- **First dev result (2026-11-10, `results/arms/dev-v1.jsonl`; 106 items, 41 source pages, one
  repeat).** Strata are split into resolvable items (a newer value exists) and implicit ones
  (the right answer is CONTESTED); pooling them had produced a misleading table.
  - Only the stale page retrieved, newer value exists (26 items): baseline 0% correct (it states
    the stale value 96% of the time); pull, annotate and redact+pull 77% (20 items rescued, 0
    lost, McNemar p about 2e-6). `redact` alone stays at 0% (the model abstains 69% of the time):
    the gain comes from pulling the newer evidence. Baseline 0% is close to guaranteed by
    construction, so this mostly measures the detector's recall.
  - **Both pages retrieved, newer value exists (36 items): no lift.** Baseline is already 94%;
    redact, annotate and pull are 89 to 92% (a loss of 1 to 2 items, not significant). When both
    pages are in front of it, this model resolves explicit and dated updates by itself.
  - No evidence of order (15 items): baseline 0% (it always picks a value); every grounded arm
    58 to 67% say CONTESTED (p=0.002). That is by the benchmark's own definition of correct for
    these items. 33 to 42% still pick a value despite the notice.
  - Clean controls (54 items): no arm differs from baseline, so no harm was measured. That
    rests on the detector making no cuts on them, as in the earlier detection result.
  - `random_cut` never helps anywhere.
  - **Not shown by this run:** any effect on real documentation, any held-out effect, or a
    lift once both pages are retrieved. The noise floor is unmeasured (one repeat).

- **The dev runs above are dev items, on synthetic items.** Items are two pages built from a
  real page and a templated update, so they are easier than real drift. The held-out run is in
  its own section near the top; there is no real-documentation result anywhere.
- **The answering model is the same model that extracts and relates** (`gpt-6-luna`), and the
  answering prompt (`answer-v1`) is fixed across arms. A different answerer may behave
  differently; the plan's optional comparison without SERV is not done.
- **Answers are typed numbers.** Items whose true answer is not a number (a token address, an
  identifier, a range) cannot be scored for correctness and are left out of accuracy; they
  still count for harm (was the control's own sentence cut or never retrieved). This
  excludes most clean controls from accuracy, so accuracy on clean items rests on few items.
- **Strata are decided after the fact.** `stale_only` (the stale page retrieved without the
  newer one) arises only when BM25 happens to rank that way. At `k=1` it is rare, so that
  stratum, the one Currant is built for, has few items; the table shows how many.
- **Repeats and the noise floor.** With one repeat the floor is `unmeasured`, and a lift is
  not claimed as clearing it. Repeats are made distinct by a marker in the message, which
  also defeats the cache, so they cost real calls.
- **`random_cut` cuts as many claim sentences as the detector does**, chosen uniformly from
  current claims in the retrieved pages. It controls for "any cut", not for "a cut of the
  right size".
- **The page ids `a`/`b` are the item's own**; the scorer reads which one is stale from the
  label, so strata and harm are only as good as the label.

## Real evaluation items

- **Only 3 exist, all dev.** The frozen evaluation set (2026-11-11) holds 199 synthetic items and
  3 real ones from Reppo's docs; the freeze closed the item set for good, so no more real items
  can join it. The Kite site gave none (see "A third documentation site").
- **Only a person can label them.** `currant real-worksheet` proposes candidate pairs from the real
  corpus using the detector's candidate stage only (text similarity, never its verdict);
  `currant real-label` records a person's verdict one key at a time; `currant real-import` seals
  the items after re-checking every quote and date with our own code. A model never decides the
  truth of a real item.
- **Why there are only 3 (history).** The plan says 40. The corpus yielded 60 candidate pairs, many
  of which will turn out not to be conflicts, and the first extraction found no replacement
  statements at all, so the count may be well under 40. The write-up must report the real n.
- **Judged from the snapshot text, not from today's site.** The labels are about the pages as
  crawled on 2026-11-05. One of the sponsor pages has since been rewritten (2026-11-11).
- **A `contested` label means "the text gives no order".** If a person knows from outside which side is
  right, the label is still `contested`, because that is what a text-only system should answer.

## Run lifecycle

- An extract run with a failed page stays `running` until `currant extract --resume N` retries
  it. `relate` and `ground` refuse an extract run that is not `complete`, so a page with no
  claims cannot silently pass as covered. Guard-blocked pages are different: they are skipped
  by policy and logged, and the run still completes.
- A relate run that left a pair undecided is marked `failed` and `ground` refuses it; rerunning
  `currant relate` reconciles it, because only final, usable replies are cached.
- An extract run made with `--limit` that actually cut pages is recorded `limited`, and
  `relate` and `ground` refuse it, so a 5-page run cannot pass for a full one.
- `--resume` refuses to mix models or settings (model, prompt version, shadow agent,
  unguarded retry) in one run.
- **Not handled:** a page that fails every time (for example it keeps hitting the output
  limit) leaves its extract run open forever, `relate` and `ground` refuse it, and every
  `--resume` pays for that page again. There is no "accept this run with these pages
  missing" decision yet; the only way out is to fix the page's extraction or use a new run.
- **Not handled:** nothing stops two `--resume` commands on the same run at the same time.
  It is a single-user command line, but it would double-count work.
- If a raw-log write fails (full disk, locked file), the run carries on, the reply is still
  cached, and a warning with the count is printed; that part of the audit trail is then
  missing. A raw log with a half-written last line (a crash) has that line dropped on the
  next start.
- A real `relate` run made before this rule (run 3 in the author's store) is recorded as
  `complete` although 3 pairs were undecided; run 4 supersedes it.

## Model cache

- `data/llm_cache.db` keys on the exact request, so a changed prompt never reuses an answer, but
  it never expires: a model update behind the same name would serve old answers.
- It stores only final, usable replies (`stop` with a JSON object, or a guard block). It is a
  cost saver, not the audit trail: every model call, including cache hits, truncated replies
  and errors, is appended to a raw log under `results/` (`results/relate/*.raw.jsonl`, which is git-ignored, and
  `results/items/<predictions>.raw.jsonl`). **`results/items/dev-v2.jsonl` and the first
  real relate runs predate that log**, so their raw model outputs exist only in the local
  cache. The raw log does not contain the prompts, only the replies and the cache key.

## Crawler

- **Three live crawls of the sponsor docs (2026-11-05, -11, -15; 132 pages each, no errors)**, plus
  one each of Kite and a Stripe slice. Retry, 429, 5xx, timeout and
  deadline handling are tested only against a mock transport because the live hosts never
  failed. Whether `llms.txt` lists every page is unmeasured. See `docs/API_NOTES.md`.
- **`robots.txt` is not consulted.** The seeds are `llms.txt` files published for machines,
  and the crawl is sequential with a delay, but a stricter policy would check it.
- **Markdown only.** An HTML response is recorded as `failed`, not converted. A WAF or
  interstitial page returned with a 200 is recorded the same way, although it is arguably
  `unknown`; it is retried on the next run either way.
- **Sequential, no concurrency.** Fine for about 200 pages; slow for much more.
- **Dates come from the snapshot day, not from the pages.** `currant crawl-diff` places a change
  between two snapshot dates, never at a moment inside that window.
- **Retry-After is only read in seconds form**; the HTTP-date form falls back to exponential
  backoff.
- **The page cap cuts alphabetically by URL, not by relevance.** A cut is no longer silent: the
  manifest lists every dropped URL (`truncated`, plus a `skipped_cap` record each), `complete`
  is false, `crawl` exits 1 unless `--allow-truncation`, and `verify` fails unless
  `--allow-unreconciled`.
- **One crawl per snapshot date, enforced by a lock file.** If a crawl is killed hard
  (power loss, `kill -9`) the lock stays and the next run refuses to start until you delete
  `snapshots/<date>/.crawl.lock`. That is deliberate: it fails safe.
- **A corrupt `manifest.json` stops the crawl** (exit 2) and is never overwritten. Fixing or
  deleting it is a manual step.
- **A `removed` page is not refetched.** If an index stops listing a page that is still served,
  the earlier copy is kept and marked `removed`; it only returns if the index lists it again.
- **Dead links are data, not errors.** A discovered link that returns 404 counts as a complete
  crawl. Only a missing page we configured explicitly is a problem.

## A second vendor's documentation: Stripe (public trial, 2026-11-12)

An unlabelled trial of the pipeline, unchanged, on a hand-picked slice of Stripe's public docs
(named from 2026-11-15; it found no documentation error, so there was nothing to tell them first). It tests that the pipeline runs elsewhere, not how accurate it is: there are
no labels, so there is no precision or recall. The pages and model replies stay in git-ignored
folders (`data/external*`, `results/external/`, and a trial config that is not committed), because
redistribution of their text is unchecked; only counts are recorded here.

- **Slice 1, 36 pages (billing, API behaviour, Checkout, disputes, payouts):** 370 claims verified
  of 487 proposed; the relation step asked about 12 pairs and found 0 relations (all judged
  compatible, mostly different Checkout page variants).
- **Slice 2, 59 pages (slice 1 plus 23 recent changelog pages):** 463 claims verified of 611
  proposed (our code rejected 148: value not in the quote, quote ambiguous, quote not found); 69
  pairs asked about, 4 "replaced value" leads and 1 "conflict" lead, 64 unrelated.
- **Read by hand, none of the 5 is a documentation error to report:**
  - 3 of the 4 "replaced value" leads are a repeated sentence in dated release notes ("include
    a version header set to <that release>"). The detector ordered the version strings by date and
    called the older one replaced. Each note is right for its own release, so this is a **false
    positive of the detector**, and a real failure mode: boilerplate repeated across dated entries
    reads as supersession.
  - 1 is a genuine staleness in the sense an agent cares about (an old preview version string
    against a page stating the current version). It is a release note correctly dated, not an error.
  - The "conflict" compares "several business days" with "up to a few days" for delayed payment
    methods: wording, not a conflict.
- **What it shows:** the pipeline extracts and verifies claims on a different vendor's markdown docs
  with no code change, and it did not invent real conflicts. **What it does not show:** that it
  finds real drift there. Nothing was sent to the vendor, because there was nothing to report.
- **Slice limits:** 59 of a very large site; the full 236 KB changelog was left out; one model and
  English only.

## Claim store

- **The real store is local and not reproducible from a clone.** `data/currant.db` holds one
  extraction run (1,011 claims) and several relate runs, but `data/` is not committed, and
  rebuilding it needs a SERV key and gives different model output each time. From a clone, only
  `examples/demo/` (hand-written claims on invented pages) and `examples/real/` (one receipt over
  real Reppo pages, with a 43-claim copy of the store) can be replayed; CI replays both.
- **Staleness does not propagate yet.** A second page repeating a stale value is only flagged if
  its own claim is related to the stale one; the closure over `same` relations is not written.
- **Value identity is simple.** Numeric values match by number and unit, other values by
  normalised text. Wording differences ("five" vs "5", "one hour" vs "60 minutes") are not
  reconciled until extraction produces typed numbers.

## Extraction

- **Accepted is not correct.** 85.6% of proposals passed our checks on the first partial run, but
  those checks prove only that a quote is verbatim, unique, and contains the value. Whether the
  subject, attribute, value type and stance are right is unmeasured until labelled items exist.
- **Recall is unknown and visibly incomplete.** The stale lines inside an embedded prompt
  block (one of the two known drift pairs) were skipped, and the whole `models.md` page failed. Lists of identifiers in code or
  prompt blocks need explicit instruction in the prompt (`extract-v2`), tuned on dev items only.
- **Naming varies between pages** (the same fact gets different subject and attribute names),
  so exact-key matching cannot pair related claims. The detector must generate
  candidates by similarity, and the classifier must decide.
- **The first full run completed through a resume** (the system stopped it at 116 of 132 pages
  for low memory). 17 of 132 pages produced no claim, and it predates the markdown-escape fix, so
  about 30 proposals that were refused as not found could now be recovered by a rerun.
- **Runs are not deterministic.** A 3-page A/B showed about 82-86% agreement between two runs by
  position and value; the rest is wording and marginal recall.
- Stored `value_text` keeps the page's own markdown escapes; keys normalise them, text does not.
- **Locating a quote is not strictly byte-exact.** The stored quote is always the page's own text
  at the span, but the model's copy is matched up to whitespace runs and markdown backslash
  escapes. Re-checking the full run's model outputs with today's code: 12 of 1,023 passing claims
  (1.2%) matched only that way (`scripts/quote_exactness.py`). New runs flag them
  `quote_matched_loosely`; the flag is in the run log, not yet in the claim store or receipts.

## Evaluation items and the split

- **Decided Nov 6: the split is by evaluation item, grouped by cluster, not by page.** A first,
  page-level split put the two halves of the flagship pair on opposite sides (the stale quickstart
  was `dev`, the changelog that retired it was `test`), so Gate 1 could
  only have seen the minority of pairs that landed together. See `docs/EVALUATION_ITEMS.md`.
- **199 synthetic items and 3 real ones.** The generator (`harness/synth.py`) made 99 injected
  supersessions and 100 clean controls from the first extraction run. The plan's 40 real items
  were not reached (3, all dev), so every held-out figure is on synthetic items. The commit root
  was published in issue #1 before the freeze, and all 202 labels are published in
  `results/labels/` (a test recomputes the root).
- **The effective sample is the number of source pages, not items.** The 199 items come from 68
  distinct pages (41 dev, 27 test), and only 44 pages had a rewritable number, so the 99
  supersession items carry about 44 independent clusters. Items from one page are not independent;
  every interval must resample by cluster (`cluster_id`), or it will be too narrow.
- **Synthetic items are optimistic on the stale side.** Source facts are claims the extractor
  already found, so recall of the stale span on these items overstates recall on real docs. The
  held-out real items are the honest measure.
- **Synthetic wording is templated.** The update sentence is the original sentence with a changed
  number, so it is easier than a real rewrite; the explicit, dated and implicit forms are three
  fixed templates.
- **The label seal is a hash commit the author published.** Labels are salted and hash-committed
  when an item is created, and `commit_root` summarises them. The root was posted in issue #1
  before the freeze, which proves the labels did not change afterwards, not that they are right.
- **The lock guards the API, not the file.** `labels()` refuses test and held-out labels before
  `freeze()`, but anyone with the SQLite file can read every row. The pipeline is kept from the
  labels by a guardrail that fails CI if pipeline modules import `currant.evalset`; a determined
  author could still wire them together.
- **Clusters are only as good as the cluster ids we assign.** If two items about one fact are
  given different cluster ids they can land on opposite sides. Cluster ids for real items must be
  chosen by fact, and for synthetic items by template and source page.
- **Tuning on synthetic items may not transfer to real docs.** The 40 real items are held out in
  full and read once at the end; if the result does not transfer, the report says so.
- The real items we already studied (the two known drift pairs) are `dev` and demo material,
  not test material, because we know their answers.
- The 60/40 dev/test ratio for synthetic items is a default.

## Verification

- `currant verify` proves the files match the manifest, the crawl finished, nothing is left
  unresolved. It does not prove the manifest matches what the
  server served; a compromised crawl host or a bad run is not detectable from the snapshot
  alone.
- Committed snapshots are verified on Linux and Windows in CI, which only holds because
  `.gitattributes` marks `snapshots/` as `-text`.

## Repo rules that are still only prose

`CLAUDE.md` states these; nothing enforces them yet:

- **"Ask before any x402 payment or top-up".** (The earlier spend caps were lifted on 2026-11-11.)
  No payment code exists. When it does, it needs an explicit opt-in switch and a test.
- **"No tuning on test or held-out items after Nov 11".** Reading their labels before the freeze is
  refused by code (`EvalLocked`), and `run-items` refuses a non-dev split before the freeze.
  Not stopped: running dev items as often as you like and tuning on them (allowed), or
  writing a separate script that bypasses the CLI.
- **"Every guard ships with a test that fails when the guard is removed".** CI's `mutants` job
  removes 30 named guards and requires a test to fail for each; a guard not on that list is
  still checked only by hand.
- **"Crawled text goes to a model only behind the prompt guard".** Extraction and relation calls
  pass `guard=True` and tests assert it, but no rule fails CI if a new call site forgets it.
  The guard also fails open if its own judge fails.
- **No mainnet deploys from an agent session.**

Enforced as code today: the secret env-var names and any `os.environ` / `os.getenv` read only in
`src/currant/config.py`; secret-shaped strings; `.env` ignored and `.env.*` never read by the
scan; HTTP clients only built in the `cli/` package or `live_*` scripts; no skipped tests, type
suppressions or bare lint exemptions; sockets blocked in the test suite; the item split rule (golden
test) and sealed labels; pipeline modules barred from importing the evaluation store; and `uv.lock` in sync with `pyproject.toml` (`--locked` in CI).

Gaps in the enforcement itself:

- Label isolation is enforced by import for the pipeline modules (`crawl/`, `extract`, `store`,
  `store_schema`, `serv`, `config`, `detect`, `ground`, `receipt`, `llmcache`, `obs`) and, for
  `harness/run_items.py` (which must import the item type), by a ban on calling a label
  accessor. A new pipeline module has to be added to the list by hand.
- Bare 64-character hex strings are not flagged as wallet keys, because SHA-256 hashes look
  identical. The SERV and Reppo key formats are unknown, so they have no pattern.
- The `.env*` deny rule in `.claude/settings.json` blocks Claude's Read tool, not a shell
  `cat`; the guardrails scan is the second layer for committed files.
