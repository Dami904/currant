# Reppo Eval Router — Agent Integration Guide

This document tells an AI agent (Claude, Codex, GPT, or any other model) how to
submit evaluations to Reppo Eval Router over HTTP. Point your agent at this
file directly (`https://eval.reppo.xyz/agents.md`), or paste its contents into its
system prompt / context.

No account? An agent with a Base wallet holding USDC can buy prepaid credits
over x402 instead and evaluate with a credit token, no API key needed. See
section 6.

## 1. Get an API key

API keys are personal and tied to a signed-in account — an agent cannot
generate its own key. A human has to:

1. Sign in at `https://eval.reppo.xyz`
2. Go to **API Key** in the sidebar (`https://eval.reppo.xyz/api-key`)
3. Click **Generate API key** and copy it — it's only ever shown once

Give the agent that key as a secret (e.g. an environment variable). Every
request below authenticates with:

```
Authorization: Bearer YOUR_API_KEY
```

## 2. Credits

- New accounts start with **22,000 credits** (a one-time sign-up bonus).
- A text-only evaluation costs **440 credits**; one with an
  image or PDF attached costs **1,000 credits** —
  50 text evaluations from the sign-up bonus alone.
- Credits are only charged once the evaluation `COMPLETED`. A `FAILED`
  evaluation costs nothing.
- More credits are purchased by a human via **Billing** (`https://eval.reppo.xyz/billing`)
  — there is no API endpoint for purchasing account credits (x402 wallet
  credits are the keyless alternative — see section 6).
- Multiple evaluations may be in flight at once. Each one reserves its price
  against your balance until it finishes, so submitting several needs enough
  credits to cover all of them.

## 3. Submit an evaluation

`POST https://eval.reppo.xyz/api/v1/agents/evals`

Evaluations are queued and scored in the background by a panel of
independent evaluators, usually within 30–90 seconds. Submitting returns
straight away with the evaluation's `id` — poll section 4 for the result.

```bash
curl -X POST "https://eval.reppo.xyz/api/v1/agents/evals" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "taskType": "response",
    "input": "User prompt: What is 15% of 200?\n\nAI response: 15% of 200 is 35."
  }'
```

### Request body

| Field         | Type          | Required | Limits |
|---------------|---------------|----------|--------|
| `taskType`    | string (enum) | Yes      | `claim` (a statement to fact-check), `response` (an AI response — include the user's prompt too) or `action` (an agent action — include what the user asked for too) |
| `input`       | string        | Yes      | Non-empty, max 50 KB |
| `attachments` | array         | No       | Max 1 item, 1.25 MB each — `image/png`, `image/jpeg`, `image/webp` or `application/pdf` (see section 5 for how to get a `key`). The attachment is part of the submission — say in `input` what to assess about it. |

### Response — `201 Created`

The same shape as section 4, with `status` `QUEUED` and no result yet.
Save `id` — that's what you read the result back with.

### Errors

| Status | Cause |
|--------|-------|
| 400    | Request body failed validation, or an attachment is missing or too large |
| 401    | Missing or invalid API key |
| 402    | Insufficient credits — 440 credits for a text-only evaluation, 1,000 with an attachment |
| 500    | Unexpected server error |
| 502    | The evaluation couldn't be queued (it's returned as `FAILED` and not charged) — try again |

## 4. Read an evaluation result

`GET https://eval.reppo.xyz/api/v1/agents/evals/{id}`

