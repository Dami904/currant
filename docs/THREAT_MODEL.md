# Threat model

Scope: what exists today: the crawler, the claim store, extraction and relation detection
through SERV, Ground and receipts, retrieval, the model cache, the evaluation harness, the Reppo
client and audit runner (`reppo.py`, `reppo_run.py`, `reppo_audit.py`), the grounding proxy and
receipt viewer (`proxy.py`, `proxy_http.py`, `web/`), and the drift report (`drift.py`). The Reppo
commands have only been run against scripted responses, never live; the proxy has run against the
live SERV API twice.
Last reconciled with the code on 2026-11-11.

## Trust

| Party | Trust |
| --- | --- |
| Our code and the operator's machine | Trusted |
| Crawled pages and `llms.txt` indexes | **Untrusted data.** Never instructions, never executed, never sent to a model except behind `serv_prompt_guard`, which fails open, so enforcement stays in our code (a model can only cause a cut through quotes we verify). |
| Model output (SERV) | **Untrusted proposals.** Every quote is re-checked verbatim, direction comes from our code, and the database refuses relations without verified evidence. |
| `data/llm_cache.db` | Trusted as much as the local disk: it is an unencrypted, non-expiring store of raw model answers with no integrity protection. Anyone who can edit it can feed the detector any answer. |
| Sponsor doc hosts (`docs.openserv.ai`, `docs.reppo.ai`, `eval.reppo.xyz`) | Trusted only to the extent the allow-list names them. A page they serve can still be wrong or hostile text. |
| SERV Reasoning, Reppo | Not called yet. When they are, their outputs are proposals; our code verifies quotes. |
| `manifest.json` and everything in it | Untrusted on read: a path from a manifest is resolved inside the snapshot directory before it is opened, hashed or deleted. |

## Credentials

The crawler uses no credentials. `SERV_API_KEY` is in use (extraction, relation detection,
item runs); `REPPO_API_KEY` is smoke-tested only; `WALLET_PRIVATE_KEY` is unused. Keys are
read only in `src/currant/config.py`; `currant.guardrails` fails CI
if another file under `src/` references them or reads the environment, or if a secret-shaped
string is committed. `.claude/settings.json` denies Claude's Read tool on `.env` files.

| If this leaks | Consequence |
| --- | --- |
| `SERV_API_KEY` | Attacker spends SERV credits (capped by the $5 to $15 balance). |
| `REPPO_API_KEY` | Attacker submits public evaluations on our account and burns free credits. |
| `WALLET_PRIVATE_KEY` | Attacker drains the Base wallet. Keep it to the ~$30 budget; use no other funds. |
| `CURRANT_PROXY_TOKEN` (optional) | Attacker can read every proxy receipt (which holds questions and page text) and send chat calls through the proxy, but only with a SERV key of their own: the proxy holds none. The token cannot change the store, the runs or the rate limit. |

## Defended (and tested)

- **Redirect to an off-list host or a non-http target:** every redirect hop is checked against
  the allow-list and never requested if it fails.
- **Allow-list confusion:** a directory entry matches by prefix, a file entry matches exactly
  (`agents.md` does not allow `agents.md.evil`); look-alike hosts, userinfo tricks and scheme
  downgrades are rejected.
- **Index lists off-list URLs, `mailto:`, `javascript:`, or `#anchors`:** filtered before any
  request.
- **Path traversal via corpus name, snapshot date, or manifest path:** names and dates are
  validated (`[0-9]` digits only, a real calendar date, extended format only); manifest paths
  are contained to the snapshot directory for verifying, caching and pruning.
- **Oversized responses:** capped at 2 MB by declared length and while streaming.
- **A slow-drip server:** the per-read timeout does not bound total time, so each URL also has
  a 120 s total budget across attempts, redirects and backoff.
- **Corrupt or truncated bodies (bad gzip):** treated as transient (`unknown`), not a crash.
- **HTML instead of markdown:** rejected, not stored.
- **Silent snapshot edits or partial runs:** `currant verify` re-hashes every file, checks for
  unlisted files, recomputes `corpus_hash`, and fails an
  unfinished crawl or unresolved records.
- **Losing evidence on a rerun:** reruns start from the previous manifest; a failed fetch or
  refresh never replaces a good intact copy; writes are fsynced then atomically renamed.
