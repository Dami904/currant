> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Control prompt caching

> Reuse a generated reasoning prompt or force SERV to regenerate it.

SERV caches generated reasoning prompts per organization. The cache is enabled by default.

## How caching works

On the first request with a system prompt, SERV generates a reasoning prompt and stores it. A later request in the same organization can reuse it when the original system prompt, SERV transformation type, and relevant prompt versions match. The requested application model is not part of the cache key. The customer request still goes to the upstream model each time; caching applies only to SERV’s reasoning-prompt generation.

Cache entries are organization-scoped and expire after 30 days. A cache hit avoids a new reasoning-prompt generation charge and can reduce latency. It does not cache the model’s answer.

For Chat Completions and Responses, bypass the cache for one request with `metadata.prompt_cache`:

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  metadata: { prompt_cache: "disabled" },
  messages: [
    { role: "system", content: "Analyze the latest version of this policy." },
    { role: "user", content: "Review these policy changes: ..." },
  ],
});
```

SERV removes this metadata before forwarding the request. You can also send `X-OpenServ-Prompt-Cache: false`. The Messages endpoint currently always uses the SERV prompt cache and ignores these opt-out controls.

Keep system prompts stable when possible. Put changing data in user messages or tool results so SERV can reuse the generated reasoning prompt. A changed system-prompt string creates a different cache key automatically.

Use the opt-out when you need to regenerate an unchanged prompt during testing or incident response. Caching does not make a system prompt a safe place for secrets; follow your organization’s data-handling policy.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.