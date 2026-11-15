# Snapshots

Each dated folder here is a point-in-time copy of third-party documentation, kept so that
Currant's results can be reproduced and audited against exactly the text the models saw.

**This content is not covered by this repository's MIT licence.** It was written by others,
remains theirs, and is subject to their terms. The `LICENSE` at the repository root applies to
Currant's own code and docs only.

| Folder | Sources | Fetched |
| --- | --- | --- |
| `2026-11-05/` | `docs.openserv.ai`, `docs.reppo.ai`, `eval.reppo.xyz/agents.md` | 2026-11-05 (UTC), see `manifest.json` for per-page times |
| `2026-11-11/` | the same sources (132 pages, `corpus_hash` `1ae351e60c0f…`) | 2026-11-11 (UTC) |
| `2026-11-15/` | the same sources (132 pages, `corpus_hash` `c3bb782764de…`) | 2026-11-15 (UTC) |

The Kite docs (`docs.gokite.ai`, 2026-11-15) are **not** here: two of their pages contain
`0x` + 64-hex strings the secret scanner cannot tell from wallet keys, so that snapshot stays in
the git-ignored `data/snapshots-kite/`. The extraction log `results/extract/kite-*.jsonl` is
committed and does quote Kite's pages verbatim (one quote per claim), under the same terms as
this folder.

- **Why it is committed:** a drift finding or a score is only checkable if the pages it was
  computed from are still available after the live docs change.
- **Redistribution is unchecked.** We have not verified whether those sites' terms allow
  republishing their documentation. If you are a rights holder and want something removed,
  open an issue on this repository and it will be taken out of the tree.
- **Integrity:** files are stored byte for byte as received and are hashed in `manifest.json`.
  `.gitattributes` marks this folder `-text` so git never rewrites line endings. Check a
  snapshot with `uv run currant verify snapshots/<date>`. Do not edit these files.
