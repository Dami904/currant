> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# What is a Datanet on Reppo?

> Datanets are domain-specific data markets on Reppo where publishers submit content, stake-backed voters curate it, and rewards flow to top performers.

A datanet is the core organizational primitive of the Reppo protocol. Each datanet is a domain-specific market for sourcing, curating, and monetizing AI training data — think of it as a self-contained data economy with its own rules, fees, and incentives. Anyone can launch a datanet for any data domain without permission.

## What datanet owners control

When you create a datanet, you configure all of its economic and governance parameters:

| Setting | Description |
| - | - |
| **Access governance** | Who can publish content and who can vote |
| **Publishing fee** | Cost in REPPO to submit a pod to this datanet |
| **Quality thresholds** | Minimum standards content must meet for acceptance |
| **Reward mechanics** | How emissions flow to contributors and curators |
| **Native token** | The ERC-20 token on Base associated with this datanet |

## How content flows through a datanet

**1. Publisher pays the fee**

A publisher selects a datanet and pays its publishing fee in REPPO. This fee is the Sybil-resistance mechanism — submitting low-quality content at scale is economically costly.

**2. Pod becomes visible**

The submitted content (a pod) is made visible to all voters participating in that datanet.

**3. Voters allocate veREPPO**

During the current 48-hour epoch, voters distribute their veREPPO voting power toward or against the pod.

**4. Epoch closes and rewards are calculated**

At the end of the epoch, the network tallies votes and calculates reward distribution based on voting outcomes.

**5. Emissions flow to quality content**

High-quality pods that earn strong positive curation generate sustained emissions each epoch. Weak content is downranked and earns less.

## Datanet economics

Publishing fees and other revenue accumulate in the **Performance Pool** for that datanet:

| Source | Contribution to pool |
| - | - |
| Datanet creation fees | 50% |
| Publishing fees | 10% |
| Data access fees | 10% |

The Performance Pool distributes every third epoch. When it distributes:

* **80%** goes to REPPO stakers
* **20%** goes to datanet owners

Distribution across datanets is weighted by four metrics:

| Metric | Weight |
| - | - |
| [EVOF (Economic Value of Feedback)](https://docs.reppo.ai/concepts/evof.md) | 40% |
| Staked REPPO | 25% |
| Trading volume | 20% |
| Total fees collected | 15% |

> [!NOTE]
>
> The Performance Pool distributes on a fixed cadence — every third epoch. Rewards you earn between distributions accrue and pay out at the next distribution event.

## Creating a datanet

Use the `POST /me/subnets` endpoint to create a datanet draft programmatically. You will need to provide:

* Native token address (an ERC-20 contract on Base)
* Token symbol and decimals
* Datanet name and description
* Publisher and voter onboarding instructions
* Your initial fee structure

```bash theme={null}
POST /api/v1/me/subnets
```

After creating the draft, publish it on-chain using `POST /me/subnets/{id}/publish` with the transaction hash. You can update fees at any time via the fee management endpoints.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.