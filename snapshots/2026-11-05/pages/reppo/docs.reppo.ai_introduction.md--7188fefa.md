> ## Documentation Index
> Fetch the complete documentation index at: https://docs.reppo.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Introduction to the Reppo Protocol

> Reppo is a decentralized protocol for sourcing and monetizing AI training data. Learn about datanets, pods, veREPPO curation, and on-chain emissions on Base.

**We're building market infrastructure for AI training data.**

Reppo lets anyone publish content to domain-specific data markets called datanets, where stake-backed voters signal quality and contributors earn REPPO emissions. Rather than purchasing raw labor hours, Reppo creates open economic competition — aligning the interests of data publishers, curators, datanet owners, and the AI teams that consume the output.

## What is an RL environment?

An RL environment defines the task, scoring function, and feedback loop used to improve a model. It is the setting where a model acts, gets evaluated, and learns. On Reppo, datanets act as market-based environments for generating and curating that learning signal.

![The RL training loop: a task prompt feeds a model, a verifier scores the attempt, and the score and gradient feed back into the model across millions of rollouts](https://mintcdn.com/reppo/fCOPJ5kcGkAxNx-v/images/rl-training-loop.jpg?fit=max\&auto=format\&n=fCOPJ5kcGkAxNx-v\&q=85\&s=d295a9a0e6675cc8a98d53cbdbfc7acf)

> "Scale AI coordinates training data pipelines with contracts. Reppo coordinates them with markets, access controls, and on-chain incentives."

By putting stake behind both contribution and curation, Reppo is designed to address the AI training data trilemma.

![The AI training data trilemma: quality, scale, and legal](https://mintcdn.com/reppo/fCOPJ5kcGkAxNx-v/images/ai-data-trilemma.png?fit=max\&auto=format\&n=fCOPJ5kcGkAxNx-v\&q=85\&s=2c9f0988b73fa1449c4ed1492ddf8dcb)

![Reppo data markets: publishers to markets to curators to models, with economic stake on both sides, prediction-market style curation, and on-chain provenance](https://mintcdn.com/reppo/fCOPJ5kcGkAxNx-v/images/reppo-data-markets.png?fit=max\&auto=format\&n=fCOPJ5kcGkAxNx-v\&q=85\&s=586e0c8af865882ef0e47838abe77cf2)

## Key concepts

**Datanets** are domain-specific prediction markets where data contributors publish work and put capital behind its quality. Each datanet defines its own rules: who can publish, what content qualifies, how fees are set, and how rewards flow.

**Pods** are the atomic data units inside a datanet — a tweet, image, video, annotation, or any media the datanet accepts. Each pod is minted as an on-chain NFT on Base and earns REPPO emissions epoch by epoch based on how well it performs in curation voting.

**veREPPO** is voting-escrow REPPO. Voters lock REPPO tokens for a chosen duration to receive veREPPO, which gives them curation authority. Larger locks and longer durations yield more voting power per token. Splitting tokens across multiple identities does not multiply power, making Sybil attacks economically ineffective.

**Epochs** are 48-hour windows during which publishers submit pods, voters allocate veREPPO, and rewards accrue. Voting power decays linearly throughout each epoch — earlier votes carry more weight — and at epoch end the network calculates emissions. The Performance Pool distributes every third epoch.

## Participants

| Role | What they do |
| - | - |
| **Publishers** | Submit content to datanets, pay a publishing fee, and earn REPPO emissions when their work is well-curated |
| **Voters** | Lock REPPO for veREPPO and allocate voting power across datanets and pods each epoch |
| **Datanet owners** | Define the rules, fees, and incentive structure of a domain-specific data market |
| **AI teams** | Access curated, high-signal datasets and preference signals from datanets |

## On-chain infrastructure

All on-chain activity runs on **Base** (chain ID `8453`). The contracts you interact with directly are:

| Contract | Address | Purpose |
| - | - | - |
| Pod Manager V2 | `0x5C563f853eb4db33005A5C1aD9290e8560254A80` | Mint pods as NFTs and claim REPPO emissions |
| Subnet Manager | `0x2629A8083065938B533b117704935D727270eE7A` | Manage Datanets |
| REPPO Token | `0xFf8104251E7761163faC3211eF5583FB3F8583d6` | ERC-20 token used for minting fees and emissions |
| USDC | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | Payment token accepted for X Agent pod mints |

> [!NOTE]
>
> Reppo is not an L1 or L2 network. It is a protocol layer built on Base.

## Explore the docs

> [card] [Why Reppo](https://docs.reppo.ai/why-reppo.md)
>
> The motivation behind Reppo and the data labor problems it sets out to fix.

> [card] [How Reppo Works](https://docs.reppo.ai/concepts/how-reppo-works.md)
>
> The system-level flow: participants, publishing, curation, and emissions.

> [card] [Datanets](https://docs.reppo.ai/concepts/datanets.md)
>
> Understand how domain-specific data markets work and how to create one.

> [card] [Pods](https://docs.reppo.ai/concepts/pods.md)
>
> Learn how to publish, mint, vote on, and claim emissions from pods.

> [card] [Votes & Curation](https://docs.reppo.ai/concepts/votes-curation.md)
>
> Stake-assured human feedback, veREPPO mechanics, and epoch voting rules.

> [card] [Orquestra](https://docs.reppo.ai/concepts/orquestra.md)
>
> Run a swarm of agents that publish and vote on your behalf, and earn rewards.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.