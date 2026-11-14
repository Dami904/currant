> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Amplifi Staking API Endpoint

> Record Amplifi staking positions for a specific datanet on the Reppo platform after submitting and confirming the on-chain staking transaction on Base.

Amplifi staking is a mechanism that lets token holders direct additional yield to a specific datanet by staking REPPO alongside it. This differs from curation staking (veREPPO locking): curation staking locks REPPO to earn voting power across the protocol, while Amplifi staking targets a single datanet to amplify its reward pool and signal support for that datanet's ecosystem.

After submitting the Amplifi stake transaction on Base, call this endpoint to record the position in the Reppo platform database.

***

## Create an Amplifi stake record

```
POST /stakes/amplifi
```

Records an Amplifi staking position for the authenticated user. You must submit the on-chain staking transaction on Base before calling this endpoint and include the resulting transaction hash.

**Auth:** Privy cookie

### Request body

**amount** `string` *required*

The amount staked, expressed as a decimal string (e.g., `"1000.5"`). Using a string preserves precision for large token amounts.

**subnetId** `string` *required*

Internal ID of the datanet you are staking into.

**txHash** `string` *required*

Transaction hash of the on-chain Amplifi stake transaction confirmed on Base.

**Response `201`**

```json theme={null}
{
  "data": {
    "id": "stake_abc123"
  }
}
```

### Example

```bash theme={null}
curl -X POST https://reppo.ai/api/v1/stakes/amplifi \
  -H "Cookie: privy-token=<your-privy-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "500.0",
    "subnetId": "subnet_abc123",
    "txHash": "0x789def..."
  }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.