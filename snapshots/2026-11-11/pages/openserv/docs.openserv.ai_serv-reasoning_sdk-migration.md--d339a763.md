> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# SDK Migration

> Migrate Python, the Vercel AI SDK, LangChain, and other clients to SERV.

If you are using the official OpenAI or Anthropic Node SDKs, see [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md) — the integration is a two-field change.

SERV accepts the OpenAI and Anthropic HTTP API formats, so any client built for either one works. That includes:

* **Python**: `openai`, `anthropic`
* **Vercel AI SDK**: `@ai-sdk/openai`, `@ai-sdk/anthropic`
* **LangChain**: `langchain-openai`, `langchain-anthropic` (Python or JS)
* **LlamaIndex**: the OpenAI and Anthropic LLM classes
* **Mastra**, **AutoGen**, **CrewAI**, **Instructor**, **LiteLLM**, and similar
* Raw `fetch`, `curl`, or any HTTP client

> [!NOTE]
>
> We run integration tests against the official `openai` and `anthropic` SDKs (Node and Python), `@ai-sdk/openai`, `@ai-sdk/anthropic`, and LangChain. The other tools work through the same API formats, but are documented patterns rather than tested paths.

## What changes

| | OpenAI-shape SDK | Anthropic-shape SDK |
| - | - | - |
| Base URL | `https://inference-api.openserv.ai/v1` *(with `/v1`)* | `https://inference-api.openserv.ai` *(no `/v1`)* |
| Auth | `Authorization: Bearer <SERV_API_KEY>` — constructor field is usually `apiKey` | `Authorization: Bearer <SERV_API_KEY>` — constructor field is usually `authToken` |
| Model ID | Any model from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md). Names like `gpt-5.4-mini` and `claude-haiku-4.5` work as-is | Most of the catalog routes here too — see [endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md) |

