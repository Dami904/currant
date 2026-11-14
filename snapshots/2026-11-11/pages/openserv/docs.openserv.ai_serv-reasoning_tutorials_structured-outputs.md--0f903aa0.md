> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Return structured JSON

> Request JSON that follows your application’s schema.

Use a JSON schema when your application consumes the response.

## Define the response contract

A prompt can ask for JSON, but it cannot guarantee valid JSON. A schema defines the expected fields, types, required values, and allowed enums. SERV forwards the schema to a compatible upstream provider and preserves the structured response format.

```js theme={null}
const response = await client.chat.completions.create({
  model: "gpt-5.4-mini",
  messages: [
    { role: "system", content: "Extract the support request into the supplied schema." },
    { role: "user", content: "My invoice has the wrong company name." },
  ],
  response_format: {
    type: "json_schema",
    json_schema: {
      name: "support_request",
      strict: true,
      schema: {
        type: "object",
        properties: {
          category: { type: "string", enum: ["billing", "technical", "account"] },
          summary: { type: "string" },
        },
        required: ["category", "summary"],
        additionalProperties: false,
      },
    },
  },
});

const result = JSON.parse(response.choices[0].message.content);
```

Validate the result at your application boundary. Handle refusals, truncation, invalid JSON, and invalid field values separately.

Keep the schema small and use enums wherever the valid values are known. If the provider cannot honor the requested format, fail visibly rather than silently treating prose as valid application data.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.