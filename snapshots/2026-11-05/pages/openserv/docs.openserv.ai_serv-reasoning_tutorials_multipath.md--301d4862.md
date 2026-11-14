> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Use Multipath for branching instructions

> Make complex, branching system prompts easier for the model to follow.

Multipath uses a separate SERV reasoning transformation for system prompts with several branches, exceptions, or competing rules. SERV generates a Multipath reasoning prompt from the source instructions and sends that transformed prompt to the requested model.

## Add Multipath to a model ID

Add `-serv-multipath` to a supported base model ID. The suffix is a model feature, not an application tool, so you do not add a function definition or implement a handler for it.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini-serv-multipath",
  messages: [
    {
      role: "system",
      content: "Route each request by account type, verification status, region, and escalation priority.",
    },
    { role: "user", content: "A verified business customer in the EU reports a payment failure." },
  ],
});
```

SERV removes the feature suffix before routing to the upstream provider. Use a real base model from the [model catalog](https://docs.openserv.ai/serv-reasoning/models.md), then append `-serv-multipath` exactly once.

## Combine Multipath with Kronos

For complex branching rules that also need semantic auditing, combine the features in one suffix:

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini-serv-kronos-multipath",
  messages,
});
```

The order does not change the selected features. `-serv-multipath-kronos` is also recognized, but use one consistent spelling across your integration.

## When to use Multipath

Use Multipath for decision trees, policy matrices, routing rules, and instructions where different conditions lead to different outcomes. For a short, linear system prompt, start with the standard SERV model and measure before adding the feature.

Multipath does not execute branches or authorize actions in your application. Keep business rules, permissions, and side-effect checks in your code.

The first matching request generates and stores a Multipath reasoning prompt. Later requests in the same organization can reuse it when the source prompt and prompt version match. The requested upstream model still runs for every request. See [Monitor usage and billing](https://docs.openserv.ai/serv-reasoning/tutorials/usage-and-billing.md).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.