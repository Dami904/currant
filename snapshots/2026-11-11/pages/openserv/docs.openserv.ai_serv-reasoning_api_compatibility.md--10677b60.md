> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Endpoint compatibility

> Which models work on which SERV endpoint.

SERV exposes three endpoints: `/v1/chat/completions`, `/v1/responses`, and `/v1/messages`. Each supports a different subset of providers.

| Provider | `/v1/chat/completions` | `/v1/responses` | `/v1/messages` |
| - | :-: | :-: | :-: |
| OpenAI | ✅ | ✅ | ✅ |
| Anthropic | ✅ | ❌ | ✅ |
| Google (Gemini) | ✅ | ❌ | ⚠️ *(not available)* |
| Google (Gemma) | ✅ | ❌ | ✅ |
| xAI | ✅ | ❌ | ✅ |
| Qwen | ✅ | ❌ | ✅ |
| DeepSeek | ✅ | ❌ | ✅ |

## Endpoint behaviors

1. **`/v1/chat/completions` is universal.** It supports every provider in the catalog, including Claude. A single code path through the OpenAI SDK is sufficient for all models.
2. **`/v1/responses` is OpenAI-only.** Non-OpenAI models are not supported on this endpoint and should use `/v1/chat/completions`.
3. **`/v1/messages` is multi-provider.** It accepts OpenAI, Anthropic, xAI, Qwen, DeepSeek, and Gemma models. Existing Anthropic-SDK integrations can switch providers by changing the model ID alone.

## Google models

* **Gemini is not available on `/v1/messages`.** Use `/v1/chat/completions` for Gemini. Gemma is supported on both endpoints.
* **The `google-genai` SDK is not supported.** It uses Gemini's `generateContent` format, which SERV does not expose. Use the OpenAI SDK against `/v1/chat/completions` for any Gemini or Gemma model.

## See also

* [Models](https://docs.openserv.ai/serv-reasoning/models.md) — the full catalog with pricing and context windows.
* [SDK Integration](https://docs.openserv.ai/serv-reasoning/sdk-integration.md) — endpoints and the parameter map.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.