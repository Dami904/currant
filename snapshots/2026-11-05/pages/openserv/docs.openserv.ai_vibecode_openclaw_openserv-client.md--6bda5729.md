> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Custom OpenServ Agents (Runless Pattern)

> Build agents that use platform-managed LLM calls. Define a system prompt and capabilities — no custom code needed.

# Custom OpenServ Agents: Define & Deploy

A **Runless Agent** uses the Agent SDK (`@openserv-labs/sdk`) with **runless capabilities** — you define *what* the agent does, but the platform handles the *how*. No `run()` function, no API keys, no custom code. OpenServ's LLM does the work using your credits.

## The Concept

1. **Define:** Create an `Agent` with a `systemPrompt` and add capabilities with just a `name` + `description`.
2. **Provision:** Call `provision()` to register the agent, create a workflow, and set up a trigger — all in one call.
3. **Run:** Call `run(agent)` to start. Tunneling is automatic.

**⚠️ `run(agent)` starts a local server.** Make sure it's running before triggering any webhooks. Deploy to a VPS for always-on production use.

**Both packages are needed:**

```
@openserv-labs/sdk    → Agent, run, addCapability
@openserv-labs/client → provision, triggers
```

**Best for:**

* Agents driven by a good system prompt + model
* Text processing, Q\&A, analysis, summarization
* Anything that doesn't need external APIs or custom code

***

## The Master Template

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a runless OpenServ agent called "[AGENT_NAME]" with system prompt: "[DETAILED SYSTEM PROMPT]". Add a capability called "[CAPABILITY_NAME]" that "[WHAT_IT_DOES]". Create a workflow with a webhook trigger, fire it once with "[TEST_PROMPT]", and print the response.

--- 🤖 OPENSERV GUARDRAILS (standard — don't change) ---

Read ALL of these skills before writing any code:
- openserv-client: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md
- openserv-client reference: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md
- openserv-agent-sdk: https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/SKILL.md
- openserv-multi-agent-workflows: https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/SKILL.md

CONCEPT → CODE:

Auth: provision() creates/reuses wallet, writes WALLET_PRIVATE_KEY to .env on first run. The ONLY key — do NOT invent OPENSERV_USER_API_KEY, OPENSERV_API_KEY, or any other. All API calls via client library (no raw HTTP), EXCEPT integration attachment POST (x-openserv-key header).

Triggers: webhook → triggers.webhook({ waitForCompletion: true, timeout: 600 }); cron → triggers.cron(schedule); x402 → triggers.x402. Always activate after creation.
⚠️ Telegram trigger requires dedicated wiring (provision() does NOT handle integration triggers):
  1. Create trigger: client.triggers.create({ workflowId, name, integrationConnectionId, trigger_name: 'on-message', props: { regexMatch: '.*' } }) + activate
  2. Create task: client.tasks.create({ workflowId, agentId, description })
  3. Attach integration to task via REST: POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId } — use header x-openserv-key: userApiKey (the string returned by client.authenticate(WALLET_PRIVATE_KEY), NOT Bearer)
  4. Wire trigger→task graph: client.put(`/workspaces/${workflowId}/sync`, { workflow: { nodes: [triggerNode, taskNode], edges: [{ source, target, sourcePort, targetPort }] } }) — do NOT use POST /edges (returns 404)
  5. Set running: client.workflows.setRunning({ id: workflowId })

Integrations: User adds in UI first (Connect → Integrations). Discover: listConnections() or getOrCreateConnection('name'). Available: telegram-bot, twitter-v2, slack, youtube, google-mail, google-calendar, google-drive, jira. Attach to task (required, declarative does NOT work): POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId: id }. If missing, STOP and tell user to add in UI.

Agents: Marketplace → client.agents.listMarketplace(), assign by id. Runless → Agent({ systemPrompt }) + addCapability({ name, description }) + provision() + run(). Runnable → same + inputSchema + run function. Custom agents must be running before triggering.

Workflows: Goal must be DETAILED (not "test"). Single-agent: provision() handles everything (agent, workflow, trigger, task, edges, activation). Multi-agent: client.workflows.sync() with tasks/edges arrays, named refs (from: 'trigger:webhook', to: 'task:process').

