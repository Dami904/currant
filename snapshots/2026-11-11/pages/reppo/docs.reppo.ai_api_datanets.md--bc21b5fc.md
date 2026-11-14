> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Datanet (Subnet) API Endpoints

> Create, publish, and manage datanets (subnets) on Reppo — including fee updates, emissions config, and public discovery endpoints.

Datanets (referred to as subnets in the API) are the curated data markets at the heart of the Reppo protocol. Each datanet has its own token economics — access fees, publishing fees, and per-epoch REPPO and primary-token emissions — all of which are configured on-chain and then recorded via these endpoints. Authenticated endpoints require a valid `privy-token` cookie.

***

## List my datanets

```
GET /me/subnets
```

Returns all datanets created by the authenticated user.

**Auth:** Privy cookie

**Response**

```json theme={null}
{
  "data": {
    "subnets": [
      {
        "id": "subnet_01hw9k2mxvfg3q4r5t6y7u8i",
        "subnetName": "AI Research Papers",
        "subnetDescription": "A curated datanet for AI research paper summaries.",
        "thumbnailUrl": null,
        "nativeTokenAddress": "0x1234567890abcdef1234567890abcdef12345678",
        "nativeTokenSymbol": "AITKN",
        "nativeTokenDecimals": 18,
        "tokenId": 7,
        "accessFeeREPPO": 5,
        "emissionsPerEpochREPPO": 100,
        "emissionsPerEpochPrimaryToken": 500,
        "status": "active",
        "upVoteVolume": 4820,
        "downVoteVolume": 310,
        "onboardingPublishers": "Submit concise summaries of peer-reviewed AI papers.",
        "onboardingVoters": "Evaluate summaries for accuracy, clarity, and relevance.",
        "createdByUserId": "user_abc123"
      }
    ]
  }
}
```

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/me/subnets \
  -H "Cookie: privy-token=<your-privy-token>"
```

***

## Create a datanet draft

```
POST /me/subnets
```

Creates a new datanet draft. The datanet is not live on-chain until you call the publish endpoint. Returns the internal ID of the newly created draft.

**Auth:** Privy cookie

### Request body

**subnetCreatorType** `string` *required*

Creator type. Must be one of `individual` or `team`.

**subnetName** `string` *required*

Display name for the datanet. Maximum 100 characters.

**imageURL** `string (uri)`

URL to the datanet's cover image. Optional.

**subnetDescription** `string` *required*

Description of the datanet's purpose and focus. Between 10 and 500 characters.

**onboardingPublishers** `string` *required*

Instructions shown to publishers joining this datanet. Between 10 and 1000 characters.

**onboardingVoters** `string` *required*

Instructions shown to voters in this datanet. Between 10 and 1000 characters.

**subnetGoal** `string` *required*

Short statement of the datanet's data goal. Maximum 100 characters.

**nativeTokenAddress** `string` *required*

Contract address of the primary token used for emissions alongside REPPO.

**nativeTokenSymbol** `string` *required*

Ticker symbol of the primary token. Maximum 5 characters.

**nativeTokenDecimals** `integer` *required*

Decimal precision of the primary token. Must be between 1 and 18.

**Response `201`**

```json theme={null}
{
  "data": {
    "id": "subnet_abc123"
  }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/me/subnets \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "subnetCreatorType": "individual",
    "subnetName": "AI Research Papers",
    "subnetDescription": "A datanet focused on curating high-quality AI research paper summaries.",
    "onboardingPublishers": "Publish concise summaries of peer-reviewed AI papers published in the last 12 months.",
    "onboardingVoters": "Evaluate summaries for accuracy, clarity, and relevance to current AI research.",
    "subnetGoal": "Curate the best AI research summaries",
    "nativeTokenAddress": "0xTokenAddress",
    "nativeTokenSymbol": "AITKN",
    "nativeTokenDecimals": 18
  }'
