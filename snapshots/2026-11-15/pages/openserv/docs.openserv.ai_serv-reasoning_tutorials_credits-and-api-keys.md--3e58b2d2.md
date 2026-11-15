> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Add credits and create an API key

> Buy credits for your organization and create an API key.

Open **Billing** from the account menu or go to `/settings/billing`. Only organization owners can add a card, choose a preset or custom amount, and buy credits. Those credits pay for requests made with the organization’s API keys.

After adding a payment method, an owner can set a balance threshold, top-up amount, and monthly limit for auto top-up. AWS Marketplace organizations are invoiced through AWS, so they do not buy credits or configure auto top-up in the console.

To create a key, open **API Keys** or go to `/settings/keys`, select **Create secret key**, name it, and copy the secret immediately. The complete key is shown only once.

```bash theme={null}
export SERV_API_KEY="paste-your-key-here"
```

Use a separate key for development, staging, and production. You can deactivate a key temporarily or revoke it permanently from the same page. Never commit a key or expose it to browser code.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.