Every request also needs a **system prompt** — SERV rejects requests without one. Nothing else changes: prompts, tool definitions, streaming, and business logic stay the same. For the full field mapping, see the [parameter map](https://docs.openserv.ai/serv-reasoning/sdk-integration.md#parameter-map).

> [!NOTE]
>
> **The `google-genai` SDK is not supported.** It speaks Gemini's native `generateContent` format, not the OpenAI or Anthropic API. To use Gemini or Gemma, switch to the OpenAI SDK and call `/v1/chat/completions`.

## Python

### `openai`

```python theme={null}
from openai import OpenAI
import os

client = OpenAI(
    base_url="https://inference-api.openserv.ai/v1",
    api_key=os.environ["SERV_API_KEY"],
)

resp = client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "What is a CPU register?"},
    ],
)
print(resp.choices[0].message.content)
```

### `anthropic`

```python theme={null}
from anthropic import Anthropic
import os

client = Anthropic(
    base_url="https://inference-api.openserv.ai",
    auth_token=os.environ["SERV_API_KEY"],
)

message = client.messages.create(
    model="claude-haiku-4.5",
    max_tokens=1024,
    system="You answer in one sentence.",
    messages=[{"role": "user", "content": "What is a CPU register?"}],
)
print(message.content[0].text)
```

## Vercel AI SDK

The AI SDK exposes per-provider factories that accept custom base URLs.

### `@ai-sdk/openai`

```ts theme={null}
import { createOpenAI } from "@ai-sdk/openai";
import { generateText } from "ai";

const serv = createOpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY!,
});

const { text } = await generateText({
  model: serv("gpt-5.4-mini"),
  system: "You are a concise assistant.",
  prompt: "What is a CPU register?",
});
```

### `@ai-sdk/anthropic`

```ts theme={null}
import { createAnthropic } from "@ai-sdk/anthropic";
import { generateText } from "ai";

const serv = createAnthropic({
  baseURL: "https://inference-api.openserv.ai/v1",
  authToken: process.env.SERV_API_KEY!,
});

const { text } = await generateText({
  model: serv("claude-haiku-4.5"),
  system: "You answer in one sentence.",
  prompt: "What is a CPU register?",
});
```

> [!NOTE]
>
> Unlike the official Anthropic Node SDK, `@ai-sdk/anthropic` requires the `/v1` suffix in the `baseURL`. The "no `/v1`" rule only applies to the official `@anthropic-ai/sdk` package.

## LangChain (JS)

### `ChatOpenAI`

```ts theme={null}
import { ChatOpenAI } from "@langchain/openai";

const llm = new ChatOpenAI({
  apiKey: process.env.SERV_API_KEY,
  model: "gpt-5.4-mini",
  configuration: { baseURL: "https://inference-api.openserv.ai/v1" },
});

const res = await llm.invoke([
  { role: "system", content: "You are a concise assistant." },
  { role: "user", content: "What is a CPU register?" },
]);
```

### `ChatAnthropic`

```ts theme={null}
import { ChatAnthropic } from "@langchain/anthropic";

const llm = new ChatAnthropic({
  model: "claude-haiku-4.5",
  clientOptions: {
    baseURL: "https://inference-api.openserv.ai",
    authToken: process.env.SERV_API_KEY,
  },
});
```

## LangChain (Python)

### `ChatOpenAI`

```python theme={null}
from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    model="gpt-5.4-mini",
    api_key=os.environ["SERV_API_KEY"],
    base_url="https://inference-api.openserv.ai/v1",
)
```

### `ChatAnthropic`

```python theme={null}
from langchain_anthropic import ChatAnthropic
import os

llm = ChatAnthropic(
    model="claude-haiku-4.5",
    client_options={
        "base_url": "https://inference-api.openserv.ai",
        "auth_token": os.environ["SERV_API_KEY"],
    }
)
```

## Raw `fetch` and `curl`

With no SDK, the wire format is plain JSON.

### OpenAI shape

```bash theme={null}
curl https://inference-api.openserv.ai/v1/chat/completions \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4-mini",
    "messages": [
      {"role": "system", "content": "You are concise."},
      {"role": "user",   "content": "What is a CPU register?"}
    ]
  }'
```

### Anthropic shape

```bash theme={null}
curl https://inference-api.openserv.ai/v1/messages \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-haiku-4.5",
    "max_tokens": 1024,
    "system": "You answer in one sentence.",
    "messages": [{"role": "user", "content": "What is a CPU register?"}]
  }'
```

## Migration prompt for AI coding tools

To migrate an existing integration with Claude Code, Cursor, Copilot, or another coding agent, paste this into the chat:

```text theme={null}
Migrate this codebase from <CURRENT_PROVIDER> to SERV. SERV accepts the OpenAI Chat
Completions API and the Anthropic Messages API formats. The migration is a per-call-site
change:

1. Base URL:
   • OpenAI-shape client (openai / @ai-sdk/openai / ChatOpenAI / etc.)
     -> "https://inference-api.openserv.ai/v1"
   • Anthropic-shape client (anthropic / @anthropic-ai/sdk)
     -> "https://inference-api.openserv.ai"  (NO /v1 suffix, the SDK adds it)

2. API key:
   • Read from SERV_API_KEY.
   • For @anthropic-ai/sdk specifically, use the `authToken` constructor field, not `apiKey`.

3. Model ID: keep existing model IDs if they match the SERV catalog:
   • OpenAI-shape:    gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.4-nano,
                      o3, o3-mini, o3-pro, o4-mini,
                      gemini-flash-latest, gemini-pro-latest,
                      gemma-4-26b-a4b-it, gemma-4-31b-it   (Gemma needs the -it suffix)
                      grok-4.3, grok-4.20,
                      qwen3.6-flash, qwen3.6-max-preview,
                      deepseek-v4-pro, deepseek-v4-flash
   • Anthropic-shape: claude-haiku-4.5, claude-sonnet-4.6, claude-opus-4.6

   If the codebase uses an ID not in the catalog, flag it for me to pick a replacement.

4. SERV requires a system prompt. Audit every call site. If any request lacks a
   system / instructions / developer message, add one ("You are a helpful assistant."
   is a fine default). Requests without one are rejected.

If the codebase uses the google-genai SDK for Gemini, replace it with the openai SDK
pointed at /v1/chat/completions.

Leave all other parameters (messages, tool definitions, response handling, streaming,
temperature, etc.) untouched.
```

## Troubleshooting

| Symptom | Cause | Fix |
| - | - | - |
| `400 A system prompt is required` | Missing system / instructions / developer message | Add one. SERV requires it on every request. |
| `400 The Responses API is not supported with model X` | `/v1/responses` is OpenAI-only | Use `/v1/chat/completions` for Claude, Gemini, Gemma, Grok, Qwen, and DeepSeek. |
| `404` on the Anthropic Node SDK | Included `/v1` in `baseURL` | Drop the `/v1` — the official Anthropic SDK adds it. |
| `404` on a raw `fetch` to `/messages` | Missing `/v1` in the path | Use `/v1/messages`. |
| `404 The model 'gemma-...' does not exist` | Gemma IDs need the `-it` suffix the Playground display drops | Use `gemma-4-31b-it` / `gemma-4-26b-a4b-it`. |
| `401` on the Anthropic SDK | Ambient `ANTHROPIC_API_KEY` conflicts with the SERV key | Pass `authToken: SERV_API_KEY` explicitly. |
| `502` on Gemini via `/v1/messages` | Gemini doesn't route through the Anthropic-shape endpoint | Use `/v1/chat/completions` for Gemini. |
| Empty `content` on a reasoning model | Reasoning exhausted the token cap | Raise `max_completion_tokens` / `max_tokens`. |
| Model rejected as unsupported | The ID isn't in the catalog | Use an ID from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md). |

## See also

* [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md) — endpoints and the parameter map.
* [Endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md) — which models work on which endpoint.
* [Models](https://docs.openserv.ai/serv-reasoning/models.md) — pricing and context windows.
* [Playground](https://console.openserv.ai/playground) — compare models before you migrate.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.