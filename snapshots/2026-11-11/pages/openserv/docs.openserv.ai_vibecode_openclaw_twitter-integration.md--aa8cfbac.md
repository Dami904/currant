> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Twitter/X Integration

> Connect your agents and workflows to Twitter/X. Attach your twitter-v2 connection to tasks so agents can post tweets, read mentions, and interact on your behalf.

# Twitter/X Integration

Twitter is a **task-level integration** — you attach your `twitter-v2` connection to a task node so the agent can post tweets, read mentions, and interact with your Twitter account. Unlike Telegram, Twitter does not have its own trigger type. Use a webhook, cron, or Telegram trigger to fire the workflow, then the agent uses Twitter via the attached integration.

## Prerequisites

**You must add the Twitter integration via the OpenServ UI first.**

1. Go to **[OpenServ Platform](https://platform.openserv.ai)** → **Connect** → **Integrations**.
2. Click **+ Add New Connection**.
3. Find **Twitter/X** and click **Connect**.
4. Authorize your Twitter account via OAuth (you'll be redirected to Twitter to grant access).
5. Once connected, return to OpenServ and confirm.

### Verify the Integration

After adding, verify with this prompt:

```text theme={null}
Run client.integrations.listConnections() and show me the full results. I want to confirm my twitter-v2 connection is there.
```

You should see a `twitter-v2` entry with its connection `id`:

```json theme={null}
{
  "integrationName": "twitter-v2",
  "integrationDisplayName": "Twitter/X",
  "id": "your-connection-uuid",
  "integrationType": "custom"
}
```

If you don't see it, go back to the OpenServ UI and make sure the integration was saved.

***

## How Twitter Works on OpenServ

Twitter is a **task-level only** integration. It does not have its own trigger type.

| What You Want | How |
| :- | :- |
| Agent posts tweets | Attach `twitter-v2` connection to the task |
| Agent reads mentions | Attach `twitter-v2` connection to the task |
| Trigger workflow from a tweet | Not available — use a webhook, cron, or Telegram trigger instead |

***

## Example: Webhook → AI Writer → Tweet

A webhook fires, a marketplace agent writes copy, and posts it to Twitter.

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize this part) ---

Use a webhook trigger. Route the incoming topic to a marketplace agent that writes a short, engaging tweet about it. Post the tweet to my Twitter account using my twitter-v2 integration.

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

## Example: Custom Agent → Tweet

Use your own runnable agent to generate content and post to Twitter.

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize this part) ---

Build a runnable agent called "Tweet Writer" that takes a topic, uses this.generate() to write an engaging tweet, and posts it to my Twitter account via my twitter-v2 integration.

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

## Combining with Telegram

The most powerful pattern — Telegram triggers the workflow, the agent processes the message, and posts to Twitter. See the [Telegram Integration](https://docs.openserv.ai/vibecode/openclaw/telegram-integration.md) guide for examples.

***

## Available Integration Identifiers

These integrations can be connected via the OpenServ UI and attached to tasks:

| Integration | `integrationName` | Has Trigger? |
| :- | :- | :- |
| Twitter/X | `twitter-v2` | No |
| Telegram Bot | `telegram-bot` | Yes — `on-message` |
| Slack | `slack` | No |
| YouTube | `youtube` | No |
| Google Mail | `google-mail` | No |
| Google Calendar | `google-calendar` | No |
| Google Drive | `google-drive` | No |
| Jira | `jira` | No |

***

## Debugging

**Tweet not posting?**

1. Verify the integration: `client.integrations.listConnections()` — confirm `twitter-v2` is listed.
2. Check the connection is attached to the task: refetch the task and look at `integrationConnections`.
3. Confirm your Twitter account was authorized correctly on the OpenServ UI.
4. Make sure the workflow is set to running.

**Paste this to OpenClaw:**

```text theme={null}
Check https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/troubleshooting.md for a fix to this error: [PASTE_ERROR_HERE]
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.