> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Staking Locks API — Query Wallet Positions

> Query all veREPPO lock positions for a wallet address on Base — returns the token ID and locked REPPO amount for each active lock position.

Locks represent locked REPPO positions held in the veREPPO contract on Base. When a user locks REPPO, they receive a veREPPO NFT (identified by `tokenId`) that grants voting power proportional to the locked amount and lock duration. This endpoint lets you retrieve all active lock records associated with a specific wallet address.

***

## Get lock records for a wallet

```
GET /locks/{address}
```

Returns all veREPPO lock positions for the given wallet address.

**Auth:** Privy cookie

### Path parameters

**address** `string` *required*

The wallet address to query. Must be a valid Ethereum address.

Example: `0x3650752d4DDe21C6Ed7Df6d4840E15dE48e25481`

**Response `200`**

```json theme={null}
{
  "data": {
    "locks": [
      {
        "id": "lock_001",
        "tokenId": "42",
        "amount": "1000000000000000000000"
      }
    ]
  }
}
```

### Response fields

**data.locks** `array` *required*

Array of lock objects for the wallet.

**data.locks\[].id** `string` *required*

Internal lock record ID.

**data.locks\[].tokenId** `string` *required*

On-chain veREPPO NFT token ID corresponding to this lock position.

**data.locks\[].amount** `string` *required*

Amount of REPPO locked, expressed as a raw integer string in the token's base unit (wei-equivalent).

### Example

```bash theme={null}
curl https://reppo.ai/api/v1/locks/0x3650752d4DDe21C6Ed7Df6d4840E15dE48e25481 \
  -H "Cookie: privy-token=<your-privy-token>"
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.