Project: FIRST search cwd for an existing openserv-agents folder (or similar: openserv-project, agents, etc.) and check for .env with WALLET_PRIVATE_KEY. If found → use that folder and its .env, create your script inside it. ONLY if no such folder exists → create openserv-agents (npm init, @openserv-labs/sdk + @openserv-labs/client, .env with WALLET_PRIVATE_KEY). If unsure, STOP and ask the user if they already have an OpenServ project folder set up.

Execute: RUN with `npx tsx <file>.ts` — don't just write it. Print workflowId, triggerId, taskId(s). Verify: webhook → fire + print result; Telegram → "send a message to test"; cron → print schedule; x402 → print result.paywallUrl.
```

***

## Example Recipes

### 1. The "Legal Contract Reviewer"

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a runless agent called "Legal Contract Reviewer" with this system prompt: "You are a senior legal analyst. When given a contract, identify key risks, missing clauses, and potential liabilities. Structure: 1) Summary, 2) Key Risks, 3) Missing Clauses, 4) Recommendations." Add a capability called "reviewContract" that reviews contracts. Create a webhook, fire it once with "Review this NDA: The party agrees to disclose all proprietary information without limitation of liability", and show me the result.

--- 🤖 OPENSERV GUARDRAILS (standard — don't change) ---

Read ALL of these skills before writing any code:
- openserv-client: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md
- openserv-client reference: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md
- openserv-agent-sdk: https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/SKILL.md
- openserv-multi-agent-workflows: https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/SKILL.md

CONCEPT → CODE:

Auth: provision() creates/reuses wallet, writes WALLET_PRIVATE_KEY to .env on first run. The ONLY key — do NOT invent OPENSERV_USER_API_KEY, OPENSERV_API_KEY, or any other. All API calls via client library (no raw HTTP), EXCEPT integration attachment POST (x-openserv-key header).

Triggers: webhook → triggers.webhook({ waitForCompletion: true, timeout: 600 }); cron → triggers.cron(schedule); x402 → triggers.x402. Always activate after creation.
⚠️ Telegram trigger requires dedicated wiring (provision() does NOT handle integration triggers):
  1. Create trigger: client.triggers.create({ workflowId, name, integrationConnectionId, trigger_name: 'on-message', props: { regexMatch: '.*' } }) + activate
  2. Create task: client.tasks.create({ workflowId, agentId, description })
  3. Attach integration to task via REST: POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId } — use header x-openserv-key: userApiKey (the string returned by client.authenticate(WALLET_PRIVATE_KEY), NOT Bearer)
  4. Wire trigger→task graph: client.put(`/workspaces/${workflowId}/sync`, { workflow: { nodes: [triggerNode, taskNode], edges: [{ source, target, sourcePort, targetPort }] } }) — do NOT use POST /edges (returns 404)
  5. Set running: client.workflows.setRunning({ id: workflowId })

Integrations: User adds in UI first (Connect → Integrations). Discover: listConnections() or getOrCreateConnection('name'). Available: telegram-bot, twitter-v2, slack, youtube, google-mail, google-calendar, google-drive, jira. Attach to task (required, declarative does NOT work): POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId: id }. If missing, STOP and tell user to add in UI.

Agents: Marketplace → client.agents.listMarketplace(), assign by id. Runless → Agent({ systemPrompt }) + addCapability({ name, description }) + provision() + run(). Runnable → same + inputSchema + run function. Custom agents must be running before triggering.

Workflows: Goal must be DETAILED (not "test"). Single-agent: provision() handles everything (agent, workflow, trigger, task, edges, activation). Multi-agent: client.workflows.sync() with tasks/edges arrays, named refs (from: 'trigger:webhook', to: 'task:process').

Project: FIRST search cwd for an existing openserv-agents folder (or similar: openserv-project, agents, etc.) and check for .env with WALLET_PRIVATE_KEY. If found → use that folder and its .env, create your script inside it. ONLY if no such folder exists → create openserv-agents (npm init, @openserv-labs/sdk + @openserv-labs/client, .env with WALLET_PRIVATE_KEY). If unsure, STOP and ask the user if they already have an OpenServ project folder set up.

Execute: RUN with `npx tsx <file>.ts` — don't just write it. Print workflowId, triggerId, taskId(s). Verify: webhook → fire + print result; Telegram → "send a message to test"; cron → print schedule; x402 → print result.paywallUrl.
```

