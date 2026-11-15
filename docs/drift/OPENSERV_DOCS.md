# OpenServ and SERV: where the documentation disagrees with itself

Two places where the OpenServ documentation (docs.openserv.ai, which also hosts the SERV Reasoning docs) disagrees with itself. Both are minor: a stale code sample and a stale model list. The PORT pair was found by Currant's detector (relate run 4, 2026-11-05 snapshot); the DeepSeek pair was spotted by a person while reading the crawl, and the extractor captured only the changelog side of it. Both are still present in the 2026-11-15 crawl.

Every quote below was checked verbatim against the committed snapshot page named
next to it (`snapshots/<date>/`, verifiable with `currant verify`). Whether two quotes
describe the same fact is a judgement, so each finding says which it is and why.

Reported to the maintainers: not reported through a maintainer channel; published here on 2026-11-15 as minor documentation errors. The PORT conflict was also posted publicly in a Reppo evaluation on 2026-11-15 (`results/audit/reppo-conflicts-v2.jsonl`).

## Conflict (2)

### Default PORT of an agent built with the OpenServ SDK: 7380 or 7378

- “`PORT` is optional (defaults to 7380).”  
  https://docs.openserv.ai/vibecode/build-custom-agent.md (snapshots 2026-11-05, 2026-11-11, 2026-11-15)
- “| `PORT` | Server port | No | 7378 |”  
  https://docs.openserv.ai/vibecode/sdk/typescript.md (snapshots 2026-11-05, 2026-11-11, 2026-11-15)

Not measured: we did not run the SDK to see which port it binds, so this page does not say which side is right. Currant answers this question CONTESTED and quotes both values.

### SERV model list: DeepSeek V4 removed, but still listed in the quickstart

- “Grok 4.5, DeepSeek V4 Flash, DeepSeek V4 Pro, Kimi K2.6”  
  https://docs.openserv.ai/changelog/overview.md (snapshots 2026-11-05, 2026-11-11, 2026-11-15)
- “deepseek-v4-pro, deepseek-v4-flash”  
  https://docs.openserv.ai/serv-reasoning/introduction.md (snapshots 2026-11-05, 2026-11-11, 2026-11-15)
- “deepseek-v4-pro, deepseek-v4-flash”  
  https://docs.openserv.ai/serv-reasoning/sdk-migration.md (snapshots 2026-11-05, 2026-11-11, 2026-11-15)

The changelog's "Model catalog trimmed" entry (dated September 11, 2026) removes both DeepSeek V4 models, but the SERV introduction and the SDK migration guide still list their ids inside an embedded model list. Measured: the live `GET /v1/models` on 2026-11-15 listed 11 models and no DeepSeek (`results/smoke/20261115T090131Z-models.json`), so the changelog is right and the two pages are stale.
