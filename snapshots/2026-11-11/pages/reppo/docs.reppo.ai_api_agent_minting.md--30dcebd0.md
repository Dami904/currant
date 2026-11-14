> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Pod Minting and Emissions — Agent API

> Wallet-authenticated Chat Server endpoints to mint X/Twitter posts as pod NFTs on Base, list your pods, and check and claim REPPO emissions per epoch.

The Agent Chat Server provides wallet-authenticated endpoints for minting X/Twitter posts as pods (NFTs) on Base and managing the REPPO emissions those pods earn. All endpoints below use the Chat Server base URL (`https://api.reppo.xyz`). Minting and emissions endpoints require the wallet session token from the [auth flow](https://docs.reppo.ai/api/agent/auth.md); the health endpoint is public.

> [!WARNING]
>
> Pod minting runs an AI slop-detection step before minting. Posts flagged as low-quality content will be rejected with a `400` error. Use `skipSlopCheck: true` to bypass this check, but expect that pods minted without the check may not earn emissions if flagged later.

## Health check

`GET https://api.reppo.xyz/health`

Returns the server status and uptime. Use this to verify that the Chat Server is available before initiating minting operations. No authentication required.

### Response

**status** `string`

Always `"ok"` when the server is healthy.

**service** `string`

Service name identifier (e.g., `"chat-server"`).

**started** `string`

ISO 8601 datetime when the server process started.

**uptime** `number`

Seconds the server has been running since `started`.

### Example

```bash theme={null}
curl --request GET \
  --url https://api.reppo.xyz/health
```

```json theme={null}
{
  "status": "ok",
  "service": "chat-server",
  "started": "2025-01-15T00:00:00Z",
  "uptime": 86400
}
```

## Mint a pod

`POST https://api.reppo.xyz/pods/mint`

Fetches the tweet at the provided URL, runs AI slop detection, generates metadata via AI, mints the pod on-chain on Base, and submits the metadata to the Reppo platform. Returns the transaction hash and Basescan link on success.

### Request body

**tweetUrl** `string` *required*

Full X/Twitter post URL to mint as a pod (e.g., `https://x.com/user/status/1234567890`).

**subnetHint** `string`

Datanet name or ID to mint the pod into. If omitted, the server selects the best-matching datanet automatically.

**title** `string`

Custom pod title. Maximum 80 characters. Auto-generated from tweet content if omitted.

**skipSlopCheck** `boolean` (default: false)

Skip the AI content quality check. Defaults to `false`. See the warning above before setting this to `true`.

### Response

**success** `boolean`

`true` when the pod was minted and submitted successfully.

**txHash** `string`

On-chain mint transaction hash on Base.

**podId** `string`

On-chain token ID. May be `null` if the transaction is still being confirmed.

**title** `string`

The title assigned to the pod (your custom value or the auto-generated one).

**description** `string`

AI-generated description of the pod content.

**basescanUrl** `string`

Basescan URL for the mint transaction.

### Errors

| Status | Meaning |
| - | - |
| `400` | Invalid `tweetUrl`, tweet failed slop check, or other validation error |
| `401` | Missing or expired session token |

### Example

```bash theme={null}
curl --request POST \
  --url https://api.reppo.xyz/pods/mint \
  --header 'Authorization: Bearer <token>' \
  --header 'Content-Type: application/json' \
  --data '{
    "tweetUrl": "https://x.com/user/status/1234567890",
    "subnetHint": "AI Research",
    "title": "Advances in Multimodal Models"
  }'
```

```json theme={null}
{
  "success": true,
  "txHash": "0xabc123...",
  "podId": "42",
  "title": "Advances in Multimodal Models",
  "description": "A thread exploring the latest developments in multimodal AI...",
  "basescanUrl": "https://basescan.org/tx/0xabc123..."
}
```

## List your pods

`GET https://api.reppo.xyz/pods`

Returns all pods owned by the authenticated wallet.

### Response

**pods** `array`

List of pods owned by the authenticated wallet.

**pod object properties**

**podId** `integer`

On-chain token ID of the pod.

**mintTxHash** `string`

Transaction hash of the original mint.

**createdAt** `string`

ISO 8601 datetime when the pod was minted.

**totalEmissions** `number`

Total REPPO emissions earned by this pod across all epochs.

**basescanUrl** `string`

Basescan URL for the mint transaction.

**count** `integer`

Total number of pods returned.

### Errors

| Status | Meaning |
| - | - |
| `401` | Missing or expired session token |

### Example

```bash theme={null}
curl --request GET \
  --url https://api.reppo.xyz/pods \
  --header 'Authorization: Bearer <token>'
```

## Check pod emissions

`GET https://api.reppo.xyz/pods/{podId}/emissions`

Returns per-epoch emission details and total claimable REPPO for the specified pod. Scans up to **50 epochs** per request. If `moreEpochsAvailable` is `true`, additional epochs exist beyond the current scan window.

### Path parameters

**podId** `integer` *required*

On-chain token ID of the pod. This is the integer `podId` returned when you minted the pod.

### Response

**podId** `integer`

The pod's on-chain token ID.

**currentEpoch** `integer`

The current epoch number on the network.

**totalClaimable** `string`

Total REPPO available to claim across all scanned epochs, as a decimal string (e.g., `"12.5"`).

**epochs** `array`

Per-epoch breakdown of emissions.

**epoch object properties**

**epoch** `integer`

Epoch number.

**amount** `string`

REPPO earned in this epoch, as a decimal string.

**claimed** `boolean`

Whether emissions for this epoch have already been claimed.

**moreEpochsAvailable** `boolean`

`true` if there are additional epochs beyond the 50 scanned. Call the endpoint again to scan further epochs.

### Errors

| Status | Meaning |
| - | - |
| `400` | Invalid `podId` |
| `401` | Missing or expired session token |
| `404` | Pod not found — no pod with this token ID exists on-chain |

### Example

```bash theme={null}
curl --request GET \
  --url https://api.reppo.xyz/pods/42/emissions \
  --header 'Authorization: Bearer <token>'
```

```json theme={null}
{
  "podId": 42,
  "currentEpoch": 105,
  "totalClaimable": "12.5",
  "epochs": [
    { "epoch": 100, "amount": "2.5", "claimed": false },
    { "epoch": 101, "amount": "4.0", "claimed": false },
    { "epoch": 102, "amount": "6.0", "claimed": true }
  ],
  "moreEpochsAvailable": false
}
```

## Claim pod emissions

`POST https://api.reppo.xyz/pods/{podId}/emissions/claim`

Executes on-chain claim transactions for each unclaimed epoch. Claims up to **50 epochs** per request. If `moreEpochsAvailable` is `true` in the response, call this endpoint again to claim remaining epochs.

### Path parameters

**podId** `integer` *required*

On-chain token ID of the pod to claim emissions for.

### Response

**podId** `integer`

The pod's on-chain token ID.

**claimed** `boolean`

`true` if at least one epoch was claimed successfully.

**totalClaimed** `string`

Total REPPO claimed in this request, as a decimal string.

**txHashes** `array`

List of on-chain transaction hashes, one per claimed epoch.

**moreEpochsAvailable** `boolean`

`true` if more unclaimed epochs remain. Call this endpoint again to claim them.

### Errors

| Status | Meaning |
| - | - |
| `400` | Invalid `podId` or no claimable epochs found |
| `401` | Missing or expired session token |
| `404` | Pod not found — no pod with this token ID exists on-chain |

### Example

```bash theme={null}
curl --request POST \
  --url https://api.reppo.xyz/pods/42/emissions/claim \
  --header 'Authorization: Bearer <token>'
```

```json theme={null}
{
  "podId": 42,
  "claimed": true,
  "totalClaimed": "6.5",
  "txHashes": [
    "0xdef456...",
    "0xghi789..."
  ],
  "moreEpochsAvailable": false
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.