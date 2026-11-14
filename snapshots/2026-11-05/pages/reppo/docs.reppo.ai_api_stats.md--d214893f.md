> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Network Stats API — REPPO Protocol Metrics

> Query REPPO network-wide metrics and per-datanet statistics including total value locked, active pods, emissions rates, fee totals, and token price.

The stats endpoints expose aggregated metrics about the REPPO protocol: total value locked, active datanets, fee distributions, epoch configuration, and the current REPPO price in USD. A public version of the network summary is available without authentication; the protected versions require a stats bearer token (`REPPO_STATS_API_KEY`).

***

## Get network stats (public)

```
GET /stats
```

Returns a snapshot of high-level REPPO network metrics. No authentication required.

> [!NOTE]
>
> This endpoint is currently available without authentication. Use the protected `GET /stats/summary` endpoint for production integrations where you need a stable, authenticated version of these metrics. Response values in examples below are illustrative — live values will differ.

**Response `200`**

```json theme={null}
{
  "data": {
    "totalPods": 1420,
    "totalActiveSubnets": 18,
    "totalSubnetFees": 52300.75,
    "totalSubnetFeesBurnt": 12400.0,
    "totalSubnetFeesAccumulatedToPerformancePool": 18000.0,
    "totalSubnetFeesLocked": 21900.75,
    "epochLengthSeconds": 172800,
    "governanceLocked": 3200000.0,
    "communityLocked": 1800000.0,
    "lastUpdatedAt": "2025-04-24T00:00:00Z",
    "reppoPriceUSD": 0.042,
    "totalReppoLocked": 5000000.0,
    "totalUsers": 8400,
    "totalLocks": 2100,
    "averageLockedPerUser": 595.24,
    "activeSubnetIds": [
      { "id": "subnet_abc123" },
      { "id": "subnet_def456" }
    ]
  }
}
```

### Response fields

**data.totalPods** `integer` *required*

Total number of pods minted across all datanets.

**data.totalActiveSubnets** `integer` *required*

Number of currently active datanets.

**data.totalSubnetFees** `number` *required*

Cumulative datanet fees collected across the protocol, in REPPO.

**data.totalSubnetFeesBurnt** `number` *required*

Portion of collected datanet fees that have been burned.

**data.totalSubnetFeesAccumulatedToPerformancePool** `number` *required*

Portion of collected fees directed to the performance reward pool.

**data.totalSubnetFeesLocked** `number` *required*

Portion of collected fees that have been locked.

**data.epochLengthSeconds** `integer` *required*

Duration of a single epoch in seconds.

**data.governanceLocked** `number` *required*

Total REPPO locked by governance participants.

**data.communityLocked** `number` *required*

Total REPPO locked by community participants.

**data.lastUpdatedAt** `string (date-time)` *required*

ISO 8601 timestamp of the last stats update.

**data.reppoPriceUSD** `number` *required*

Current REPPO token price in USD.

**data.totalReppoLocked** `number` *required*

Total REPPO locked across all lock positions protocol-wide.

**data.totalUsers** `integer` *required*

Total number of registered users on the platform.

**data.totalLocks** `integer` *required*

Total number of active veREPPO lock positions.

**data.averageLockedPerUser** `number` *required*

Average REPPO locked per user across all lock holders.

**data.activeSubnetIds** `array` *required*

Array of objects, each containing an `id` string for each active datanet.

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/stats
```

***

## Get network stats (protected)

```
GET /stats/summary
```

Returns the same network summary as `GET /stats` but requires authentication. Use this endpoint in production integrations where you need a stable, auth-gated version of the metrics.

**Auth:** Stats bearer token (`REPPO_STATS_API_KEY`)

```bash theme={null}
curl https://reppo.ai/api/v1/stats/summary \
  -H "Authorization: Bearer <REPPO_STATS_API_KEY>"
```

The response shape is identical to `GET /stats`.

***

## Get datanet stats

```
GET /stats/subnets/{id}
```

Returns detailed statistics for a single datanet, including vote history, emission rates, fee collection estimates, and access counts.

**Auth:** Stats bearer token (`REPPO_STATS_API_KEY`)

### Path parameters

**id** `string` *required*

The internal ID of the datanet.

**Response `200`**

```json theme={null}
{
  "data": {
    "id": "subnet_abc123",
    "tokenId": 7,
    "subnetName": "AI Research Papers",
    "subnetDescription": "Curated summaries of peer-reviewed AI research.",
    "cumulativeUpVotes": 48200.0,
    "cumulativeDownVotes": 3100.0,
    "createdAt": "2025-01-15T08:00:00Z",
    "emissionsPerEpochREPPO": 5000.0,
    "emissionsPerEpochPrimaryToken": 200.0,
    "primaryTokenSymbol": "AITKN",
    "activePodCount": 214,
    "userAccessCount": 1830,
    "reppoSeedsBySubnetOwnerAmount": 10000.0,
    "publishingFeeREPPO": 10.0,
    "estimatedTotalPublishingFeeCollectedUSD": 84.0,
    "accessFeeREPPO": 5.0,
    "estimatedTotalAccessFeeCollectedUSD": 384.3
  }
}
```

### Response fields

**data.id** `string` *required*

Internal datanet ID.

**data.tokenId** `integer` *required*

On-chain token ID for this datanet.

**data.subnetName** `string` *required*

Display name of the datanet.

**data.subnetDescription** `string` *required*

Description of the datanet's focus.

**data.cumulativeUpVotes** `number` *required*

Total weighted up-vote volume accumulated across all pods and epochs in this datanet.

**data.cumulativeDownVotes** `number` *required*

Total weighted down-vote volume accumulated across all pods and epochs in this datanet.

**data.createdAt** `string (date-time)` *required*

ISO 8601 timestamp of when the datanet was created.

**data.emissionsPerEpochREPPO** `number` *required*

REPPO emitted to curators per epoch.

**data.emissionsPerEpochPrimaryToken** `number` *required*

Primary token emitted to curators per epoch.

**data.primaryTokenSymbol** `string` *required*

Ticker symbol of the primary token.

**data.activePodCount** `integer` *required*

Number of currently active pods in this datanet.

**data.userAccessCount** `integer` *required*

Total number of user access events recorded for this datanet.

**data.reppoSeedsBySubnetOwnerAmount** `number` *required*

Amount of REPPO seeded into this datanet by its owner.

**data.publishingFeeREPPO** `number` *required*

Current pod publishing fee in REPPO.

**data.estimatedTotalPublishingFeeCollectedUSD** `number` *required*

Estimated cumulative USD value of all publishing fees collected, based on current REPPO price.

**data.accessFeeREPPO** `number` *required*

Current access fee in REPPO.

**data.estimatedTotalAccessFeeCollectedUSD** `number` *required*

Estimated cumulative USD value of all access fees collected, based on current REPPO price.

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/stats/subnets/subnet_abc123 \
  -H "Authorization: Bearer <REPPO_STATS_API_KEY>"
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.