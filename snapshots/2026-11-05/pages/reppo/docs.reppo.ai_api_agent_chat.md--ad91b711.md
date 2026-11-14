> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# AI Chat API — Ask Questions About Reppo

> Multi-turn AI chat assistant for navigating Reppo — supports general Q&A, guided datanet setup, pod minting, and emissions claim assistance.

The Chat endpoint provides an AI assistant that helps you navigate the Reppo protocol. It supports multi-turn conversations via a persistent session ID and automatically selects an operating mode based on the context of your message. All Chat endpoints use the Chat Server base URL (`https://api.reppo.xyz`) and require a wallet session token obtained from [wallet auth](https://docs.reppo.ai/api/agent/auth.md).

> [!NOTE]
>
> Chat mode is selected automatically based on your message content: `rag` for general protocol Q\&A, `subnet-creation` for guided datanet setup, `minting` for the pod minting flow, and `emissions` for claims assistance. You do not need to specify a mode explicitly.

## Send a message

`POST https://api.reppo.xyz/chat`

Send a message and receive an AI-generated response. Omit `sessionId` to start a new conversation. The response includes the `sessionId` you should pass on follow-up turns.

### Request body

**message** `string` *required*

Your message to the AI assistant. Maximum 4000 characters.

**sessionId** `string`

UUID of an existing session. Omit this field to start a new conversation — the response will return a fresh `sessionId` to use on subsequent turns.

### Response

**sessionId** `string`

UUID identifying this conversation session. Pass this on subsequent requests to continue the conversation.

**response** `string`

The AI-generated response. May include Markdown formatting.

**sources** `array`

RAG documentation sources used to generate the response.

**source object properties**

**source** `string`

Source identifier or URL.

**title** `string`

Title of the referenced document.

**section** `string`

Section within the document.

**mode** `string`

The operating mode selected for this response. One of `rag`, `subnet-creation`, `minting`, or `emissions`.

### Errors

| Status | Meaning |
| - | - |
| `400` | Missing or invalid `message` field |
| `401` | Missing or expired session token |
| `429` | Rate limit exceeded |

### Examples

```bash Start a new conversation theme={null}
curl --request POST \
  --url https://api.reppo.xyz/chat \
  --header 'Authorization: Bearer <token>' \
  --header 'Content-Type: application/json' \
  --data '{
    "message": "What is a datanet on Reppo?"
  }'
```

```bash Continue an existing conversation theme={null}
curl --request POST \
  --url https://api.reppo.xyz/chat \
  --header 'Authorization: Bearer <token>' \
  --header 'Content-Type: application/json' \
  --data '{
    "message": "How do I publish a pod to that datanet?",
    "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }'
```

```json theme={null}
{
  "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "response": "A **datanet** on Reppo is a curated data collection organized around a specific topic or domain...",
  "sources": [
    {
      "source": "docs/concepts/datanets",
      "title": "Datanets",
      "section": "Overview"
    }
  ],
  "mode": "rag"
}
```

## Get session history

`GET https://api.reppo.xyz/chat/{sessionId}/history`

Retrieve the full message history for a conversation session. Only the wallet that created the session can access its history. Sessions expire after **30 days**.

### Path parameters

**sessionId** `string` *required*

UUID of the conversation session to retrieve.

### Response

**sessionId** `string`

UUID of the conversation session.

**messages** `array`

Ordered list of messages in the conversation.

**message object properties**

**role** `string`

Who sent the message. Either `user` or `assistant`.

**content** `string`

The message text.

**timestamp** `string`

ISO 8601 datetime when the message was sent.

**createdAt** `string`

ISO 8601 datetime when the session was created.

**updatedAt** `string`

ISO 8601 datetime of the most recent message.

### Errors

| Status | Meaning |
| - | - |
| `401` | Missing or expired session token |
| `404` | Session not found or expired (sessions expire after 30 days) |

### Example

```bash theme={null}
curl --request GET \
  --url https://api.reppo.xyz/chat/a1b2c3d4-e5f6-7890-abcd-ef1234567890/history \
  --header 'Authorization: Bearer <token>'
```

```json theme={null}
{
  "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "messages": [
    {
      "role": "user",
      "content": "What is a datanet on Reppo?",
      "timestamp": "2025-01-15T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "A **datanet** on Reppo is a curated data collection...",
      "timestamp": "2025-01-15T10:30:02Z"
    }
  ],
  "createdAt": "2025-01-15T10:30:00Z",
  "updatedAt": "2025-01-15T10:30:02Z"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.