> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Overview

> Base URL, authentication, endpoints, and errors for the SERV Reasoning API.

The SERV Reasoning API is a REST API at `https://inference-api.openserv.ai`. It implements the OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages formats, so existing clients work with a base URL and key change. To get running, start with the [Quickstart](https://docs.openserv.ai/serv-reasoning/introduction.md).

## Authentication

Generate an API key at [console.openserv.ai](https://console.openserv.ai) and send it as a bearer token:

```
Authorization: Bearer $SERV_API_KEY
```

## Endpoints

| Method and path | Format | Reference |
| - | - | - |
| `POST /v1/chat/completions` | OpenAI | [Chat completions](https://docs.openserv.ai/serv-reasoning/api/chat-completions.md) |
| `POST /v1/responses` | OpenAI | [Responses](https://docs.openserv.ai/serv-reasoning/api/responses.md) |
| `POST /v1/messages` | Anthropic | [Messages](https://docs.openserv.ai/serv-reasoning/api/messages.md) |

`/v1/chat/completions` works with every model in the [catalog](https://docs.openserv.ai/serv-reasoning/models.md). `/v1/responses` is OpenAI models only. `/v1/messages` accepts most of the catalog — see [endpoint compatibility](https://docs.openserv.ai/serv-reasoning/api/compatibility.md).

## System prompt required

Every request must include a system prompt. Where it goes depends on the endpoint — a `system` message for chat completions, top-level `instructions` for responses, or top-level `system` for messages. Requests without one are rejected.

## Errors

The API uses standard HTTP status codes. Error bodies follow the format of the endpoint's upstream API.

| Status | Meaning |
| - | - |
| `400` | Invalid request — missing system prompt, unsupported model, or malformed body. |
| `401` | Missing or invalid API key. |
| `404` | Unknown path or model. |
| `429` | Rate limited. |
| `5xx` | Server or upstream provider error. |

```json theme={null}
{
  "error": {
    "type": "invalid_request_error",
    "message": "A system prompt is required. Please include a system or developer message in your request."
  }
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.