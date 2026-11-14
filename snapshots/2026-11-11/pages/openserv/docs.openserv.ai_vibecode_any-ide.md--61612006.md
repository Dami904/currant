> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Using OpenServ Skills in any IDE

> Guide for using OpenServ skills in any IDE or coding agent.

# Using OpenServ Skills in Any AI IDE (Cursor, Windsurf, GitHub Copilot)

To build with OpenServ, your AI agent needs to "read" the manual. We call these manuals **Skills**.

## Phase 1: Get the Skills

You need to give your IDE access to the `SKILL.md` files so it knows how to write code for you.

### Option A: OpenServ via ClawHub (Fastest)

If you are using **ClawHub** or the **OpenClaw** desktop app:

1. Open the **Skills Market**.
2. Click **Install** on the skills you need (e.g., `openserv-client`, `openserv-agent-sdk`).
3. The docs are automatically added to your project context.

### Option B: The "Docs" Folder (Recommended for VS Code / Cursor)

Simply download the skills into a `docs/` folder in your project.

```bash theme={null}
# Clone the skills repo into a local docs folder
git clone https://github.com/openserv-labs/skills.git docs/openserv-skills
```

Now, in your chat, you can reference them:

> "@docs/openserv-skills/openserv-client/SKILL.md how do I create a task?"

### Option C: Online References (Cursor / Windsurf)

If you don't want local files, stick to the URL references.

> "@[https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md](https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/SKILL.md) build me a workflow"

***

## Phase 2: Setup & Authentication

This guide focuses on the critical setup step that often trips developers up: **Environment Variables and Authentication**.

Because OpenServ agents can define their own infrastructure (wallets, API keys) on the fly, you don't need to manually manage complex `.env` files if you follow the **Provisioning Pattern**.

## The Golden Rule: "Provision First, ask questions later"

In any AI IDE, when you ask the AI to "build me an agent," it will often try to manage API keys for you. **Stop it.**

Instead, prompt your AI to use the **`provision()`** pattern.

### 1. The `.env` Strategy

You typically only need **ZERO** or **ONE** environment variable to start.

#### Scenario A: Fresh Start (Recommended)

You don't need *any* environment variables.

1. The AI writes code using `provision()`.
2. When you run the code (`npx tsx agent.ts`), `provision()` checks if you have a wallet.
3. If not, it **creates a new wallet** and writes the `WALLET_PRIVATE_KEY` to your `.env` file automatically.
4. It then registers your agent and writes `OPENSERV_API_KEY` to your `.env` automatically.

**Result:** Your agent works instantly. You didn't touch a single key.

#### Scenario B: "Bring Your Own Key" (BYOK)

You already have an OpenServ account or a specific wallet you want to use.

1. Create a `.env` file.
2. Add `WALLET_PRIVATE_KEY=0x...` (your private key).
3. Run your code.
4. `provision()` sees the key, logs in with it, and reuses your existing identity.

***

## 2. Prompting Your AI IDE

When asking Cursor/Windsurf/Copilot to build an agent, use a prompt like this to ensure it handles Auth correctly:

> "Build an OpenServ agent that \[does X]. Use the `openserv-client` `provision()` method to handle authentication and registration. Do NOT assume I have an API key; let `provision()` create the wallet and keys for me if they don't exist. Use Runless Capabilities where possible for the agent logic."

## 3. How `provision()` handles logic

The `provision()` function is your best friend. It is **idempotent**, meaning you can run it 1000 times and it won't break anything.

```typescript theme={null}
// The "Magic" Setup
import { provision } from '@openserv-labs/client'

await provision({
  agent: {
    instance: agent, // 👈 PASS THE AGENT INSTANCE HERE!
    name: 'my-agent'
  },
  // ...
})
```

**Why pass `instance: agent`?**
When you do this, `provision()` automatically injects the generated API key and Auth Token directly into your `agent` object.

* **Old Way:** `agent` needed `process.env.OPENSERV_API_KEY`.
* **New Way:** `agent` gets the key from `provision()`. Your code doesn't even need to read `process.env`.

## 4. Troubleshooting Env Vars

**Issue:** "Error: Missing API Key"
**Fix:** You probably didn't pass `instance: agent` to provision.

* *Bad:* `const agent = new Agent(); await provision({...}); await run(agent);`
* *Good:* `const agent = new Agent(); await provision({ agent: { instance: agent, ... } }); await run(agent);`

**Issue:** "Error: 401 Unauthorized"
**Fix:** You might have a stale `.env`. Delete the `OPENSERV_API_KEY` line from your `.env` and run the script again. `provision()` will fetch a fresh valid key for your wallet.

## 5. Finding All Methods (The "Missing Link")

The `SKILL.md` file is just a summary and quick start. **It does NOT contain every method.**

If your AI keeps hallucinating methods or you need to know exactly what parameters `client.agents.create()` accepts, you **MUST** read the `reference.md` file in each skill.

**Prompting Tip:**

> "Please read `https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md` to see the full list of available methods before generating code."

**Key Reference Files:**

* [openserv-agent-sdk Reference](https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/reference.md)
* [openserv-client Reference](https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/reference.md)
* [openserv-launch Reference](https://github.com/openserv-labs/skills/blob/main/skills/openserv-launch/reference.md)
* [openserv-ideaboard-api Reference](https://github.com/openserv-labs/skills/blob/main/skills/openserv-ideaboard-api/reference.md)
* [openserv-multi-agent-workflows Reference](https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/reference.md)

## 6. How to Fix Common Errors

If you encounter cryptic errors (like 400 Bad Request on provision, or 500 on triggering), **DO NOT guess the solution.**

Each skill has a dedicated `troubleshooting.md` file that lists common errors and their exact fixes.

**Prompting Tip:**

> "I am getting error \[ERROR\_MESSAGE]. Please check `https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/troubleshooting.md` (or the relevant skill) to find the solution."

**Key Troubleshooting Files:**

* [openserv-agent-sdk Troubleshooting](https://github.com/openserv-labs/skills/blob/main/skills/openserv-agent-sdk/troubleshooting.md)
* [openserv-client Troubleshooting](https://github.com/openserv-labs/skills/blob/main/skills/openserv-client/troubleshooting.md)
* [openserv-launch Troubleshooting](https://github.com/openserv-labs/skills/blob/main/skills/openserv-launch/troubleshooting.md)
* [openserv-ideaboard-api Troubleshooting](https://github.com/openserv-labs/skills/blob/main/skills/openserv-ideaboard-api/troubleshooting.md)
* [openserv-multi-agent-workflows Troubleshooting](https://github.com/openserv-labs/skills/blob/main/skills/openserv-multi-agent-workflows/troubleshooting.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.