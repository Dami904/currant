> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Monitor usage and billing

> Track request cost, latency, tokens, and feature outcomes.

Open **Usage** in the console after making a request. Its **Cost**, **Performance**, **Tokens**, and **Activity** views show spend, latency, token counts, request details, and prompt-cache hits. The dedicated [Safety report](https://console.openserv.ai/usage?view=safety) covers Guard and leak detection. The [Shadow Agent report](https://console.openserv.ai/usage?view=shadow-agent) covers validation outcomes. Your remaining balance appears on the dashboard and **Billing** page.

Each request can include more than one billable component: upstream model inference, SERV reasoning generation, prompt-guard evaluation, audit or repair work, and shadow-agent validation. A cache hit avoids a new SERV reasoning-generation call, but the upstream model still runs and is billed.

Test one variable at a time: model, reasoning effort, prompt, tools, schema, or safety feature. Use the same evaluation set to compare task success, failure rate, latency, and total cost.

Organization owners can open **Billing** from the account menu to purchase credits and configure auto top-up. AWS Marketplace organizations see their AWS billing status instead. See [Models](https://docs.openserv.ai/serv-reasoning/models.md) for model pricing.

If your balance cannot cover the request’s estimated ceiling, SERV may reject it before billable inference begins. Use a reasonable output-token ceiling and monitor `finish_reason` or the endpoint’s stop reason for truncation.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.