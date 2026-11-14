> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Telegram Integration

> Connect your agents and workflows to Telegram. Telegram has its own trigger type — the only integration that can directly trigger workflows from messages.

# Telegram Integration

Telegram is special — it's the only integration that has its own **trigger type** (`on-message`), just like `webhook`, `x402`, `cron`, and `manual`. When someone messages your Telegram bot, it can directly trigger a workflow.

Additionally, the Telegram integration can be **attached to tasks** so agents can send messages back to the conversation.

## Prerequisites

**You must add the Telegram integration via the OpenServ UI first.**

1. Go to **[OpenServ Platform](https://platform.openserv.ai)** → **Connect** → **Integrations**.
2. Click **+ Add New Connection**.
3. Find **Telegram Bot** and click **Connect**.
4. Create a bot via [BotFather](https://t.me/BotFather) on Telegram and get the bot token.
5. Paste the bot token into OpenServ and confirm.

### Verify the Integration

After adding, verify with this prompt:

```text theme={null}
Run client.integrations.listConnections() and show me the full results. I want to confirm my telegram-bot connection is there.
```

You should see a `telegram-bot` entry with its connection `id`:

```json theme={null}
{
  "integrationName": "telegram-bot",
  "integrationDisplayName": "Telegram Bot",
  "id": "your-connection-uuid",
  "integrationType": "custom"
}
```

If you don't see it, go back to the OpenServ UI and make sure the integration was saved.

***

## How Telegram Works on OpenServ

Telegram has **two roles** in a workflow:

| Role | What It Does | How |
| :- | :- | :- |
| **Trigger** | Fires the workflow when someone messages the bot | `client.triggers.create()` with `integrationConnectionId` and `trigger_name: 'on-message'` |
| **Task Integration** | Lets the agent read/send Telegram messages | Attach the connection to a task node |

This is unique to Telegram. Other integrations (Twitter, Slack, etc.) are task-level only — they don't have their own trigger type.

***

## Example 1: Telegram → Grok Research Agent

Send a research question to your bot, get a researched answer back in the chat.

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize this part) ---

Use a Telegram trigger to listen for incoming messages. Route them to the Grok Research marketplace agent. Have the agent respond back in the Telegram chat with a researched answer.

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

## Example 2: Telegram → Nano Banana Pro (Image Generation)

Send an image description to your bot, get a generated image back in the chat.

**Copy & Paste:**

```text theme={null}
--- 📋 BUILD REQUEST (customize this part) ---

Use a Telegram trigger to listen for incoming messages. Route them to the Nano Banana Pro Agent (marketplace, id 1044) to generate an image from the message. Send the generated image back in the Telegram chat.

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

## With a Custom Agent

If you want your own agent (runless or runnable) to handle Telegram messages, the pattern is the same — just use your agent instead of a marketplace agent. Make sure the agent server is running before sending a message to the bot.

***

## Available Integration Identifiers

These integrations can be connected via the OpenServ UI and attached to tasks:

| Integration | `integrationName` | Has Trigger? |
| :- | :- | :- |
| Telegram Bot | `telegram-bot` | Yes — `on-message` |
| Twitter/X | `twitter-v2` | No |
| Slack | `slack` | No |
| YouTube | `youtube` | No |
| Google Mail | `google-mail` | No |
| Google Calendar | `google-calendar` | No |
| Google Drive | `google-drive` | No |
| Jira | `jira` | No |

***

## Debugging

**Bot not responding?**

1. Verify the integration: `client.integrations.listConnections()`.
2. Check the trigger is activated.
3. Check the BotFather token is correct.
4. Make sure the workflow is set to running.

**Paste this to OpenClaw:**

```text theme={null}
Check https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/troubleshooting.md for a fix to this error: [PASTE_ERROR_HERE]
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.