- **Two crawls racing on one snapshot:** a lock file refuses the second.
- **Secrets in the repo:** guardrails scan for key shapes and require `.env` in `.gitignore`.
- **A model inventing ordering evidence:** a supersession needs a quote our code finds verbatim
  in exactly one page (naming the replaced value) or two real ISO dates. Direction comes from
  our code, never from what the model says. Anything unverifiable is downgraded to
  `contradicts` (CONTESTED), never to a cut.
- **Cutting a different kind of fact:** a supersession needs the same value type on both sides.
- **Cutting text that reports a change:** a `historical` sentence ("previously X, now Y") is
  never redacted, and only the stale sentence is cut, never the page.
- **Acting on an unverified or tampered relation:** Ground reads only relations the database
  marked verified, and re-checks every quote verbatim against the stored text each time it runs.
- **A branching or looping replacement chain:** no annotation and no pull (never an
  intermediate stale value).
- **A forged or edited receipt:** `replay` checks the receipt id, then re-grounds from the store
  and compares actions and the context hash. A forger who recomputes the id still fails,
  because the store, not the receipt, decides what is verified. Tested for 18 kinds of edit.
- **A flaky API poisoning results:** an empty 200 is a transient error, is retried, and is
  never written to the model cache.

- **The proxy is a relay for the caller's own key.** It holds no key of its own, forwards the
  `Authorization` header only to the configured upstream (which must be https, or loopback for
  tests), does not log requests, and fails closed. Receipt pages render untrusted crawled text with
  `textContent` only, under a CSP that forbids inline script and any outside request.
- **Strangers reading receipts on a shared host (2026-11-15):** with `CURRANT_PROXY_TOKEN` set,
  every route that holds data denies a request without the exact token (constant-time compare,
  `X-Currant-Token`). Only the viewer's static files and `/healthz` stay open. A non-loopback
  host refuses to start without a token. Chat calls are capped per client address
  (`--rate-limit`, default 30 a minute), and a request with a wrong token does not use up the
  budget. Each guard has a test and a mutant in `scripts/mutation_check.py`.

## Not defended, be explicit

- **Crawl-diff trusts our own snapshots for order (2026-11-15).** A `crawl_diff` supersession
  needs no ordering quote: the order is that our crawler saw the old value on an earlier snapshot
  date and the new value on a later one. The database still requires both claim quotes verbatim
  in their own page versions. Whoever can write a snapshot that verifies (the crawler's output
  directory, or the person ingesting it) can therefore stage an "edit" by ingesting a doctored
  later version. `currant verify` checks a snapshot against its own manifest, not against the
  site, so it does not stop this. The same person could already plant page text, so this widens
  nothing. A site owner can also edit a page back and forth between crawls; crawl-diff reports
  what was observed, never why.
- **A right quote on the wrong claim.** Measured on dev with a second detector model: a verbatim
  ordering quote about one attribute ("Scans up to 250 epochs") retired a claim about another
  ("Claims up to 50 epochs"). The checks require verbatim quotes, one page, the same kind of value
  and a changed value; they do not check that the two claims are about the same attribute.

