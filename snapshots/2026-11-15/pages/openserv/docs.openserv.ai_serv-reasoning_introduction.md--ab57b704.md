> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> Make your first SERV Reasoning request with the OpenAI SDK, the Anthropic SDK, or raw HTTP.

Point your existing OpenAI or Anthropic SDK at SERV and use your `SERV_API_KEY` — your prompts, tool definitions, and application logic stay the same. Or call the endpoints directly over HTTP. Generate a key at [console.openserv.ai](https://console.openserv.ai).

## Make your first request

```js OpenAI SDK theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "You are a concise assistant." },
    { role: "user", content: "Hello!" },
  ],
});

console.log(response.choices[0].message.content);
```

```js Anthropic SDK theme={null}
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic({
  baseURL: "https://inference-api.openserv.ai",
  authToken: process.env.SERV_API_KEY,
});

const message = await client.messages.create({
  model: "claude-haiku-4.5",
  max_tokens: 1024,
  system: "You answer in one sentence.",
  messages: [{ role: "user", content: "Hello!" }],
});

console.log(message.content[0].text);
```

That completes the integration. For Python, the Vercel AI SDK, LangChain, and other clients, see [SDK Migration](https://docs.openserv.ai/serv-reasoning/sdk-migration.md).

## Call the endpoints directly

For raw HTTP, SERV exposes three endpoints under `https://inference-api.openserv.ai`.

```bash /v1/chat/completions theme={null}
curl https://inference-api.openserv.ai/v1/chat/completions \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4-mini",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

```bash /v1/responses theme={null}
curl https://inference-api.openserv.ai/v1/responses \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4",
    "instructions": "You are a careful reasoner.",
    "input": "Hello!"
  }'
```

```bash /v1/messages theme={null}
curl https://inference-api.openserv.ai/v1/messages \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-haiku-4.5",
    "max_tokens": 1024,
    "system": "You answer in one sentence.",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Things to know

A few SERV-specific behaviors are worth knowing before your first integration. Full detail is in [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md).

* **A system prompt is required.** Every request needs a `system` message, `instructions` field, or developer message. Requests without one are rejected.
* **The base URL differs by SDK.** The OpenAI SDK takes `/v1` in the base URL; the Anthropic SDK does not — it appends `/v1/messages` itself.
* **The auth field differs by SDK.** OpenAI uses `apiKey`; the Anthropic SDK uses `authToken`.

## Try it in the Playground

Compare any model with and without SERV Reasoning side by side on the same prompt before you commit to an integration.

→ [console.openserv.ai/playground](https://console.openserv.ai/playground)

## Next steps

```text theme={null}
I'm migrating my project from [OpenAI / Anthropic / other provider] to SERV Reasoning.
SERV is wire-compatible with the OpenAI Chat Completions API and the Anthropic
Messages API. Please refactor as follows:

1. Set the client baseURL:
   • OpenAI-shape clients   -> "https://inference-api.openserv.ai/v1"  (WITH /v1)
   • Anthropic-shape client -> "https://inference-api.openserv.ai"    (WITHOUT /v1)

2. Read the API key from SERV_API_KEY.
   • OpenAI SDK: use the `apiKey` constructor field.
   • Anthropic SDK: use the `authToken` constructor field, not `apiKey`.

3. Leave model IDs as-is if they are already SERV-supported. The current public
   catalog is:
     OpenAI-shape: gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.4-nano,
                   o3, o3-mini, o3-pro, o4-mini,
                   gemini-flash-latest, gemini-pro-latest,
                   gemma-4-26b-a4b, gemma-4-31b,
                   grok-4.3, grok-4.20,
                   qwen3.6-flash, qwen3.6-max-preview,
                   deepseek-v4-pro, deepseek-v4-flash
     Anthropic-shape: claude-opus-4.6, claude-sonnet-4.6, claude-haiku-4.5
   If you encounter a non-supported ID, flag it for me to pick a replacement.

4. SERV requires a system prompt on every request. Audit every call site. If any
   request lacks a system message / instructions / developer message, add a
   default ("You are a helpful assistant." is fine) and flag it for me to refine.

5. If any code passes `reasoning_effort: "minimal"`, change to `"low"`. SERV's
   allowed values are: none | low | medium | high.

6. Leave all prompts, tool/function definitions, message structures, streaming
   logic, and business logic UNCHANGED.

Produce a diff for every call site, and flag any provider-specific features
(prompt caching, assistants API, etc.) for manual review.
```

> [card] [Models](https://docs.openserv.ai/serv-reasoning/models.md)
>
> The full model catalog with pricing and context windows.

> [card] [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md)
>
> Endpoint details and the parameter map.

> [card] [SDK Migration](https://docs.openserv.ai/serv-reasoning/sdk-migration.md)
>
> Migrate Python, Vercel AI SDK, LangChain, and raw `fetch` clients.

> [card] [Why SERV Reasoning](https://docs.openserv.ai/serv-reasoning/why.md)
>
> What you get over calling model APIs directly.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.