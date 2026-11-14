> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Choose reasoning effort

> Set how much reasoning a supported model should perform.

For Chat Completions, use `reasoning_effort` with a model whose catalog entry supports reasoning. `low`, `medium`, and `high` are the common values exposed by the SERV Playground; the upstream provider determines the exact behavior for each model.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  reasoning_effort: "medium",
  messages: [
    { role: "system", content: "Solve constrained planning problems carefully." },
    { role: "user", content: "Plan this project under these constraints: ..." },
  ],
});
```

Run your evaluation set with `low` first. Increase the effort only when the results improve enough to justify the added cost and latency.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.