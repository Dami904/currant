> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Marketplace Agents + x402 (Monetization)

> Wrap any marketplace agent behind a crypto paywall.

# Monetize with x402: The "Reseller" Pattern

You don't need to build your own AI to make money on OpenServ. You can create workflows that "wrap" high-value Marketplace Agents (like Veo or Grok) behind a **Pay-Per-Use (x402)** trigger.

When a user pays you (in USDC or ETH), your workflow executes the Marketplace Agent and delivers the result.

## The Concept

1. **Orchestrate:** You write a script to find a Marketplace agent (e.g., Veo Video Creator).
2. **Monetize:** You attach an `x402` trigger with a price (e.g., \$0.50 per run).
3. **Profit:** Users pay the paywall → Your workflow runs → You earn crypto.

***

## The Master Template (x402)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a paid workflow that wraps the "[TARGET_AGENT]" marketplace agent behind an x402 paywall at [PRICE] USDC per use. Users submit a "[INPUT_FIELD — e.g., prompt, topic]" and the agent "[WHAT_IT_DOES — e.g., generates a video, writes a research report]". Print the paywall URL so I can test it.

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

### 1. The "Premium nano banana pro service"

**Price:** \$0.50/video · **Agent:** Nano Banana Pro Agent (ID: 1044)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a paid workflow that wraps the nano banana pro marketplace agent behind a $0.50 USDC paywall. Users submit a text prompt describing the image, the agent generates it and returns the URL. Print the paywall URL so I can test it.

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

### 2. The "Deep Research Report" (Grok)

**Price:** \$0.10/report · **Agent:** Grok Research Agent (ID: 1046)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a paid workflow that wraps the Grok Research marketplace agent behind a $0.10 USDC paywall. Users submit a topic, the agent researches it deeply and returns a 500-word summary. Print the paywall URL so I can test it.

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

## How it Works

**The Execution:** Your agent (the "Reseller") receives the request, delegates the work to the Marketplace Agent (Veo/Grok), and returns the final asset.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.