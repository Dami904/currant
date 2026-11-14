> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Responses

> POST /v1/responses — OpenAI Responses format, with streamed reasoning summaries.

```
POST https://inference-api.openserv.ai/v1/responses
```

OpenAI Responses format. Use it to receive the reasoning trace alongside the answer. **OpenAI models only** — other models are not supported on this endpoint. Use [chat completions](https://docs.openserv.ai/serv-reasoning/api/chat-completions.md) for everything else.

## Request

**Authorization** `string` *required*

`Bearer $SERV_API_KEY`.

**model** `string` *required*

An OpenAI model ID from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md), for example `gpt-5.4`.

**input** `string | array` *required*

The prompt — a string, or an array of input items.

**instructions** `string` *required*

The system prompt. SERV requires one.

**reasoning** `object`

Reasoning controls, for example `{ "effort": "medium", "summary": "auto" }`.

**max\_output\_tokens** `integer`

Maximum number of tokens to generate.

**tools** `array`

Function definitions, in OpenAI format.

**stream** `boolean` (default: false)

Stream the response as server-sent events.

All other OpenAI Responses parameters are accepted and forwarded to the model.

## Response

**id** `string`

Unique identifier for the response.

**object** `string`

Always `"response"`.

**model** `string`

The model used.

**output\_text** `string`

Convenience field with the generated text.

**output** `array`

The full output items, including reasoning items when reasoning is enabled.

**usage** `object`

Token counts: `input_tokens`, `output_tokens`, `total_tokens`.

```bash curl theme={null}
curl https://inference-api.openserv.ai/v1/responses \
  -H "Authorization: Bearer $SERV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4",
    "instructions": "You are a careful reasoner.",
    "input": "Hello!"
  }'
```

```js OpenAI SDK theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const response = await client.responses.create({
  model: "gpt-5.4",
  instructions: "You are a careful reasoner.",
  input: "Hello!",
});
```

```json theme={null}
{
  "id": "resp_...",
  "object": "response",
  "model": "gpt-5.4",
  "output_text": "Hello! How can I help?",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [{ "type": "output_text", "text": "Hello! How can I help?" }]
    }
  ],
  "usage": { "input_tokens": 16, "output_tokens": 7, "total_tokens": 23 }
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.