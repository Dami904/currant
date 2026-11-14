> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Choose an API endpoint

> Select the endpoint that matches your client and model.

| If you need | Use |
| - | - |
| One endpoint for any catalog model | [`/v1/chat/completions`](../api/chat-completions) |
| OpenAI Responses format or reasoning summaries | [`/v1/responses`](../api/responses) |
| An Anthropic SDK or Messages-shaped integration | [`/v1/messages`](../api/messages) |

`/v1/responses` supports OpenAI-routed models only. For Gemini, Claude, Gemma, Grok, Qwen, or DeepSeek, use Chat Completions unless the [compatibility matrix](https://docs.openserv.ai/serv-reasoning/api/compatibility.md) says otherwise.

The endpoint changes the request and response shape, not the SERV reasoning concept. Use the [parameter map](https://docs.openserv.ai/serv-reasoning/sdk-integration.md#parameter-map) when translating system prompts, token limits, reasoning controls, tools, and usage fields between formats.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.