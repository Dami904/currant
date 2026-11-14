> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrate an existing integration

> Move an OpenAI or Anthropic integration to SERV Reasoning.

For an OpenAI-compatible integration, update the key and base URL:

```diff theme={null}
 const client = new OpenAI({
-  apiKey: process.env.OPENAI_API_KEY,
+  apiKey: process.env.SERV_API_KEY,
+  baseURL: "https://inference-api.openserv.ai/v1",
 });
```

Check that each SERV-enabled request includes the required system instructions, uses a model ID from the [catalog](https://docs.openserv.ai/serv-reasoning/models.md), and sets token limits high enough to avoid truncation.

For the official Anthropic SDK, use `baseURL: "https://inference-api.openserv.ai"` without `/v1` and keep the top-level `system` field.

See [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md) and [SDK Migration](https://docs.openserv.ai/serv-reasoning/sdk-migration.md) for Python, Vercel AI SDK, LangChain, and raw HTTP examples.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.