```bash
curl "https://eval.reppo.xyz/api/v1/agents/evals/YOUR_EVAL_ID" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Poll this (every few seconds is fine) until `status` is `COMPLETED` or
`FAILED`.

### Response — `200 OK`

```json
{
  "id": "string",
  "taskType": "claim" | "response" | "action",
  "source": "WEB" | "API" | "X402",
  "input": "string",
  "status": "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED",
  "score": 82,
  "route": "ship" | "review" | "block",
  "creditsCharged": 440,
  "createdAt": "2024-01-01T00:00:00.000Z",
  "startedAt": "2024-01-01T00:00:02.000Z",
  "completedAt": "2024-01-01T00:00:58.000Z",
  "attachments": [{ "filename": "string", "contentType": "string" }],
  "result": {
    "score": 82,
    "decision": "accept" | "reject",
    "confidence": "low" | "medium" | "high",
    "route": "ship" | "review" | "block",
    "reason": "string",
    "rubric_scores": { "accuracy": 85 },
    "consensus": { "...": "how the evaluators' scores were combined" },
    "gates": [],
    "explain": { "confidence_checks": [], "route_reasons": ["string"] }
  },
  "trace": { "...": "each evaluator's scores and reasoning" },
  "error": null
}
```

`score`, `route` and `result` stay `null` until the evaluation is
`COMPLETED`, and `creditsCharged` stays `0` until then. What to act on:

- `result.route` — the recommendation: `ship` (good to use), `review`
  (needs a human look) or `block` (don't use it).
- `result.score` — 0–100 overall quality; `result.decision` — accept or
  reject at the policy threshold; `result.confidence` — how much the
  evaluators agreed.
- `result.reason` — a one-paragraph explanation; `result.rubric_scores` —
  the per-dimension breakdown.

A `FAILED` evaluation wasn't charged — submit it again.

### Errors

| Status | Cause |
|--------|-------|
| 401    | Missing or invalid API key |
| 404    | No evaluation with that `id`, or it belongs to a different account |
| 500    | Unexpected server error |

## 5. Submit with an attachment

Optional — only needed if you want to attach a file. It's three calls:
request an upload URL, `PUT` the file bytes to it, then submit the
evaluation with the returned `key`. Only 1 attachment per evaluation is
allowed.

### 5a. Request an upload URL

`POST https://eval.reppo.xyz/api/v1/agents/evals/attachments`

```bash
curl -X POST "https://eval.reppo.xyz/api/v1/agents/evals/attachments" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "screenshot.png",
    "contentType": "image/png"
  }'
```

| Field         | Type          | Required | Limits |
|---------------|---------------|----------|--------|
| `filename`    | string        | Yes      | 1–255 characters |
| `contentType` | string (enum) | Yes      | One of `image/png`, `image/jpeg`, `image/webp`, `application/pdf` |

Returns `200 OK` with `{ "key": "string", "uploadUrl": "string" }`.
`uploadUrl` expires in 5 minutes. The 1.25 MB size limit isn't enforced here —
it's checked when you submit the evaluation in step 5c.

### 5b. Upload the file to that URL

The file bytes go straight to storage, not through this API:

```bash
curl -X PUT "UPLOAD_URL_FROM_RESPONSE" \
  -H "Content-Type: image/png" \
  --data-binary "@screenshot.png"
```

Use `PUT` (not `POST`) — the URL is signed specifically for `PUT`, and
any other method will fail signature verification.

### 5c. Submit the evaluation with the attachment

```bash
curl -X POST "https://eval.reppo.xyz/api/v1/agents/evals" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "taskType": "response",
    "input": "User prompt: Summarise this chart.\n\nAI response: Revenue grew 40% year on year. Check the summary against the attached chart.",
    "attachments": [
      {
        "key": "KEY_FROM_STEP_5A",
        "filename": "screenshot.png",
        "contentType": "image/png"
      }
    ]
  }'
```

Same request as section 3, just with `attachments` filled in.

## 6. Pay with x402 (no account)

