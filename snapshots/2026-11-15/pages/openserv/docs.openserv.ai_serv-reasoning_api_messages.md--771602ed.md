> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Messages

> POST /v1/messages — Anthropic Messages format through SERV.

```
POST https://inference-api.openserv.ai/v1/messages
```

Anthropic Messages format. Accepts Claude and most other models in the [catalog](https://docs.openserv.ai/serv-reasoning/models.md) — see [endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md).

## Request

**Authorization** `string` *required*

`Bearer $SERV_API_KEY`.

**model** `string` *required*

Model ID from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md), for example `claude-haiku-4.5`.

**max\_tokens** `integer` *required*

Maximum number of tokens to generate. Required by the Messages format.

**system** `string` *required*

The system prompt. SERV requires one.

**messages** `array` *required*

The conversation so far. Each entry has a `role` (`user` or `assistant`) and `content`.

**thinking** `object`

Extended thinking controls, for example `{ "type": "enabled", "budget_tokens": 1024 }`.

**tools** `array`

Tool definitions, in Anthropic format: `{ name, input_schema }`.

**tool\_choice** `string | object`

`"auto"`, `"any"`, or `{ "type": "tool", "name": "..." }`.

**stop\_sequences** `array`

Sequences that stop generation.

**stream** `boolean` (default: false)

Stream the response as server-sent events.

All other Anthropic Messages parameters are accepted and forwarded to the model.

## Response

**id** `string`

Unique identifier for the message.

**type** `string`

Always `"message"`.

**role** `string`

Always `"assistant"`.

**model** `string`

The model used.

**content** `array`

Output blocks. Find the block with `type: "text"` for the generated text.

**stop\_reason** `string`

Why generation ended. Common values: `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`.

**usage** `object`

Token counts: `input_tokens`, `output_tokens`.

```bash curl theme={null}
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
```

```json theme={null}
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "model": "claude-haiku-4.5",
  "content": [{ "type": "text", "text": "Hello! How can I help?" }],
  "stop_reason": "end_turn",
  "usage": { "input_tokens": 16, "output_tokens": 7 }
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.