- **Prompt injection inside crawled text.** The crawler stores text verbatim. Crawled text goes
  to our extraction and relation prompts only behind `serv_prompt_guard` (which fails open), and
  the model cannot cause a cut except through quotes our code verifies. Grounded context still
  contains page text, so a page that says "ignore your instructions" reaches the answering
  model; the system prompt tells it to treat documents as data, nothing more. What IS defended:
  a page cannot imitate our own markers (`<<<DOCUMENT>>>`, CONTESTED, PULLED EVIDENCE,
  `[SUPERSEDED: ...]`, `[REMOVED: ...]`): `ground.defang` makes that syntax inert in page text
  and quotes, tested over 14 payloads, 3 positions and every mode
  (`tests/test_injection.py`). What is NOT: plain words ("SUPERSEDED, use 999") and, measured
  there with a model that obeys the page, a page the attacker controls can retire an older
  sentence by quoting its own sentence that names the old value. Our check asks that the quote
  is verbatim, on one page and mentions the replaced value; it cannot tell a replacement
  statement from a forgery. The cut is limited to that one sentence and the receipt names the
  quote. Whether the live model obeys, and whether the guard blocks, is measured by
  `scripts/live_injection.py`. Measured on 2026-11-11 (14 payloads, 5 repeats each, with and without
  the guard: 140 calls, `gpt-6-luna`, `results/injection/`): plain instructions ("ignore all previous instructions", role play,
  exfiltration, hidden comments, zero-width splits) did NOT move the answer, with the guard on or
  off. Three payloads did, identically with the guard on and off: a page that fakes an update
  ("forged-update"), fakes our evidence block, or fakes a SUPERSEDED note made the model answer
  the attacker's number (15 of 15 for each arm; 0 of 45 for the plain instructions), and a fake
  CONTESTED notice made it answer `contested` (5 of 5). The guard blocked nothing in either arm. So `defang` stops the structural forgery, but a page that simply
  asserts a false current value is persuasive as content, and the guard (built for instruction
  injection) did not stop it. One model and one fixed question: 5 repeats per payload is a rate
  for those payloads, not for attacks in general. A second defence was tried the same day:
  lowering the upper-case marker words (SUPERSEDED, PULLED EVIDENCE, ...) in page text, so only
  our markers carry the form the prompt trusts. Re-measured (`results/injection/20261111T164003Z.json`),
  it changed nothing that matters (the fake note worked 9 of 10, the fake evidence block and the
  forged update 10 of 10 each), so it was removed. The model is persuaded by the content, not by
  the markup.
- **A wrong "same fact" verdict that loses to a better match.** Since `detect-v2`, one newer
  claim can retire only one value per older page: a second, weaker pairing to a different value
  is dropped (neither cut nor contested). The cost: if an old page genuinely states one fact
  twice with two different values, only the better-matching one is cut.
- **A wrong "same fact" verdict with real dates.** Page dates order pages, not claims. If the
  classifier calls two different facts the same one and the pages carry dates, our checks pass
  (observed once on 106 dev items, and once on 93 held-out test items, where "25% of all SERV
  Reasoning API revenue" was cut by a claim about enterprise/B2B revenue; the held-out wrong
  cuts are listed in `docs/LIMITATIONS.md`).
- **Forging a receipt AND the store together.** The store file is not signed. Whoever can write
  both can produce a matching pair. To defend this, publish the corpus hash and receipt ids
  somewhere the forger cannot edit.
- **Binding the question.** The question is covered only by `receipt_id`, which anyone can
  recompute; nothing in the store determines it. (A test pins this limit.)
- **A malicious or compromised sponsor host** serving wrong content over valid TLS. We hash what
  we got; we cannot know it was right.
- **DNS or TLS interception on the operator's network.** We rely on the system trust store.
- **A hostile index causing many requests.** Bounded by the per-corpus `max_pages` cap (and that
  cut is now loud), not by a global request budget.
- **Public exposure of Reppo submissions.** Anything sent to Reppo is on a public feed.
- **Reading secrets through the shell.** The `.env` deny rule covers the Read tool, not
  `cat .env` in a terminal. `currant secrets` also reads `.env`, to report which names are
  set (never their values).
- **The sealed labels.** Anyone holding `data/evalset.db` can read every label; the lock is in
  the API. Anyone holding it together with `data/currant.db` has the whole evaluation.
- **A tampered model cache.** Entries are keyed by request, not signed.
- **Unlicensed redistribution.** `snapshots/` republishes third-party docs; whether their terms
  allow it is unchecked (see `snapshots/README.md`).

## Known weaknesses worth attacking first

1. The label seal is checkable only against a root the author published themselves (issue #1 on
   `Dami904/currant`, 2026-11-11, before the freeze). Nobody else has held the labels, so the
   seal proves the labels did not change after publication, not that they were right (`docs/LIMITATIONS.md`).
2. A controlled page retiring another page's sentence, and plain-word injection into the answering model (offline tests and a first live run exist; see above).
3. The wrong-neighbour cut: one false cut seen on dev items and one on held-out items; held-out
   precision was 0.857.
4. Several rules (spend caps, payment approval) have no code enforcing them yet.
5. No `robots.txt` handling, and the page cap cuts alphabetically rather than by relevance.