An agent with its own wallet can skip the Reppo account and API key entirely.
It buys prepaid credits with one [x402](https://x402.org) payment in USDC on
Base, gets a **credit token** back, and spends the credits on evaluations
with that token. An evaluation costs 440 credits ($0.22);
1 USDC buys 2,000 credits.

It's three steps: buy credits, submit an evaluation, then poll for the
result.

### 1. Buy credits

`POST https://eval.reppo.xyz/api/v1/x402/credits?usd=AMOUNT`

`usd` is a whole number of USDC from 1 to 100. No request body. It's paid
over x402:

1. Send the request with no payment. You get `402 Payment Required` with
   the payment terms (price, network, asset, `payTo`) base64-encoded in the
   `PAYMENT-REQUIRED` response header.
2. Sign a payment for those terms with your wallet and resend the identical
   request with it in the `PAYMENT-SIGNATURE` header.
3. The payment is only collected if you get a `2xx` back.

Don't build the payment by hand — use an x402 client, which does steps 1–2
for you:

```ts
import { wrapAxiosWithPayment, x402Client } from "@x402/axios";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import axios from "axios";
import { privateKeyToAccount } from "viem/accounts";

const client = new x402Client();
registerExactEvmScheme(client, { signer: privateKeyToAccount(process.env.WALLET_PRIVATE_KEY) });
const api = wrapAxiosWithPayment(axios.create(), client);

const { data } = await api.post("https://eval.reppo.xyz/api/v1/x402/credits?usd=5");
// First purchase for this wallet: save data.creditToken - it's shown once
```

The wallet only needs USDC on Base — no ETH, since the payment is a signed
authorization and the facilitator pays the gas.

Response — `201 Created`:

```json
{
  "walletAddress": "0x...",
  "creditsPurchased": 10000,
  "creditToken": "x402ck_..."
}
```

- `creditToken` is returned **once**, on the wallet's first purchase. Store
  it as a secret — anyone holding it can spend the wallet's credits.
- Later purchases are top-ups: credits are added and the same token keeps
  working, so the response has no `creditToken`.
- Lost the token? Buy again with `&newKey=true` (any amount). That returns a
  new token and the old one stops working. Your balance is kept.
- Credits (and any new token) only take effect once the payment settles. If
  settlement fails, nothing changes.

### 2. Submit an evaluation

`POST https://eval.reppo.xyz/api/v1/x402/evals`

```bash
curl -X POST "https://eval.reppo.xyz/api/v1/x402/evals" \
  -H "Authorization: Bearer YOUR_CREDIT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"taskType":"claim","input":"Claim: The Great Wall of China is visible from space with the naked eye."}'
```

| Field      | Type          | Required | Limits |
|------------|---------------|----------|--------|
| `taskType` | string (enum) | Yes      | `claim` (a statement to fact-check), `response` (an AI response — include the user's prompt too) or `action` (an agent action — include what the user asked for too) |
| `input`    | string        | Yes      | Non-empty, max 50 KB |

Attachments aren't supported with a credit token — submit text only.

The evaluation is queued and scored in the background by a panel of
independent evaluators, usually within 30–90 seconds. The response —
`201 Created` — is the evaluation with `status` `QUEUED` and no result
yet; save its `id`.

Credits are only charged when the evaluation `COMPLETED`. A `FAILED`
evaluation costs nothing. You can have several evaluations in flight at once:
each reserves its price against your balance until it finishes.

### 3. Read the result

`GET https://eval.reppo.xyz/api/v1/x402/evals/{id}`

```bash
curl "https://eval.reppo.xyz/api/v1/x402/evals/YOUR_EVAL_ID" \
  -H "Authorization: Bearer YOUR_CREDIT_TOKEN"
```

Poll this (every few seconds is fine) until `status` is `COMPLETED` or
`FAILED`. The response is the same shape as reading an evaluation with an
API key (section 4 of `https://eval.reppo.xyz/agents.md`) — act on `result.route`:
`ship`, `review` or `block`. The token only reads its own wallet's
evaluations.

### Check your balance

```bash
curl "https://eval.reppo.xyz/api/v1/x402/credits" \
  -H "Authorization: Bearer YOUR_CREDIT_TOKEN"
```

```json
{ "walletAddress": "0x...", "balance": 9560 }
```

### Errors

| Status | Cause |
|--------|-------|
| 400    | Buying: `usd` missing, not a whole number, or outside 1–100. Evaluating: the body failed validation, or it included `attachments` |
| 401    | The credit token is missing, wrong, or was replaced by a `newKey=true` purchase |
| 402    | Buying: no payment, an invalid payment, or settlement failed. Evaluating: not enough credits — buy more |
| 404    | Reading: no evaluation with that `id` for this wallet |
| 409    | Buying: the payment authorization was already used |
| 502    | The evaluation couldn't be queued (it's returned as `FAILED` and not charged) — try again |
| 503    | x402 payments are temporarily unavailable, or this month's purchase limit was reached (buying only) |
| 500    | Unexpected server error |

## 7. Loop

Re-run the same evaluation on a fixed interval, e.g. to watch how a result
holds up over time. There's no loop endpoint — your agent does it itself:
submit, poll until the result is ready, wait the interval, repeat. Each run
is an ordinary evaluation and is charged as one.

1. Pick an interval, e.g. 1, 2, 5 or 10 minutes.
2. Submit the evaluation (section 3 with an API key, or section 6 step 2 with
   a credit token) and keep the returned `id`.
3. Poll the read endpoint every few seconds until `status` is `COMPLETED`
   or `FAILED`. Record the result.
4. Sleep for the interval, then repeat from step 2 with the same body.

Rules:

- Set a run limit. Every completed run is charged, and nothing stops the loop
  for you.
- Stop on `400`, `401` or `402` (bad body, bad key or token, out of
  credits). A `FAILED` run cost nothing, so it's safe to carry on at the
  next tick.

With a credit token (swap the URLs for `/api/v1/agents/evals` and your API
key to do the same with an account):

```bash
INTERVAL_MINUTES=5
MAX_RUNS=12
AUTH="Authorization: Bearer $REPPO_CREDIT_TOKEN"

for run in $(seq 1 "$MAX_RUNS"); do
  id=$(curl -sS -X POST "https://eval.reppo.xyz/api/v1/x402/evals" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d '{"taskType":"claim","input":"Claim: The Great Wall of China is visible from space with the naked eye."}' \
    | jq -r '.id // empty')
  [ -z "$id" ] && break   # 400, 401 or 402 - stop and check

  while :; do
    status=$(curl -sS "https://eval.reppo.xyz/api/v1/x402/evals/$id" -H "$AUTH" | tee "run-$run.json" | jq -r '.status')
    [ "$status" = "COMPLETED" ] || [ "$status" = "FAILED" ] && break
    sleep 5
  done
  echo "run $run: $status"

  [ "$run" -lt "$MAX_RUNS" ] && sleep $((INTERVAL_MINUTES * 60))
done
```

## 8. Removed endpoints (deprecated)

These endpoints have been removed and now return `404`. Switch to
the replacements — the request and response shapes changed, see sections
3–5.

| Removed | Replacement |
|---------|-------------|
| `POST /api/v1/agents/eval-requests/submit` (`type`, `payload`, `criteria`, `context`, `settlementMinutes`) | `POST /api/v1/agents/evals` (`taskType`, `input`) — section 3 |
| `GET /api/v1/agents/eval-requests/{evalId}` | `GET /api/v1/agents/evals/{id}` — section 4 |
| `POST /api/v1/agents/eval-requests/attachments` | `POST /api/v1/agents/evals/attachments` — section 5 |
| `GET /api/v1/agents/eval-requests/pending` and `POST /api/v1/agents/eval-requests/{evalId}/assessments` (peer assessment) | Removed — evaluations are scored by the evaluator panel, with no settlement window to assess in |
| `POST /api/v1/x402/evals/lite` with a credit token | `POST /api/v1/x402/evals` (`taskType`, `input`), then poll — section 6 |
| `POST /api/v1/x402/evals/lite` paid per request over x402, and `Sandbox: true` | Removed — buy prepaid credits instead (section 6, step 1) |
| `GET /api/v1/x402/evals/{evalId}` with a `readToken` | `GET /api/v1/x402/evals/{id}` with your credit token — section 6 |

Results are no longer an `accept` / `revise` / `reject` verdict from a
single judge after a settlement window: each evaluation is scored 0–100 by
a panel of evaluators and routed `ship` / `review` / `block`.

## 9. Use it as an MCP server

Instead of calling the HTTP API yourself, you can connect an MCP-capable client
(Claude, ChatGPT, Claude Code, Cursor, ...) to the Eval Router and let it call
the evaluation tools directly.

Server URL (Streamable HTTP): `https://eval.reppo.xyz/api/mcp` (beta). Setup steps are also
on the **MCP** page in the sidebar (`https://eval.reppo.xyz/mcp`).

### Connecting

- **Claude / ChatGPT (chat apps):** add a custom connector (in ChatGPT this needs
  developer mode) and give it the server URL above. You'll be sent to sign in to
  your account and approve access, no API key needed. Approving lets the
  connector read your evals and submit new ones **using your credits**.
- **Claude Code, Cursor and other clients that accept headers:** use your API key
  from section 1 instead:

```bash
claude mcp add --transport http reppo-eval https://eval.reppo.xyz/api/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

```json
{
  "mcpServers": {
    "reppo-eval": {
      "url": "https://eval.reppo.xyz/api/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

### Tools

| Tool | What it does |
|------|--------------|
| `submit_eval` | Submit text for evaluation (`taskType`: `claim` / `response` / `action`, plus `input`). Spends credits. Returns an eval id straight away. |
| `get_eval` | Status and result of one of your evals, by id. Poll until `status` is `COMPLETED` or `FAILED`. |
| `get_credit_balance` | Your remaining credits. |

Evals run asynchronously, the same as the HTTP API: `submit_eval` returns an
id, then `get_eval` until it's done. `get_eval` only returns your own evals.

Attachments and x402 payment aren't available over MCP. Use sections 5 and 6
for those.
