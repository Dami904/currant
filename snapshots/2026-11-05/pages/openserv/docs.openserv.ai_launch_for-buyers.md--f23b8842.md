> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# For Buyers

> How to qualify for early access and what to expect during a launch on Base and Solana.

Holding 50,000 \$SERV is your ticket to early access on every launch across both Base and Solana. The requirement is the same on both chains. The mechanics are different.

***

## How to qualify

* Hold a minimum of **50,000 \$SERV** tokens
* Tokens can be held on **Base** or **Ethereum mainnet** - balances are checked separately, not combined
* Connect your wallet to the platform before a launch begins
* Qualification is determined by a snapshot taken just before each launch

***

## Base launches

### How early access works on Base

For the first **15 minutes** after trading is enabled, only qualified \$SERV holders can purchase tokens. This window runs in parallel with the decaying burn protection described below.

### The launch sequence

When the scheduled time arrives, the on-chain deployment begins automatically and takes a few minutes:

1. ERC-20 token deployed via TokenFactory
2. Anti-sniper configuration applied
3. 5% staking allocation transferred automatically
4. Team and treasury vesting streams created via Sablier (if configured)
5. Aerodrome CL liquidity pool created
6. LP position locked for 10 years
7. Programmatic fundraising positions created (if enabled)
8. Initial seed buy to seed the pool
9. SERV holder snapshot taken
10. Trading enabled

### The decaying burn

When trading opens, every buy during the first 15 minutes triggers a burn applied to the tokens leaving the pool before they reach the buyer's wallet. The burn rate starts at 99% and decreases linearly to 0% over the 15-minute window.

* Buy at minute 0, 99% of the tokens leaving the pool are burned
* Buy at minute 7.5, roughly 50% are burned
* Buy at minute 15, the burn reaches 0% and full token amounts are delivered

The pool reserves move normally on every transaction.

The buyer receives whatever portion of the outgoing tokens survives the burn at that moment.

This creates a strong disincentive for bots to front-run the launch, since the earliest buys lose the most to the burn, while genuine early supporters who hold through the window benefit from the lower starting supply.

### Public trading

After the 15-minute SERV holder window and 15-minute decaying burn ends, all access restrictions are lifted and public trading begins.

***

## Solana launches

Solana launches use a different protection mechanism called the **Alpha Vault**. Instead of a trading window after launch, qualified \$SERV holders deposit SOL before the pool goes live. At activation, the vault executes a single atomic purchase at the launch price before any external transaction can land.

### How to participate on Solana

To be eligible for the Alpha Vault you must link your EVM wallet to your Solana wallet in the user dropdown menu on the platform. This is required before the deposit window opens.

### The full timeline

| Stage | Duration | What happens |
| - | - | - |
| Deploy | T+0 | Launch transaction lands. Pool and vault created. |
| Pre-deposit period | 3 minutes | On-chain deployment completes. Nobody can act yet. |
| Alpha Vault deposit window | 21 minutes | Qualified \$SERV holders deposit SOL. |
| Lockup period | 65 minutes | Deposits closed. Vault executes atomic buy. |
| Trading live | T+89 min | Public trading opens. |
| Claim available | T+89 min 30s | Vault participants can claim their tokens. |

The 65-minute lockup is a hard requirement of the Meteora protocol and cannot be shortened.

### Deposit limits

| Parameter | Value |
| - | - |
| Minimum \$SERV holding | 50,000 \$SERV on Base or Ethereum |
| Deposit window duration | 21 minutes |
| Per-wallet deposit cap | 3 SOL |
| Total vault cap | 400 SOL |

### What you receive

At activation, all deposited SOL is used to purchase tokens at the launch price in a single atomic transaction. Your share of tokens is proportional to your deposit relative to the total vault deposit. Any SOL that cannot be deployed is automatically returned to your wallet.

### The anti-sniper fee

For Solana launches without programmatic fundraising, an anti-sniper fee activates once public trading begins. The fee applies to every swap during the first 15 minutes of public trading and decreases each second from its starting point down to zero by the end of the window.

The earliest swaps carry the highest fee, which disincentivizes bots from front-running the launch. By the time the 15-minute window closes, the fee has decayed all the way to zero and trading proceeds with no further mechanics.

For Solana launches with programmatic fundraising, the anti-sniper fee does not apply. The launch proceeds with the Alpha Vault mechanic only.

### When can you claim

Tokens become claimable **30 seconds after trading goes live**. There is no expiry on claims; you can claim at any time after the window opens.

***

## Base vs Solana at a glance

| | Base | Solana |
| - | - | - |
| **Protection mechanism** | Decaying burn over 15 minutes | Alpha Vault atomic buy |
| **Post-launch protection** | Yes, all launches | Only for non-programmatic launches |
| **Early access requirement** | 50,000 \$SERV | 50,000 \$SERV |
| **Early access window** | First 10 minutes of trading | 21-minute pre-deposit window |
| **Time to public trading** | 2 to 6 minutes after deployment | 89 minutes after deployment |
| **Wallet linking required** | No | Yes, EVM wallet must be linked to Solana wallet |
| **Starting FDV** | \$15,000 | \$15,000 |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.