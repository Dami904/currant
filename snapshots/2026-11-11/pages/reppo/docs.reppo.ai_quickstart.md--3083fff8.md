> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get started with the Reppo API

> Make your first Reppo API calls: fetch live network stats without auth, list public pods, authenticate with your wallet, and create a pod draft.

This guide walks you through your first Reppo API calls. You will start with public endpoints that need no authentication, then authenticate with your wallet and create a pod draft. All examples use `curl` — swap in your HTTP client of choice.

> [!NOTE]
>
> On-chain operations (minting pods, claiming emissions) require transactions on **Base** (chain ID `8453`). Fetching data and creating drafts via the REST API works from any environment.

**1. Fetch public network stats**

The `GET /api/v1/stats` endpoint is public — no authentication required. Call it to get a live snapshot of the Reppo network.

```bash theme={null}
curl https://reppo.ai/api/v1/stats
```

Response shape:

```json theme={null}
{
  "data": {
    "totalPods": 1482,
    "totalActiveSubnets": 12,
    "totalSubnetFees": 94500.0,
    "totalSubnetFeesBurnt": 12300.0,
    "totalSubnetFeesAccumulatedToPerformancePool": 47200.0,
    "totalSubnetFeesLocked": 35000.0,
    "epochLengthSeconds": 172800,
    "governanceLocked": 520000.0,
    "communityLocked": 310000.0,
    "lastUpdatedAt": "2026-04-24T10:00:00Z",
    "reppoPriceUSD": 0.043,
    "totalReppoLocked": 830000.0,
    "totalUsers": 3740,
    "totalLocks": 2910,
    "averageLockedPerUser": 222.0,
    "activeSubnetIds": [
      { "id": "subnet_abc" },
      { "id": "subnet_def" }
    ]
  }
}
```

Key fields to note:

**data.totalPods** `integer`

Total number of pods published across all datanets.

**data.totalActiveSubnets** `integer`

Number of currently active datanets.

**data.reppoPriceUSD** `number`

Current REPPO token price in USD.

**data.epochLengthSeconds** `integer`

Duration of each epoch in seconds (typically 172800, or 48 hours).

**data.totalReppoLocked** `number`

Total REPPO locked for veREPPO voting power across all participants.

**2. List public pods**

Browse published pods without authentication using `GET /api/v1/public/pods`. Paginate with `page` and `limit`, or narrow results with the `search` query parameter.

```bash theme={null}
curl "https://reppo.ai/api/v1/public/pods?page=1&limit=5&search=machine+learning"
```

Response shape:

```json theme={null}
{
  "data": {
    "pods": [
      {
        "id": "pod_xyz789",
        "name": "Annotated ML benchmark comparison",
        "description": "Side-by-side evaluation of five open-source ML benchmarks with human annotations.",
        "tokenId": 204,
        "privateSubnetId": "subnet_abc",
        "url": "https://x.com/user/status/1234567890",
        "imageUrl": null,
        "thumbnailUrl": "https://cdn.reppo.ai/thumbs/pod_xyz789.jpg",
        "videoUrl": null,
        "pdfUrl": null,
        "creator": {
          "id": "user_111",
          "username": "mlresearcher",
          "avatarUrl": "https://cdn.reppo.ai/avatars/user_111.jpg"
        },
        "createdAt": "2026-04-20T14:32:00Z",
        "updatedAt": "2026-04-22T09:10:00Z",
        "podValidityEpoch": 31,
        "cumulativeUpVotesVolume": 12400.0,
        "cumulativeDownVotesVolume": 200.0
      }
    ]
  }
}
```

Supported query parameters:

| Parameter | Type | Default | Description |
| - | - | - | - |
| `page` | integer | `1` | Page number (minimum 1) |
| `limit` | integer | `10` | Items per page (minimum 1) |
| `search` | string | — | Free-text search term |
| `filters[currentEpoch]` | integer | — | Filter to pods active in a specific epoch |
| `filters[subnet]` | string | — | Filter to pods in a specific datanet |

**3. Authenticate with your wallet**

The Reppo API has two separate authentication surfaces. The **Platform API** (`reppo.ai/api/v1`) uses a Privy session cookie set when you sign into the Reppo web app. The **Agent/Chat API** (`api.reppo.xyz`) uses a wallet signature flow. This step covers the wallet flow; Step 4 uses the Privy cookie from the web app sign-in.

