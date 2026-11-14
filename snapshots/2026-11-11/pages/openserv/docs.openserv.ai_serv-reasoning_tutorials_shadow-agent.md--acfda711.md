> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Validate output with Shadow Agent

> Validate difficult model outputs and revise failed drafts.

Add `serv_shadow_agent` when an incorrect answer costs more than an additional validation call.

## How validation works

The requested model first produces a draft. SERV then asks a validator to judge that draft against the original request and any validation hint. If the draft fails, SERV asks the upstream model to revise it and validates the new draft, up to the configured validation-attempt limit.

If a draft passes, the caller receives that version. If every attempt fails, SERV returns the latest revision and records an `exhausted` outcome. If the validator or regeneration call aborts, SERV returns a `502` error instead of an unvalidated draft. It does not expose the validator as a tool call to your application.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "Give careful recommendations and state missing information." },
    { role: "user", content: "Is now a good entry point for ETH?" },
  ],
  tools: [{
    type: "function",
    function: {
      name: "serv_shadow_agent",
      parameters: {
        type: "object",
        properties: {
          hint: { type: "string", default: "State what information is missing." },
          max_iterations: { type: "integer", default: 3 },
        },
      },
    },
  }],
});
```

When a draft fails, SERV can ask the requested model to revise it and run the validator again. This works with non-streaming requests only. See [SERV Tools](https://docs.openserv.ai/serv-reasoning/tools.md) for defaults and limits.

## Configure the validator

`hint` adds task-specific criteria to the default meaningful-and-valid check. Make it observable and testable, such as “the answer must include the account ID” or “the recommendation must state missing information.” Avoid vague hints like “be better.”

`max_iterations` controls validation attempts, defaults to `3`, and accepts values from `1` to `10`. A value of `3` permits up to three judge calls and two revisions. Each extra attempt adds possible latency and cost. Raise the limit only when your evaluation data shows enough improvement to justify it.

Because the validator sees the original task context, keep the important requirements in the system prompt and user request. Validate structured data in your application as well.

Open the [Shadow Agent report](https://console.openserv.ai/usage?view=shadow-agent) to see how many responses were validated and whether each passed unchanged, improved before delivery, or could not be validated.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.