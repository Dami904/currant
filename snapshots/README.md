# Snapshots

Each dated folder here is a point-in-time copy of third-party documentation, kept so that
Currant's results can be reproduced and audited against exactly the text the models saw.

**This content is not covered by this repository's MIT licence.** It was written by others,
remains theirs, and is subject to their terms. The `LICENSE` at the repository root applies to
Currant's own code and docs only.

| Folder | Sources | Fetched |
| --- | --- | --- |
| `2026-11-05/` | `docs.openserv.ai`, `docs.reppo.ai`, `eval.reppo.xyz/agents.md` | 2026-11-05 (UTC), see `manifest.json` for per-page times |

- **Why it is committed:** a drift finding or a score is only checkable if the pages it was
  computed from are still available after the live docs change.
- **Redistribution is unchecked.** We have not verified whether those sites' terms allow
  republishing their documentation. If you are a rights holder and want something removed,
  open an issue on this repository and it will be taken out of the tree.
- **Integrity:** files are stored byte for byte as received and are hashed in `manifest.json`.
  `.gitattributes` marks this folder `-text` so git never rewrites line endings. Check a
  snapshot with `uv run currant verify snapshots/<date>`. Do not edit these files.