### 2. The "Brand Voice Writer"

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a runless agent called "Brand Voice Writer" with this system prompt: "You are a copywriter for a premium tech brand. Tone: confident, minimal, slightly playful. Never use exclamation marks. Short paragraphs. Always produce 3 variations: formal, casual, and tweet-length." Add a capability called "writeCopy". Create a webhook, fire it once with "Write about our new AI-powered search feature", and show me the 3 variations.

--- 🤖 OPENSERV GUARDRAILS (standard — don't change) ---

Read ALL of these skills before writing any code:
- openserv-client: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md
- openserv-client reference: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md
- openserv-agent-sdk: https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/SKILL.md
- openserv-multi-agent-workflows: https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/SKILL.md

CONCEPT → CODE:

Auth: provision() creates/reuses wallet, writes WALLET_PRIVATE_KEY to .env on first run. The ONLY key — do NOT invent OPENSERV_USER_API_KEY, OPENSERV_API_KEY, or any other. All API calls via client library (no raw HTTP), EXCEPT integration attachment POST (x-openserv-key header).

Triggers: webhook → triggers.webhook({ waitForCompletion: true, timeout: 600 }); cron → triggers.cron(schedule); x402 → triggers.x402. Always activate after creation.
⚠️ Telegram trigger requires dedicated wiring (provision() does NOT handle integration triggers):
  1. Create trigger: client.triggers.create({ workflowId, name, integrationConnectionId, trigger_name: 'on-message', props: { regexMatch: '.*' } }) + activate
  2. Create task: client.tasks.create({ workflowId, agentId, description })
  3. Attach integration to task via REST: POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId } — use header x-openserv-key: userApiKey (the string returned by client.authenticate(WALLET_PRIVATE_KEY), NOT Bearer)
  4. Wire trigger→task graph: client.put(`/workspaces/${workflowId}/sync`, { workflow: { nodes: [triggerNode, taskNode], edges: [{ source, target, sourcePort, targetPort }] } }) — do NOT use POST /edges (returns 404)
  5. Set running: client.workflows.setRunning({ id: workflowId })

Integrations: User adds in UI first (Connect → Integrations). Discover: listConnections() or getOrCreateConnection('name'). Available: telegram-bot, twitter-v2, slack, youtube, google-mail, google-calendar, google-drive, jira. Attach to task (required, declarative does NOT work): POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId: id }. If missing, STOP and tell user to add in UI.

Agents: Marketplace → client.agents.listMarketplace(), assign by id. Runless → Agent({ systemPrompt }) + addCapability({ name, description }) + provision() + run(). Runnable → same + inputSchema + run function. Custom agents must be running before triggering.

Workflows: Goal must be DETAILED (not "test"). Single-agent: provision() handles everything (agent, workflow, trigger, task, edges, activation). Multi-agent: client.workflows.sync() with tasks/edges arrays, named refs (from: 'trigger:webhook', to: 'task:process').

Project: FIRST search cwd for an existing openserv-agents folder (or similar: openserv-project, agents, etc.) and check for .env with WALLET_PRIVATE_KEY. If found → use that folder and its .env, create your script inside it. ONLY if no such folder exists → create openserv-agents (npm init, @openserv-labs/sdk + @openserv-labs/client, .env with WALLET_PRIVATE_KEY). If unsure, STOP and ask the user if they already have an OpenServ project folder set up.