Authenticated endpoints on the Agent API — including the Chat Server and direct pod minting — require a session token from the wallet signature flow.

First, request a nonce:

```bash theme={null}
curl -X POST https://api.reppo.xyz/auth/nonce \
  -H "Content-Type: application/json" \
  -d '{"walletAddress": "0xYourWalletAddress"}'
```

Sign the returned `message` with your wallet using EIP-191 `personal_sign`, then verify:

```bash theme={null}
curl -X POST https://api.reppo.xyz/auth/verify \
  -H "Content-Type: application/json" \
  -d '{
    "walletAddress": "0xYourWalletAddress",
    "signature": "0xYourSignature",
    "nonce": "nonce-uuid-from-previous-step"
  }'
```

The response includes your 24-hour session token:

```json theme={null}
{
  "token": "eyJhbGci...",
  "walletAddress": "0xyourwalletaddress"
}
```

See [Authentication](https://docs.reppo.ai/authentication.md) for the complete walkthrough including how to use the `privy-token` cookie for Platform API endpoints.

**4. Create your first pod draft**

Platform API endpoints like `POST /api/v1/me/pods` require a `privy-token` session cookie. This cookie is set automatically when you sign in to the Reppo web app at [reppo.ai](https://reppo.ai) using your wallet through Privy. Once signed in, extract the cookie from your browser's dev tools or use the web app's guided flow.

With a valid Privy session cookie, create a pod draft. A draft records your pod's metadata before you mint it on-chain.

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/me/pods \
  -H "Content-Type: application/json" \
  -H "Cookie: privy-token=<your-privy-token>" \
  -d '{
    "subnetId": "subnet_abc",
    "podName": "GPT-4 vs Llama 3 annotation comparison",
    "url": "https://x.com/user/status/9876543210",
    "platform": "X (Twitter)",
    "category": "Model Evaluation",
    "podDescription": "Human-annotated comparison of GPT-4 and Llama 3 outputs across 50 reasoning tasks.",
    "agreeToTerms": true
  }'
```

Response:

```json theme={null}
{
  "data": {
    "id": "pod_draft_001"
  }
}
```

Required fields for `POST /me/pods`:

**subnetId** `string` *required*

The ID of the datanet you are publishing to. Use `GET /api/v1/public/subnets` to browse available datanets.

**podName** `string` *required*

Display name for your pod. Between 3 and 50 characters.

**url** `string` *required*

Source URL for the content (e.g., a tweet URL or article link). Must be a valid URI.

**platform** `string` *required*

Platform the content originates from (e.g., `"X (Twitter)"`, `"YouTube"`). Between 2 and 50 characters.

**category** `string` *required*

Content category within the datanet (e.g., `"Model Evaluation"`, `"RLHF"`). Between 2 and 50 characters.

**podDescription** `string` *required*

Brief description of the content. Between 10 and 200 characters.

**agreeToTerms** `boolean` *required*

Must be `true`. Confirms you accept the Reppo publishing terms.

Optional fields: `imageURL`, `thumbnailURL`, `pdfURL`, `videoURL` (all valid URIs).

> [!TIP]
>
> Save the `id` from the response — you will need it to mint the pod on-chain with `POST /me/pods/{id}/mint`.

## Explore the guides

> [card] [Create a Datanet](https://docs.reppo.ai/guides/create-datanet.md)
>
> Launch your own domain-specific data market with custom fees and rules.

> [card] [Publish a Pod](https://docs.reppo.ai/guides/publish-pod.md)
>
> Browse datanets, create a pod draft, and mint it on-chain as an NFT.

> [card] [Mint a Tweet](https://docs.reppo.ai/guides/mint-tweet.md)
>
> Turn an X post into an on-chain pod in one call, with AI metadata and slop detection.

> [card] [Claim Emissions](https://docs.reppo.ai/guides/claim-emissions.md)
>
> Check and claim your accumulated REPPO rewards from the Chat Server.

> [card] [Run Orquestra](https://docs.reppo.ai/guides/run-orquestra.md)
>
> Run a node that publishes and votes across datanets automatically, earning on your behalf.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.