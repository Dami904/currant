> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Stream a response

> Read SERV response chunks over server-sent events.

Set `stream: true` and iterate over the returned stream.

```js theme={null}
const stream = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  stream: true,
  messages: [
    { role: "system", content: "You are a concise technical writer." },
    { role: "user", content: "Explain database indexes in three paragraphs." },
  ],
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}
```

Streaming is supported by Chat Completions, Responses, and Messages, using each endpoint’s normal event format. Prompt Guard can return a streamed refusal. The output content filter runs on Chat Completions and Responses streams, but not Messages streams.

You cannot combine streaming with `serv_shadow_agent`. SERV rejects that combination with a `400` response because Shadow Agent must validate a completed response.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.