> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Audit reasoning prompts with Kronos

> Audit and repair SERV's generated reasoning prompt before inference.

Kronos audits the reasoning prompt SERV generates from your system prompt. If the audit finds a semantic problem, SERV repairs the generated prompt and checks it again. It repeats this loop up to its configured internal repair limit, then uses the latest generated prompt.

## Add Kronos to a model ID

Add `-serv-kronos` to a supported base model ID. The suffix is a model feature, not an application tool, so you do not add a function definition or implement a handler for it.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini-serv-kronos",
  messages: [
    {
      role: "system",
      content: "Approve refunds only when the order is eligible and the customer provides the order ID.",
    },
    { role: "user", content: "Can I get a refund for order 1842?" },
  ],
});
```

SERV removes the feature suffix before routing to the upstream provider. Use a real base model from the [model catalog](https://docs.openserv.ai/serv-reasoning/models.md), then append `-serv-kronos` exactly once.

## When to use Kronos

Use Kronos for system prompts with procedural rules, multiple conditions, or consequences that must remain consistent. Add it when ambiguity in the generated reasoning prompt could change the model’s decision.

Kronos does not replace application authorization, tool-argument validation, or testing. Keep those checks in your application.

## Cost and behavior

On a cache miss, Kronos adds at least one audit call and may add repair and re-audit calls. Those calls increase cost and latency. A matching cache hit reuses the previously audited reasoning prompt, but the requested upstream model still runs for every request. See [Monitor usage and billing](https://docs.openserv.ai/serv-reasoning/tutorials/usage-and-billing.md).

You can combine Kronos with Multipath by using `-serv-kronos-multipath`. See [Use Multipath for branching instructions](https://docs.openserv.ai/serv-reasoning/tutorials/multipath.md).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.