> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenClaw

> An OS gateway for AI agents across messaging platforms.

# OpenClaw

**An OS gateway for AI agents across WhatsApp, Telegram, Discord, iMessage, and more.**
Send a message, get an agent response from your pocket. Plugins add Mattermost and more.

## Get Started

First, get OpenClaw running.
[Official Installation Docs](https://docs.openclaw.ai/install)

**Quickest way (Linux VPS / VM):**

```bash theme={null}
curl -fsSL https://openclaw.ai/install.sh | bash
```

**Once OpenClaw is set up and working:**
[Go to the Quickstart](https://docs.openserv.ai/vibecode/openclaw/quickstart.md) to build your first agent with OpenServ skills.

## What is OpenClaw?

OpenClaw is a self-hosted gateway that connects your favorite chat apps — WhatsApp, Telegram, Discord, iMessage, and more — to AI coding agents like Pi. You run a single Gateway process on your own machine (or a server), and it becomes the bridge between your messaging apps and an always-available AI assistant.

**Who is it for?** Developers and power users who want a personal AI assistant they can message from anywhere — without giving up control of their data or relying on a hosted service.

### What makes it different?

* **Self-hosted**: runs on your hardware, your rules
* **Multi-channel**: one Gateway serves WhatsApp, Telegram, Discord, and more simultaneously
* **Agent-native**: built for coding agents with tool use, sessions, memory, and multi-agent routing
* **Open source**: MIT licensed, community-driven

**What do you need?** Node 22+, an API key (Anthropic recommended), and 5 minutes.

***

## How it works

The Gateway is the single source of truth for sessions, routing, and channel connections.

1. **Chat apps + plugins**: Users message via WhatsApp, Telegram, etc.
2. **Gateway**: Receives message, handles routing and session management.
3. **Pi agent**: Processes the request and generates a response.
4. **Web Control UI**: Browser dashboard for chat, config, and sessions.

### Key capabilities

* **Multi-channel gateway**: WhatsApp, Telegram, Discord, and iMessage with a single Gateway process.
* **Plugin channels**: Add Mattermost and more with extension packages.
* **Multi-agent routing**: Isolated sessions per agent, workspace, or sender.
* **Media support**: Send and receive images, audio, and documents.
* **Web Control UI**: Browser dashboard for chat, config, sessions, and nodes.
* **Mobile nodes**: Pair iOS and Android nodes with Canvas support.

***

## Ready to build?

[Once your gateway is running, go to the Quickstart Guide](https://docs.openserv.ai/vibecode/openclaw/quickstart.md) to build your first agent workflow.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.