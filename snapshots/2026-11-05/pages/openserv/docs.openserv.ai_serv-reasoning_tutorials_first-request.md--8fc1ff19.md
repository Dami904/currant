> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Make your first API request

> Send your first SERV Reasoning request with the OpenAI SDK.

Install the OpenAI SDK:

```bash theme={null}
npm install openai
```

Create a server-side file such as `example.mjs`. Read the API key from an environment variable. Do not expose it in browser JavaScript.

```js theme={null}
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://inference-api.openserv.ai/v1",
  apiKey: process.env.SERV_API_KEY,
});

const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  reasoning_effort: "low",
  messages: [
    { role: "system", content: "You classify support requests." },
    { role: "user", content: "I was charged twice for the same order." },
  ],
});

console.log(response.choices[0].message.content);
```

SERV-enabled Chat Completions requests require a system or developer message. The Responses API also accepts an `instructions` field. Check the [model catalog](https://docs.openserv.ai/serv-reasoning/models.md) for supported model IDs and reasoning support.

The SDK returns the standard Chat Completions shape. Read the generated text from `choices[0].message.content` and usage data from `response.usage`.

If the request fails, check the API key, organization balance, model ID, and system prompt first. For endpoint-specific fields, see the [Chat Completions reference](https://docs.openserv.ai/serv-reasoning/api/chat-completions.md).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.