> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Use application tools

> Combine your own function tools with SERV features.

## Know which tools your server executes

Application tools describe functions that your code executes. SERV Tools are control markers that SERV consumes before the model runs. SERV recognizes a fixed set of marker names; use the documented names for SERV features.

You can put both kinds in one `tools` array. SERV removes its marker tools and forwards your application tools unchanged. The model can call `get_order`, but it never calls `serv_prompt_guard` or `serv_shadow_agent`.

| SERV Tool | Endpoint support | Constraint |
| - | - | - |
| `serv_prompt_guard` | Chat Completions, Responses, Messages | Runs before the requested model |
| `serv_shadow_agent` | Chat Completions, Responses, Messages | Non-streaming requests only |
| `serv_disable_content_filter` | Chat Completions and Responses | Disables the default output leak detector |

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "Use get_order for order status. Never guess." },
    { role: "user", content: "What is the status of order 1842?" },
  ],
  tools: [{
    type: "function",
    function: {
      name: "get_order",
      description: "Look up an order by its ID.",
      parameters: {
        type: "object",
        properties: { order_id: { type: "string" } },
        required: ["order_id"],
        additionalProperties: false,
      },
    },
  }],
});
```

When the model calls an application tool, your server executes it and sends the result in a follow-up request. SERV forwards unrecognized tools normally, even when their names begin with `serv_`.

State when the model should call each tool, define a strict input schema, and validate every argument before performing a side effect. Put the tool-use policy in the system prompt. For example: “Use `get_order` for every order-status question. Never guess an order status.”

## Combine application tools with SERV Tools

The same request can enable SERV protection, quality validation, and an application function:

```js theme={null}
tools: [
  { type: "function", function: { name: "serv_prompt_guard" } },
  {
    type: "function",
    function: {
      name: "serv_shadow_agent",
      parameters: {
        type: "object",
        properties: { hint: { type: "string", default: "Cite the order status returned by the tool." } },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_order",
      description: "Look up an order by its ID.",
      parameters: {
        type: "object",
        properties: { order_id: { type: "string" } },
        required: ["order_id"],
        additionalProperties: false,
      },
    },
  },
]
```

SERV consumes the first two markers. Only `get_order` reaches the model. Your server remains responsible for executing `get_order`, checking the arguments, and handling the follow-up conversation.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.