```

***

## Get one of my datanets

```
GET /me/subnets/{id}
```

Returns a single datanet owned by the authenticated user.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

**Response `200`**

```json theme={null}
{
  "data": {
    "subnet": {
      "id": "subnet_01hw9k2mxvfg3q4r5t6y7u8i",
      "subnetName": "AI Research Papers",
      "subnetDescription": "A curated datanet for AI research paper summaries.",
      "thumbnailUrl": null,
      "nativeTokenAddress": "0x1234567890abcdef1234567890abcdef12345678",
      "nativeTokenSymbol": "AITKN",
      "nativeTokenDecimals": 18,
      "tokenId": 7,
      "accessFeeREPPO": 5,
      "emissionsPerEpochREPPO": 100,
      "emissionsPerEpochPrimaryToken": 500,
      "status": "active",
      "upVoteVolume": 4820,
      "downVoteVolume": 310,
      "onboardingPublishers": "Submit concise summaries of peer-reviewed AI papers.",
      "onboardingVoters": "Evaluate summaries for accuracy, clarity, and relevance.",
      "createdByUserId": "user_abc123"
    }
  }
}
```

***

## Publish a datanet

```
POST /me/subnets/{id}/publish
```

Records the on-chain publication of a datanet draft. You must have already submitted the publish transaction on Base and obtained the transaction hash before calling this endpoint.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID (must match the path parameter).

**txHash** `string` *required*

The transaction hash of the on-chain publish transaction.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Update REPPO access fee

```
POST /me/subnets/{id}/access-fee/reppo
```

Updates the REPPO access fee for a datanet after the corresponding on-chain transaction has been submitted.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID.

**accessFeeREPPO** `number` *required*

New access fee denominated in REPPO.

**txHash** `string` *required*

Transaction hash of the on-chain fee update.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Update pod publishing fee

```
POST /me/subnets/{id}/pod-publishing-fee/reppo
```

Updates the REPPO fee charged to publishers minting pods into this datanet.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID.

**publishingFeeREPPO** `number` *required*

New publishing fee denominated in REPPO.

**txHash** `string` *required*

Transaction hash of the on-chain fee update.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Update pod republishing fee

```
POST /me/subnets/{id}/pod-republishing-fee/reppo
```

Updates the REPPO fee charged when a pod is republished into this datanet.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID.

**republishingFeeREPPO** `number` *required*

New republishing fee denominated in REPPO.

**txHash** `string` *required*

Transaction hash of the on-chain fee update.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Update REPPO emissions per epoch

```
POST /me/subnets/{id}/emissions-per-epoch/reppo
```

Updates the amount of REPPO emitted to curators per epoch in this datanet.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID.

**emissionsPerEpochREPPO** `number` *required*

New REPPO emission rate per epoch.

**txHash** `string` *required*

Transaction hash of the on-chain update.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## Update primary token emissions per epoch

```
POST /me/subnets/{id}/emissions-per-epoch/primary-token
```

Updates the amount of the primary token emitted to curators per epoch in this datanet.

**Auth:** Privy cookie

### Path parameters

**id** `string` *required*

The datanet's internal ID.

### Request body

**subnetId** `string` *required*

The datanet's internal ID.

**emissionsPerEpochPrimaryToken** `number` *required*

New primary token emission rate per epoch.

**txHash** `string` *required*

Transaction hash of the on-chain update.

**Response `200`**

```json theme={null}
{
  "data": { "success": true }
}
```

***

## List public datanets

```
GET /public/subnets
```

Returns all active public datanets. No authentication required. Supports pagination and search.

### Query parameters

**page** `integer`

Page number. Minimum `1`. Default `1`.

**limit** `integer`

Number of results per page. Minimum `1`. Default `10`.

**search** `string`

Free-text search term filtered against datanet name and description.

**Response `200`**

```json theme={null}
{
  "data": {
    "subnets": [
      {
        "id": "subnet_01hw9k2mxvfg3q4r5t6y7u8i",
        "subnetName": "AI Research Papers",
        "subnetDescription": "A curated datanet for AI research paper summaries.",
        "thumbnailUrl": null,
        "nativeTokenAddress": "0x1234567890abcdef1234567890abcdef12345678",
        "nativeTokenSymbol": "AITKN",
        "nativeTokenDecimals": 18,
        "tokenId": 7,
        "accessFeeREPPO": 5,
        "emissionsPerEpochREPPO": 100,
        "emissionsPerEpochPrimaryToken": 500,
        "status": "active",
        "upVoteVolume": 4820,
        "downVoteVolume": 310,
        "onboardingPublishers": "Submit concise summaries of peer-reviewed AI papers.",
        "onboardingVoters": "Evaluate summaries for accuracy, clarity, and relevance.",
        "createdByUserId": "user_abc123"
      }
    ]
  }
}
```

### Example

```bash theme={null}
curl "https://reppo.ai/api/v1/public/subnets?page=1&limit=20&search=AI"
```

***

## Get a public datanet by ID

```
GET /public/subnets/{id}
```

Returns a single public datanet by its internal ID. No authentication required.

### Path parameters

**id** `string` *required*

The datanet's internal ID.

**Response `200`**

```json theme={null}
{
  "data": {
    "subnet": {
      "id": "subnet_abc123",
      "subnetName": "Base DeFi Research",
      "subnetDescription": "A curated datanet for high-signal DeFi research on Base.",
      "thumbnailUrl": null,
      "nativeTokenAddress": "0x1234567890abcdef1234567890abcdef12345678",
      "nativeTokenSymbol": "DEFI",
      "nativeTokenDecimals": 18,
      "tokenId": 3,
      "accessFeeREPPO": 10,
      "emissionsPerEpochREPPO": 100,
      "emissionsPerEpochPrimaryToken": 500,
      "status": "active",
      "upVoteVolume": 8200,
      "downVoteVolume": 410,
      "onboardingPublishers": "Submit original DeFi analysis with verifiable on-chain references.",
      "onboardingVoters": "Vote on quality and accuracy of DeFi research submissions.",
      "createdByUserId": "user_abc123"
    }
  }
}
```

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/public/subnets/subnet_abc123
```

***

## Subnet schema

The `Subnet` object is returned by all datanet endpoints.

**id** `string` *required*

Internal datanet ID.

**subnetName** `string` *required*

Display name of the datanet.

**subnetDescription** `string` *required*

Description of the datanet's focus and curation criteria.

**thumbnailUrl** `string | null`

URL to the datanet thumbnail image.

**nativeTokenAddress** `string` *required*

Contract address of the primary token.

**nativeTokenSymbol** `string` *required*

Ticker symbol of the primary token.

**nativeTokenDecimals** `integer` *required*

Decimal precision of the primary token.

**tokenId** `integer | null`

On-chain token ID assigned after the datanet is published. `null` while in draft status.

**accessFeeREPPO** `number` *required*

Fee in REPPO required to access this datanet.

**emissionsPerEpochREPPO** `number` *required*

REPPO emitted to curators per epoch.

**emissionsPerEpochPrimaryToken** `number` *required*

Primary token emitted to curators per epoch.

**status** `string` *required*

Current status of the datanet (e.g., `draft`, `active`).

**upVoteVolume** `number` *required*

Cumulative up-vote volume across all pods in this datanet.

**downVoteVolume** `number` *required*

Cumulative down-vote volume across all pods in this datanet.

**onboardingPublishers** `string` *required*

Onboarding instructions for publishers.

**onboardingVoters** `string` *required*

Onboarding instructions for voters.

**createdByUserId** `string` *required*

Internal ID of the user who created this datanet.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.