> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Pod Engagement API — Votes, Comments, Feedback

> Register on-chain veREPPO votes, post written comments, and store qualitative vote feedback for pods — all authenticated with your Privy session cookie.

The engagement endpoints let users interact with pods in three ways: commenting for discussion, voting to influence curation rewards, and submitting qualitative feedback alongside a vote. All engagement endpoints require Privy cookie authentication. Votes are on-chain actions on Base — you must submit the transaction first and pass the resulting hash to the API.

***

## List comments for a pod

```
GET /pods/{podId}/comments
```

Returns all comments posted on a pod, ordered by creation time.

**Auth:** Privy cookie

### Path parameters

**podId** `string` *required*

The internal ID of the pod.

**Response `200`**

```json theme={null}
{
  "data": {
    "comments": [
      {
        "id": "comment_001",
        "comment": "Great summary of the paper.",
        "createdAt": "2025-04-01T10:30:00Z",
        "userName": "alice",
        "thumbnailURL": "https://example.com/avatar.png"
      }
    ]
  }
}
```

### Response fields

**data.comments** `array` *required*

Ordered list of comments on the pod.

**data.comments\[].id** `string` *required*

Internal comment ID.

**data.comments\[].comment** `string` *required*

The comment text.

**data.comments\[].createdAt** `string (date-time)` *required*

ISO 8601 timestamp when the comment was posted.

**data.comments\[].userName** `string` *required*

Display name of the commenter.

**data.comments\[].thumbnailURL** `string | null`

Avatar URL for the commenter.

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/pods/pod_xyz789/comments \
  -H "Cookie: privy-token=<your-privy-token>"
```

***

## Create a comment on a pod

```
POST /pods/{podId}/comments
```

Posts a new comment on a pod. Returns the internal ID of the created comment.

**Auth:** Privy cookie

### Path parameters

**podId** `string` *required*

The internal ID of the pod.

### Request body

**podId** `string` *required*

The internal ID of the pod (must match the path parameter).

**comment** `string` *required*

The comment text.

**Response `201`**

```json theme={null}
{
  "data": {
    "id": "comment_002"
  }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/pods/pod_xyz789/comments \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "podId": "pod_xyz789",
    "comment": "This is a well-curated summary — very useful for the datanet."
  }'
```

***

## Register a vote for a pod

```
POST /pods/{podId}/votes
```

Records a vote for a pod after the corresponding on-chain transaction has been confirmed on Base. Votes affect the pod's curation score for the given epoch and determine reward distribution.

> [!WARNING]
>
> You must submit the vote transaction on Base before calling this endpoint. Passing an invalid or unconfirmed `txHash` will result in a `400` error.

**Auth:** Privy cookie

### Path parameters

**podId** `string` *required*

The internal ID of the pod being voted on.

### Request body

**podId** `string` *required*

The internal ID of the pod (must match the path parameter).

**epoch** `integer` *required*

The epoch number in which this vote is being cast.

**votes** `number` *required*

The weighted vote amount, derived from the voter's veREPPO balance.

**upVote** `boolean` *required*

`true` for an up-vote, `false` for a down-vote.

**txHash** `string` *required*

Transaction hash of the on-chain vote submitted on Base.

**Response `200`**

```json theme={null}
{
  "data": {
    "id": "vote_abc456"
  }
}
```

### Response fields

**data.id** `string` *required*

Internal ID of the created vote record.

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/pods/pod_xyz789/votes \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "podId": "pod_xyz789",
    "epoch": 42,
    "votes": 250.5,
    "upVote": true,
    "txHash": "0xdef456..."
  }'
```

***

## Store vote feedback for a pod

```
POST /feedback/pods/{id}
```

Stores qualitative written feedback alongside a vote. Use this to capture the voter's reasoning — the feedback is linked to the specific vote context (epoch, voting power, and direction).

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The internal ID of the pod.

### Request body

**podId** `string` *required*

The internal ID of the pod.

**feedback** `string` *required*

The voter's written rationale or qualitative assessment.

**epoch** `integer` *required*

The epoch number in which the vote was cast.

**votingPower** `number` *required*

The voter's veREPPO voting power at the time of the vote.

**upVote** `boolean` *required*

`true` if the associated vote was an up-vote, `false` for a down-vote.

**privateSubnetId** `string` *required*

Internal ID of the datanet the pod belongs to.

**votes** `number` *required*

The weighted vote amount associated with this feedback entry.

**Response `201`**

```json theme={null}
{
  "data": {
    "id": "feedback_789"
  }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/feedback/pods/pod_xyz789 \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "podId": "pod_xyz789",
    "feedback": "The summary is accurate and well-structured, covering the key contributions clearly.",
    "epoch": 42,
    "votingPower": 1500.0,
    "upVote": true,
    "privateSubnetId": "subnet_abc123",
    "votes": 250.5
  }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.