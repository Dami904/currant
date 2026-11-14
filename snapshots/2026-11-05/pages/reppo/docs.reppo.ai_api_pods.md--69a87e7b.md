> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Pod API Endpoints — Platform API

> Create pod drafts, record on-chain mints and republishes, query your own pods, and browse the public pod catalog — all via the Reppo Platform API.

Pods are the individual data units published into datanets on Reppo. Each pod represents a piece of content (article, dataset, social post, PDF, or video) minted as an NFT on Base. The Platform API lets you create pod drafts, record on-chain mints, republish pods across datanets, and retrieve both your own pods and the public pod catalog. Authenticated endpoints require a valid `privy-token` cookie.

***

## List my pods

```
GET /me/pods
```

Returns all pods created by the authenticated user.

**Auth:** Privy cookie

**Response `200`**

```json theme={null}
{
  "data": {
    "pods": [UserPod]
  }
}
```

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/me/pods \
  -H "Cookie: privy-token=<your-privy-token>"
```

***

## Create a pod draft

```
POST /me/pods
```

Creates a new pod draft. The pod is not on-chain until you call the mint endpoint with a valid transaction hash.

**Auth:** Privy cookie

### Request body

**subnetId** `string` *required*

ID of the datanet this pod will be published into.

**podName** `string` *required*

Display name of the pod. Between 3 and 50 characters.

**url** `string (uri)` *required*

Canonical URL of the content (e.g., the original article or social post).

**platform** `string` *required*

Platform the content originates from (e.g., `X`, `Substack`, `YouTube`). Between 2 and 50 characters.

**category** `string` *required*

Category label for the content (e.g., `AI Research`, `DeFi`). Between 2 and 50 characters.

**imageURL** `string (uri)`

URL to the pod's cover image. Optional.

**thumbnailURL** `string (uri)`

URL to a thumbnail image. Optional.

**pdfURL** `string (uri)`

URL to a PDF version of the content. Optional.

**videoURL** `string (uri)`

URL to a video version of the content. Optional.

**podDescription** `string` *required*

Short description of the pod's content. Between 10 and 200 characters.

**agreeToTerms** `boolean` *required*

Must be `true`. Confirms the publisher agrees to the Reppo terms of service.

**Response `201`**

```json theme={null}
{
  "data": {
    "id": "pod_xyz789"
  }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/me/pods \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "subnetId": "subnet_abc123",
    "podName": "Attention Is All You Need — Summary",
    "url": "https://arxiv.org/abs/1706.03762",
    "platform": "ArXiv",
    "category": "AI Research",
    "podDescription": "A concise summary of the original Transformer architecture paper.",
    "agreeToTerms": true
  }'
```

***

## Get one of my pods

```
GET /me/pods/{id}
```

Returns a single pod owned by the authenticated user, including moderation status and voting volumes.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The pod's internal ID.

**Response `200`**

```json theme={null}
{
  "data": {
    "pod": UserPod
  }
}
```

***

## Mint a pod

```
POST /me/pods/{id}/mint
```

Records the on-chain mint of a pod draft. Submit this after the Base transaction has been confirmed.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The pod's internal ID.

### Request body

**podId** `string` *required*

The pod's internal ID (must match the path parameter).

**txHash** `string` *required*

Transaction hash of the on-chain mint.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/me/pods/pod_xyz789/mint \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "podId": "pod_xyz789",
    "txHash": "0xabc123..."
  }'
```

***

## Republish a pod

```
POST /me/pods/{id}/republish
```

Records an on-chain republish of an existing pod into a new or the same datanet.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The pod's internal ID.

### Request body

**podId** `string` *required*

The pod's internal ID.

**txHash** `string` *required*

Transaction hash of the on-chain republish transaction.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Get pods voted on during an epoch

```
GET /me/pods/votes/epochs/{epochId}
```

Returns the list of pods the authenticated user voted on during the specified epoch.

**Auth:** Privy cookie

### Path parameters

**epochId** `integer` *required*

The epoch number to query.

**Response `200`**

```json theme={null}
{
  "data": {
    "pods": [UserPod]
  }
}
```

***

## List public pods

```
GET /public/pods
```

Returns active public pods across all datanets. No authentication required. Supports pagination, search, and filtering by epoch and datanet.

### Query parameters

**page** `integer`

