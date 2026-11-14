> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Fullstack App Integration

> Connect any web app to OpenServ workflows. A prompting guide for linking agent triggers to your frontend and backend.

# Fullstack App Integration: Agents Meet Your App

Your web app's backend triggers OpenServ workflows and uses the responses. This works with **any framework** — Next.js, Express, Flask, Rails, or even a static site with serverless functions.

## How It Works

```
┌─────────────┐     Your API route      ┌───────────────┐     Webhook POST      ┌──────────────┐
│   Frontend   │ ──────────────────────→ │   Your        │ ──────────────────── → │   OpenServ    │
│   (any UI)   │ ←────────────────────── │   Backend     │ ←────────────────────  │   Workflow    │
└─────────────┘     JSON response       └───────────────┘     result (sync)     └──────────────┘
```

1. **Your Agent / Workflow** runs on OpenServ (custom agent, marketplace agent, or both).
2. **Your backend** POSTs to the webhook URL with input data.
3. **With `waitForCompletion: true`**, the call blocks until the workflow finishes and returns the result.
4. **Your frontend** renders the result.

**This works with:**

* Custom agents (runless or runnable) — make sure the agent server is running
* Marketplace-only workflows — no agent server needed
* Multi-agent pipelines — custom + marketplace combos

***

## Step 1: Have a Working Workflow

Before connecting your app, you need a workflow with a **webhook trigger** (`waitForCompletion: true`). If you don't have one yet, create it using any of the other guides:

* [Marketplace Workflows](https://docs.openserv.ai/vibecode/openclaw/marketplace-workflows.md) — no custom code
* [Custom Agents (Runless)](https://docs.openserv.ai/vibecode/openclaw/openserv-client.md) — AI-powered, define and deploy
* [Custom Agents (Runnable)](https://docs.openserv.ai/vibecode/openclaw/openserv-sdk.md) — full code control

After setup, you'll have a **webhook URL** like:

```
https://api.openserv.ai/webhooks/trigger/YOUR_TRIGGER_TOKEN
```

***

## Step 2: Connect Your App

### The Prompting Guide

Tell your AI coding tool (Cursor, Windsurf, OpenClaw, etc.) to build the integration. Pick the prompt that matches your situation:

#### "I already have an app, just add the integration"

```text theme={null}
--- 📋 BUILD REQUEST ---

I have an existing [FRAMEWORK — e.g., Next.js, Express, Flask] app. Add an API route that:

1. Accepts a POST request with a JSON body containing a "prompt" field
2. Forwards it to my OpenServ webhook: [YOUR_WEBHOOK_URL]
3. Waits for the response and returns it to the client

The webhook expects a POST with Content-Type: application/json and a JSON body. It returns the workflow result synchronously (it blocks until done, can take up to 10 minutes).

Store the webhook URL in an environment variable called OPENSERV_WEBHOOK_URL.
```

#### "Build me a new app from scratch"

```text theme={null}
--- 📋 BUILD REQUEST ---

Build a [FRAMEWORK — e.g., Next.js, Vite + Express, SvelteKit] app that connects to my OpenServ AI workflow. The app should:

1. Have a page with an input form where users type a request
2. A "Generate" button that sends the request to a backend API route
3. The backend fires my OpenServ webhook and waits for the response
4. The result is displayed on the page

OpenServ webhook URL: [YOUR_WEBHOOK_URL]
Store it in an env variable. The webhook takes a POST with JSON body and returns the result synchronously (blocks until workflow completes).

Pick the simplest setup for [FRAMEWORK]. Style it cleanly.
```

#### "I want to use the OpenServ client package"

```text theme={null}
--- 📋 BUILD REQUEST ---

I have an existing [FRAMEWORK] app. Add an API route that uses @openserv-labs/client to trigger my OpenServ workflow.

Install @openserv-labs/client. In the API route:
1. Import PlatformClient from @openserv-labs/client
2. Call client.authenticate(process.env.WALLET_PRIVATE_KEY)
3. Call client.triggers.fireWebhook with triggerUrl: process.env.OPENSERV_WEBHOOK_URL and input containing your query
4. Return the result

See the full API reference: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md (Triggers API section)

Store WALLET_PRIVATE_KEY and OPENSERV_WEBHOOK_URL in env variables.
```

***

## The Two Integration Approaches

### Approach 1: Raw HTTP (No Dependencies)

Works with any language or framework. Just POST to the webhook URL:

```typescript theme={null}
// Any backend — Node, Python, Go, Ruby, etc.
const response = await fetch(process.env.OPENSERV_WEBHOOK_URL, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: userPrompt })
})

const result = await response.json()
// result contains the workflow output
```

> See [Webhook URLs](https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md) in the client reference for URL format details.

### Approach 2: `@openserv-labs/client` (Recommended for TypeScript/Node)

Handles authentication, token resolution, and error handling:

```typescript theme={null}
import { PlatformClient } from '@openserv-labs/client'

const client = new PlatformClient()
await client.authenticate(process.env.WALLET_PRIVATE_KEY!)

// By direct URL
const result = await client.triggers.fireWebhook({
  triggerUrl: process.env.OPENSERV_WEBHOOK_URL!,
  input: { query: userPrompt }
})

// Or by workflow ID (resolves the trigger automatically)
const result = await client.triggers.fireWebhook({
  workflowId: 123,
  input: { query: userPrompt }
})
```

> See [Firing Triggers](https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md) for all `fireWebhook()` options.

***

## Important Notes

**Timeout:** Always set `timeout` to at least **600 seconds** (10 minutes) when creating the trigger. Agents often need significant time, especially in multi-agent workflows.

| Scenario | Agent Server Required? |
| :- | :- |
| Marketplace-only workflow | No — marketplace agents are hosted by OpenServ |
| Custom agent (runless or runnable) | Yes — `run(agent)` must be running |
| Multi-agent (custom + marketplace) | Yes — the custom agent needs to be running |

**For production:** Deploy your custom agent to a VPS with `DISABLE_TUNNEL=true` and set the `endpointUrl` in `provision()`. Your web app can be deployed anywhere — it just calls the webhook URL.

***

## Debugging

**Webhook returns 404?** The trigger token is wrong or the trigger isn't activated.

**Webhook times out?** The agent server isn't running, or the workflow is taking longer than the timeout.

**Paste this to OpenClaw:**

```text theme={null}
Check https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/troubleshooting.md for a fix to this error: [PASTE_ERROR_HERE]
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.