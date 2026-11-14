> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Chat completions

> POST /v1/chat/completions — OpenAI-format chat completions through SERV.

```
POST https://inference-api.openserv.ai/v1/chat/completions
```

OpenAI Chat Completions format. The universal endpoint — works with every model in the [catalog](https://docs.openserv.ai/serv-reasoning/models.md).

## Request

**Authorization** `string` *required*

`Bearer $SERV_API_KEY`.

**model** `string` *required*

Model ID from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md), for example `gpt-5.4-mini`.

**messages** `array` *required*

The conversation so far. Must include a system or developer message. Each entry has a `role` (`system`, `user`, `assistant`, or `tool`) and `content`.

**max\_completion\_tokens** `integer`

Maximum number of tokens to generate.

**reasoning\_effort** `string`

Reasoning depth for reasoning-capable models.

**temperature** `number`

Sampling temperature.

**tools** `array`

Function definitions, in OpenAI format: `{ type: "function", function: { name, parameters } }`.

**tool\_choice** `string | object`

`"auto"`, `"none"`, or `{ type: "function", function: { name } }`.

**stream** `boolean` (default: false)

Stream the response as server-sent events.

All other OpenAI Chat Completions parameters are accepted and forwarded to the model.

## Response

**id** `string`

Unique identifier for the completion.

**object** `string`

Always `"chat.completion"`.

**model** `string`

The model used to generate the completion.

**choices** `array`

The generated completions. `choices[0].message.content` holds the text.

**Choice object**

**index** `integer`

Position of this choice in the array.

**message** `object`

Contains `role` (`"assistant"`) and `content`.

**finish\_reason** `string`

One of `stop`, `length`, `content_filter`, or `tool_calls`.

**usage** `object`

Token counts: `prompt_tokens`, `completion_tokens`, `total_tokens`.

```bash curl theme={null}
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

```js OpenAI SDK theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const completion = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "You are a concise assistant." },
    { role: "user", content: "Hello!" },
  ],
});
```

```json theme={null}
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gpt-5.4-mini",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "Hello! How can I help?" },
      "finish_reason": "stop"
    }
  ],
  "usage": { "prompt_tokens": 18, "completion_tokens": 7, "total_tokens": 25 }
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.