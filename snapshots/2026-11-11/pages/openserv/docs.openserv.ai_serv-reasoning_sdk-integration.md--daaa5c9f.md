> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# SDK Integration

> Endpoints and parameter mappings for the OpenAI and Anthropic SDKs.

This is the reference for integrating the OpenAI and Anthropic SDKs with SERV. For a five-minute setup, start with the [Quickstart](https://docs.openserv.ai/serv-reasoning/introduction.md).

SERV exposes three HTTP endpoints under one base URL: `https://inference-api.openserv.ai`

| Endpoint | Shape | Use it for |
| - | - | - |
| `POST /v1/chat/completions` | OpenAI | Universal. Works with every model in the catalog. |
| `POST /v1/responses` | OpenAI | OpenAI models, with streamed reasoning summaries. |
| `POST /v1/messages` | Anthropic | Claude and most other providers. See [endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md). |

## OpenAI SDK

### Chat completions

```js theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const completion = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "You are a concise assistant." },
    { role: "user", content: "What is a CPU register?" },
  ],
});

console.log(completion.choices[0].message.content);
```

### Responses

Use the Responses API to receive the reasoning trace alongside the answer. OpenAI models only.

```js theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const response = await client.responses.create({
  model: "gpt-5.4",
  instructions: "You are a careful reasoner.",
  input: "What is the integral of x^2 from 0 to 3?",
});

console.log(response.output_text);
```

## Anthropic SDK

### Messages

```js theme={null}
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic({
  baseURL: "https://inference-api.openserv.ai",
  authToken: process.env.SERV_API_KEY,
});

const message = await client.messages.create({
  model: "claude-haiku-4.5",
  max_tokens: 1024,
  system: "You answer in one sentence.",
  messages: [{ role: "user", content: "What is a CPU register?" }],
});

console.log(message.content.find(b => b.type === "text").text);
```

## Important details

### Base URL differs by SDK

| SDK | Base URL | Why |
| - | - | - |
| OpenAI SDK | `https://inference-api.openserv.ai/v1` | The OpenAI SDK expects `/v1` in the base URL. |
| Anthropic SDK | `https://inference-api.openserv.ai` | The Anthropic SDK appends `/v1/messages` itself. Including `/v1` yourself would call `/v1/v1/messages`, which fails. |

### Auth field differs by SDK

| SDK | Field | Notes |
| - | - | - |
| OpenAI SDK | `apiKey` | Standard. |
| Anthropic SDK | `authToken` | `apiKey` also works, but `authToken` keeps `ANTHROPIC_API_KEY` free if you ever fall back to direct Anthropic. |

### A system prompt is required

Every request needs a system, developer, or instructions message. Requests without one are rejected:

```
A system prompt is required. Please include a system or developer message in your request.
```

Where the system prompt goes depends on the endpoint:

| Endpoint | Where the system prompt goes |
| - | - |
| `/v1/chat/completions` | a `{ role: "system", content: "..." }` message |
| `/v1/responses` | top-level `instructions` |
| `/v1/messages` | top-level `system` |

## Parameter map

Moving an integration across SDKs comes down to this mapping.

| Concept | OpenAI Chat | OpenAI Responses | Anthropic Messages |
| - | - | - | - |
| HTTP path | `/v1/chat/completions` | `/v1/responses` | `/v1/messages` |
| Auth field (SDK constructor) | `apiKey` | `apiKey` | `authToken` |
| `baseURL` suffix to use with SERV | `/v1` | `/v1` | *(none)* |
| Token cap field | `max_completion_tokens` | `max_output_tokens` | `max_tokens` *(required)* |
| System prompt | message with `role:"system"` | top-level `instructions` | top-level `system` |
| User message shape | `{role, content}` in `messages[]` | top-level `input` (string or array) | `{role, content}` in `messages[]` |
| Reasoning-effort control | `reasoning_effort` | `reasoning: { effort, summary }` | `thinking: { type:"enabled", budget_tokens }` |
| Streaming | `stream: true` | `stream: true` | `stream: true` |
| Stop sequences | `stop` | n/a | `stop_sequences` |
| Tool schema | `tools: [{type:"function", function:{name, parameters}}]` | `tools: [{type:"function", ...}]` | `tools: [{name, input_schema}]` *(no nested `function:`)* |
| Tool choice | `tool_choice: "auto" \| {type:"function", function:{name}}` | `tool_choice: ...` | `tool_choice: "auto" \| "any" \| {type:"tool", name}` |
| Response text | `choices[0].message.content` | `output_text` or `output[]` blocks | `content[]` array, find the `type === "text"` block |
| Token usage | `usage.prompt_tokens / completion_tokens / total_tokens` | `usage.input_tokens / output_tokens / total_tokens` | `usage.input_tokens / output_tokens` |
| Cache metrics | `usage.prompt_tokens_details.cached_tokens` | `usage.input_tokens_details.cached_tokens` | `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens` |

## See also

* [SERV Tools](https://docs.openserv.ai/serv-reasoning/tools.md) — enable the prompt-injection guard and shadow agents via tool definitions.
* [Endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md) — which models work on which endpoint.
* [Quickstart](https://docs.openserv.ai/serv-reasoning/introduction.md) — the five-minute setup.
* [SDK Migration](https://docs.openserv.ai/serv-reasoning/sdk-migration.md) — Python, Vercel AI SDK, LangChain, and raw `fetch`.
* [Models](https://docs.openserv.ai/serv-reasoning/models.md) — pricing and context windows.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.