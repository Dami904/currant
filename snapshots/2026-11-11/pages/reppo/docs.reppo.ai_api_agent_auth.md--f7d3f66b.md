> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Wallet Authentication for the Agent API

> Two-step EIP-191 wallet authentication for the Reppo Agent API — request a nonce, sign it with your wallet, and receive a 24-hour session token.

The Agent API uses a two-step wallet authentication flow based on EIP-191 `personal_sign`. You first request a nonce tied to your wallet address, sign the returned message client-side, then submit the signature to receive a session token. Both steps use the Chat Server base URL (`https://api.reppo.xyz`) and do not require an existing token.

## Step 1 — Request a nonce

`POST https://api.reppo.xyz/auth/nonce`

Send your wallet address to receive a unique nonce and a pre-formatted message to sign. The nonce expires after **5 minutes**.

### Request body

**walletAddress** `string` *required*

Your Ethereum wallet address. Must be `0x`-prefixed and 40 hex characters. Pattern: `^0x[a-fA-F0-9]{40}$`.

### Response

**nonce** `string`

A UUID identifying this auth attempt. Pass this value to `/auth/verify`.

**message** `string`

The exact string you must sign with your wallet using `personal_sign` (EIP-191).

### Errors

| Status | Meaning |
| - | - |
| `400` | Missing or malformed `walletAddress` |
| `429` | Rate limit exceeded |

### Example

```bash theme={null}
curl --request POST \
  --url https://api.reppo.xyz/auth/nonce \
  --header 'Content-Type: application/json' \
  --data '{
    "walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
  }'
```

```json theme={null}
{
  "nonce": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Sign this message to authenticate with Reppo.\n\nNonce: a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

## Step 2 — Verify the signature

`POST https://api.reppo.xyz/auth/verify`

Submit your wallet address, the signature produced by signing the message from step 1, and the nonce. A valid signature returns a 24-hour session token.

### Request body

**walletAddress** `string` *required*

The same wallet address you passed to `/auth/nonce`. Pattern: `^0x[a-fA-F0-9]{40}$`.

**signature** `string` *required*

The EIP-191 `personal_sign` signature of the `message` string returned by `/auth/nonce`.

**nonce** `string` *required*

The UUID returned by `/auth/nonce`. Must not be expired (5-minute window).

### Response

**token** `string`

A session token valid for 24 hours. Pass this as `Authorization: Bearer <token>` on all subsequent authenticated requests.

**walletAddress** `string`

The authenticated wallet address in lowercase.

### Errors

| Status | Meaning |
| - | - |
| `400` | Missing fields or malformed request |
| `401` | Signature does not match the wallet address, or nonce has expired |
| `429` | Rate limit exceeded |

### Example

```bash ethers.js (Node.js) theme={null}
# 1. Fetch the nonce and message
NONCE_RESP=$(curl -s --request POST \
  --url https://api.reppo.xyz/auth/nonce \
  --header 'Content-Type: application/json' \
  --data '{"walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"}')

MESSAGE=$(echo $NONCE_RESP | jq -r '.message')
NONCE=$(echo $NONCE_RESP | jq -r '.nonce')

# 2. Sign the message with ethers.js (run in Node.js)
# const { ethers } = require("ethers");
# const wallet = new ethers.Wallet(PRIVATE_KEY);
# const signature = await wallet.signMessage(MESSAGE);

# 3. Submit the signature
curl --request POST \
  --url https://api.reppo.xyz/auth/verify \
  --header 'Content-Type: application/json' \
  --data "{
    \"walletAddress\": \"0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18\",
    \"signature\": \"<signature>\",
    \"nonce\": \"$NONCE\"
  }"
```

```bash cast (Foundry) theme={null}
# 1. Fetch the nonce and message
NONCE_RESP=$(curl -s --request POST \
  --url https://api.reppo.xyz/auth/nonce \
  --header 'Content-Type: application/json' \
  --data '{"walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"}')

MESSAGE=$(echo $NONCE_RESP | jq -r '.message')
NONCE=$(echo $NONCE_RESP | jq -r '.nonce')

# 2. Sign the message with cast
SIGNATURE=$(cast wallet sign --private-key $PRIVATE_KEY "$MESSAGE")

# 3. Submit the signature
curl --request POST \
  --url https://api.reppo.xyz/auth/verify \
  --header 'Content-Type: application/json' \
  --data "{
    \"walletAddress\": \"0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18\",
    \"signature\": \"$SIGNATURE\",
    \"nonce\": \"$NONCE\"
  }"
```

```json theme={null}
{
  "token": "eyJ...",
  "walletAddress": "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
}
```

> [!NOTE]
>
> The session token expires after **24 hours**. Include it on all subsequent authenticated requests as `Authorization: Bearer <token>`. When it expires, repeat the nonce → verify flow to obtain a fresh token.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.