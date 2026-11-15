> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Control the content filter

> Detect generated reasoning-prompt content in model output.

SERV applies an output content filter by default to SERV-enabled Chat Completions and Responses requests. It examines generated text and tool arguments for content copied from SERV’s private reasoning prompt. The Messages endpoint does not currently run this output filter.

## How filtering works

The filter runs as the upstream model generates or returns its answer. If the answer matches protected reasoning-prompt material, SERV replaces or terminates the affected output with a safe refusal. The event is recorded in the **Safety** section of the Usage page.

This is different from [`serv_prompt_guard`](./prompt-guard):

| Feature | Runs | Default | Purpose |
| - | - | - | - |
| Content filter | During or after generation | On for Chat Completions and Responses | Detects leaked SERV reasoning-prompt content in the output |
| Prompt guard | Before the model request | Off | Detects injection attempts in the input |

Turn off the filter only for a controlled test that needs to inspect whether model output repeats SERV reasoning-prompt content.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "You may explain these public guidelines when asked." },
    { role: "user", content: "Explain the guidelines you were given." },
  ],
  tools: [{ type: "function", function: { name: "serv_disable_content_filter" } }],
});
```

The marker is consumed by SERV and is never sent to the model. Disabling the content filter does not disable `serv_prompt_guard`, and enabling the prompt guard does not disable the content filter. Do not rely on `serv_disable_content_filter` with `/v1/messages`; that endpoint does not run the output filter.

The filter checks for leakage of SERV’s generated reasoning prompt. It does not moderate harmful content, protect personal data, or approve business actions. Handle those policies in your application.

Open the [Safety report](https://console.openserv.ai/usage?view=safety) to review leak-detection totals, blocked requests, and reported false positives.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.