Page number. Minimum `1`. Default `1`.

**limit** `integer`

Results per page. Minimum `1`. Default `10`.

**search** `string`

Free-text search against pod name and description.

**filters\[currentEpoch]** `integer`

Filter pods active in a specific epoch number.

**filters\[subnet]** `string`

Filter pods by datanet ID.

**Response `200`**

```json theme={null}
{
  "data": {
    "pods": [PublicPod]
  }
}
```

### Example

```bash theme={null}
curl "https://reppo.ai/api/v1/public/pods?page=1&limit=10&filters[subnet]=subnet_abc123"
```

***

## Get a public pod by ID

```
GET /public/pods/{podId}
```

Returns a single public pod by its internal ID, including creator info and cumulative vote volumes. No authentication required.

### Path parameters

**podId** `string` *required*

The pod's internal ID.

**Response `200`**

```json theme={null}
{
  "data": {
    "pod": PublicPod
  }
}
```

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/public/pods/pod_xyz789
```

***

## Get public pod votes for an epoch

```
GET /public/pods/{podId}/votes/epochs/{epoch}
```

Returns all votes cast for a pod during a specific epoch. No authentication required.

### Path parameters

**podId** `string` *required*

The pod's internal ID.

**epoch** `integer` *required*

The epoch number to query.

**Response `200`**

```json theme={null}
{
  "data": {
    "podVotes": [
      {
        "id": "vote_001",
        "userId": "user_abc",
        "votes": 150.0,
        "createdAt": "2025-04-01T12:00:00Z",
        "voter": "0xVoterAddress",
        "epoch": 42,
        "upVote": true
      }
    ]
  }
}
```

***

## UserPod schema

Returned by authenticated pod endpoints (`/me/pods/*`).

**id** `string` *required*

Internal pod ID.

**name** `string` *required*

Display name of the pod.

**description** `string` *required*

Short description of the pod's content.

**tokenId** `integer | null`

On-chain NFT token ID. `null` until the pod is minted.

**privateSubnetId** `string` *required*

Internal ID of the datanet this pod belongs to.

**url** `string (uri)` *required*

Canonical URL of the original content.

**imageUrl** `string | null`

URL to the pod's cover image.

**thumbnailUrl** `string | null`

URL to the pod's thumbnail image.

**status** `string` *required*

Current status (e.g., `draft`, `active`).

**banned** `boolean` *required*

Whether this pod has been banned from the platform.

**banReason** `string | null`

Reason for the ban, if applicable.

**podValidityEpoch** `integer` *required*

The epoch through which this pod is considered valid for curation rewards.

**cumulativeUpVotesVolume** `number` *required*

Total weighted up-vote volume accumulated across all epochs.

**cumulativeDownVotesVolume** `number` *required*

Total weighted down-vote volume accumulated across all epochs.

**createdAt** `string (date-time)` *required*

ISO 8601 timestamp of when the pod was created.

**updatedAt** `string (date-time)` *required*

ISO 8601 timestamp of the last update.

***

## PublicPod schema

Returned by unauthenticated pod endpoints (`/public/pods/*`). Includes creator info and media URLs.

**id** `string` *required*

Internal pod ID.

**name** `string` *required*

Display name of the pod.

**description** `string` *required*

Short description of the pod's content.

**tokenId** `integer` *required*

On-chain NFT token ID.

**privateSubnetId** `string` *required*

Internal ID of the datanet this pod belongs to.

**url** `string (uri)` *required*

Canonical URL of the original content.

**imageUrl** `string | null`

URL to the pod's cover image.

**thumbnailUrl** `string | null`

URL to the pod's thumbnail.

**videoUrl** `string | null`

URL to a video version of the content.

**pdfUrl** `string | null`

URL to a PDF version of the content.

**creator** `object` *required*

Object containing the creator's `id` (string, required), `username` (string | null), and `avatarUrl` (string | null).

**createdAt** `string (date-time)` *required*

ISO 8601 timestamp of when the pod was created.

**updatedAt** `string (date-time)` *required*

ISO 8601 timestamp of the last update.

**podValidityEpoch** `integer` *required*

The epoch through which this pod is valid for curation rewards.

**cumulativeUpVotesVolume** `number` *required*

Total weighted up-vote volume.

**cumulativeDownVotesVolume** `number` *required*

Total weighted down-vote volume.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.