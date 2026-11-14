# Reppo Evaluation API: where the documentation disagrees with itself

Currant's detector flagged 7 pairs of sentences in the sponsor documentation as disagreeing (relate run 7 over the 2026-11-05 snapshot, and the same pairs came back from a wider run). 6 are on the Reppo Evaluation API pages and are listed here; 1 is on another sponsor's documentation and is not listed. A person then read each pair against both sources. Of the 6, two are live conflicts. A third live conflict (attachment size) was found by hand because the detector missed it. The rest are not live conflicts, and are shown so the detector's real precision on documentation is visible.

Every quote below was checked verbatim against the committed snapshot page named
next to it (`snapshots/<date>/`, verifiable with `currant verify`). Whether two quotes
describe the same fact is a judgement, so each finding says which it is and why.

Reported to the maintainers: https://github.com/Reppo-Labs/docs/issues/11 (opened 2026-11-12), with a fix proposed in https://github.com/Reppo-Labs/docs/pull/12.

## Conflict (3)

### Cost of a text-only evaluation: 100 credits or 440 credits

- “An evaluation costs 100 credits.”  
  https://docs.reppo.ai/api/eval/evaluations.md (snapshots 2026-11-05, 2026-11-11)
- “A text-only evaluation costs **440 credits**;”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-05, 2026-11-11)

Measured: one evaluation through the documented endpoint (2026-11-05) and one through the current endpoint (2026-11-11) were each charged `creditsCharged: 440`, which matches agents.md.

### Sign-up bonus: 1,000 credits or 22,000 credits

- “Sign-up bonus | 1,000 credits (10 evaluations)”  
  https://docs.reppo.ai/api/eval/overview.md (snapshots 2026-11-05, 2026-11-11)
- “New accounts start with **22,000 credits** (a one-time sign-up bonus).”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-05, 2026-11-11)

Whether a new account gets the larger or smaller bonus is unsettled in this repository (the console balance is the source of truth); the two pages cannot both be current.

### Largest attachment: 2 MB or 1.25 MB

- “Attachments | 1 per evaluation, up to 2 MB: PNG, JPEG, WebP, or PDF”  
  https://docs.reppo.ai/api/eval/overview.md (snapshots 2026-11-05, 2026-11-11)
- “Max 1 item, 1.25 MB each”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-05, 2026-11-11)

Found by hand: the detector missed this pair (it is its recall limit on real documentation).

## Resolved by removal (not a live conflict) (1)

### Peer assessments per evaluation: 3 or 5

- “Each evaluation accepts up to 3.”  
  https://docs.reppo.ai/api/eval/peer-assessments.md (snapshots 2026-11-05, 2026-11-11)
- “`assessmentCount` tells you how close it is to the cap of 5 — see section 7.”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-05)
- “These endpoints have been removed and now return `404`.”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-11)

In the first snapshot the two pages disagreed (3 against 5). By the second, agents.md no longer mentions a cap and lists the peer-assessment endpoints as removed, so the docs page now describes an API that no longer exists. This is the case a crawl-diff would catch (the same URL changed between two dated snapshots); Currant does not build that yet.

## Not a conflict (detector false positive) (2)

### 1,000 credits against 100 credits

- “image or PDF attached costs **1,000 credits**”  
  https://eval.reppo.xyz/agents.md (snapshots 2026-11-05, 2026-11-11)
- “Cost per evaluation | 100 credits (1¢)”  
  https://docs.reppo.ai/api/eval/overview.md (snapshots 2026-11-05, 2026-11-11)

The detector paired the price of an evaluation with an attachment (1,000) with the price of a text-only evaluation (100). They are different quantities, so this pair is not a conflict. The real conflict about the 100 is listed above.

### Settlement window: up to 24 hours or up to 1440 minutes

- “You can also give an evaluation a settlement window, from 10 minutes up to 24 hours.”  
  https://docs.reppo.ai/concepts/evaluation-api.md (snapshots 2026-11-05, 2026-11-11)
- “Settlement window | 10, 15, 30, 60, 120, 360, 720, or 1440 minutes (default 15)”  
  https://docs.reppo.ai/api/eval/overview.md (snapshots 2026-11-05, 2026-11-11)

24 hours is 1440 minutes, so the two pages agree. A false positive. (Both describe a settlement window that agents.md no longer has; that is part of issue #11.)