Execute: RUN with `npx tsx <file>.ts` — don't just write it. Print workflowId, triggerId, taskId(s). Verify: webhook → fire + print result; Telegram → "send a message to test"; cron → print schedule; x402 → print result.paywallUrl.
```

### 3. The "Text-to-Image Pipeline" (Runless + Marketplace Combo)

Your runless agent writes a vivid visual description, then Nano Banana Pro turns it into an image.

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a two-agent pipeline: First, a runless agent called "Creative Director" with system prompt "You are a visual art director. When given a concept (e.g., 'solarpunk city'), write a single detailed image prompt: describe the scene, lighting, color palette, composition, and mood in one rich paragraph. Output ONLY the image prompt, nothing else." Then, hand off that image prompt to the Nano Banana Pro marketplace agent to generate the image. Chain both in one workflow, fire it once with "a cyberpunk ramen shop at midnight", and show me the generated image URL.

--- 🤖 OPENSERV GUARDRAILS (standard — don't change) ---

Read ALL of these skills before writing any code:
- openserv-client: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md
- openserv-client reference: https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md
- openserv-agent-sdk: https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/SKILL.md
- openserv-multi-agent-workflows: https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/SKILL.md

CONCEPT → CODE:

Auth: provision() creates/reuses wallet, writes WALLET_PRIVATE_KEY to .env on first run. The ONLY key — do NOT invent OPENSERV_USER_API_KEY, OPENSERV_API_KEY, or any other. All API calls via client library (no raw HTTP), EXCEPT integration attachment POST (x-openserv-key header).

Triggers: webhook → triggers.webhook({ waitForCompletion: true, timeout: 600 }); cron → triggers.cron(schedule); x402 → triggers.x402. Always activate after creation.
⚠️ Telegram trigger requires dedicated wiring (provision() does NOT handle integration triggers):
  1. Create trigger: client.triggers.create({ workflowId, name, integrationConnectionId, trigger_name: 'on-message', props: { regexMatch: '.*' } }) + activate
  2. Create task: client.tasks.create({ workflowId, agentId, description })
  3. Attach integration to task via REST: POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId } — use header x-openserv-key: userApiKey (the string returned by client.authenticate(WALLET_PRIVATE_KEY), NOT Bearer)
  4. Wire trigger→task graph: client.put(`/workspaces/${workflowId}/sync`, { workflow: { nodes: [triggerNode, taskNode], edges: [{ source, target, sourcePort, targetPort }] } }) — do NOT use POST /edges (returns 404)
  5. Set running: client.workflows.setRunning({ id: workflowId })

Integrations: User adds in UI first (Connect → Integrations). Discover: listConnections() or getOrCreateConnection('name'). Available: telegram-bot, twitter-v2, slack, youtube, google-mail, google-calendar, google-drive, jira. Attach to task (required, declarative does NOT work): POST /workspaces/{workflowId}/tasks/{taskId}/integration-connections { integrationConnectionId: id }. If missing, STOP and tell user to add in UI.

Agents: Marketplace → client.agents.listMarketplace(), assign by id. Runless → Agent({ systemPrompt }) + addCapability({ name, description }) + provision() + run(). Runnable → same + inputSchema + run function. Custom agents must be running before triggering.

Workflows: Goal must be DETAILED (not "test"). Single-agent: provision() handles everything (agent, workflow, trigger, task, edges, activation). Multi-agent: client.workflows.sync() with tasks/edges arrays, named refs (from: 'trigger:webhook', to: 'task:process').

Project: FIRST search cwd for an existing openserv-agents folder (or similar: openserv-project, agents, etc.) and check for .env with WALLET_PRIVATE_KEY. If found → use that folder and its .env, create your script inside it. ONLY if no such folder exists → create openserv-agents (npm init, @openserv-labs/sdk + @openserv-labs/client, .env with WALLET_PRIVATE_KEY). If unsure, STOP and ask the user if they already have an OpenServ project folder set up.

Execute: RUN with `npx tsx <file>.ts` — don't just write it. Print workflowId, triggerId, taskId(s). Verify: webhook → fire + print result; Telegram → "send a message to test"; cron → print schedule; x402 → print result.paywallUrl.
```

***

## How It Works

| Step | What Happens |
| :- | :- |
| **`new Agent()`** | Defines your agent with a system prompt. |
| **`addCapability()`** | Tells the platform what this agent can do (runless = no code). |
| **`provision()`** | Registers agent, creates workflow, sets up trigger — all idempotent. |
| **`run(agent)`** | Starts the agent server with automatic tunneling. |

***

## Comparison: Runless vs Runnable

| Feature | Runless (This Guide) | Runnable (Agent SDK Guide) |
| :- | :- | :- |
| **Capability** | `{ name, description }` | `{ name, description, inputSchema, run() }` |
| **Custom Code** | None — platform handles LLM | Full TypeScript in `run()` |
| **External APIs** | No — not possible | Yes — fetch, databases, SDKs |
| **LLM Calls** | Platform-managed (auto) | `this.generate()` (manual) |
| **Use Case** | Prompt-driven tasks | Code-driven tasks |

***

## Debugging

If something isn't working, paste this to OpenClaw:

```text theme={null}
Check https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/troubleshooting.md for a fix to this error: [PASTE_ERROR_HERE]
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.