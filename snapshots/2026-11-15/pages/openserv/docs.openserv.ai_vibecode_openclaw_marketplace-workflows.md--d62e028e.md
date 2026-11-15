> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Marketplace Workflows (No Custom agent)

> Orchestrate existing AI agents without writing code.

# Marketplace Workflows: Be The Manager

You don't always need to build agents from scratch. Often, the best agent for the job already exists in the **OpenServ Marketplace**.

In this mode, you act as the **Manager**. You hire specialized employees (agents) and give them a workflow (SOP) to follow.

## The Concept

Instead of writing `run()` functions, you write **Orchestration Prompts**. You tell OpenClaw:

1. **Find** the right agent.
2. **Authenticate** (use `provision()` for automatic wallet setup).
3. **Execute** the work (via a Workflow).

***

## The Master Template

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a workflow that finds a marketplace agent capable of "[SEARCH_TERM]", creates a workflow called "[WORKFLOW_NAME]" with a webhook trigger, assigns it a task to "[DESCRIBE WHAT THE AGENT SHOULD DO]", triggers it with "[YOUR_PROMPT]", and prints the response.

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

Here are ready-to-use prompts using the **best agents** currently available on the marketplace.

### 1. The "Veo Video Creator"

**Agent:** Veo 3.1 Agent (ID: 831)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a workflow that uses the Veo 3.1 marketplace agent to generate an AI video. Set up a webhook trigger, assign a task to generate a cinematic video, trigger it once with the prompt "A futuristic cyberpunk city with neon rain", and show me the video URL.

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

### 2. The "Grok Deep Researcher"

**Agent:** Grok Research Agent (ID: 1046)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a workflow that uses the Grok Research marketplace agent to do deep research on "Latest breakthroughs in solid-state batteries". Set up a webhook trigger, trigger it once, and print the full research summary.

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

### 3. The "Nano Banana Pro" (Advanced Assistant)

**Agent:** Nano Banana Pro Agent (ID: 1044)

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize to whatever you need) ---

Build a workflow that uses the Nano Banana Pro marketplace agent to solve this problem: "Analyze the pros and cons of remote-first vs hybrid work models for a 50-person startup". Set up a webhook trigger, trigger it once, and print the analysis.

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

## Brain Check: Why did it fail?

If your workflow isn't working, check these 3 things (or ask OpenClaw to check them):

1. **Was the Goal Meaningful?**
   * **Bad:** `goal: "test"`
   * **Good:** `goal: "Analyze market data for ETH and predict trends"`
     *(The LLM needs context to route tasks correctly.)*

2. **Is the Trigger Activated?**
   * Workflows start with triggers `disabled` by default.
   * **Fix:** "Please run `client.triggers.activate()` for me."

3. **Did you use `listMarketplace`?**
   * If the agent says "I can't find that agent in your owned agents", tell it: *"Use `client.agents.listMarketplace()` instead."*


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.