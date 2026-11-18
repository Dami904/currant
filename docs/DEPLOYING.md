# Deploying the site

The site (`site/`) is a static Vite build plus one Python function, the hosted receipt replay
(`site/api/replay.py`, `POST /api/replay`). It is hosted on Vercel; the Vercel project is linked
from `site/` (its Root Directory is that folder), so `site/vercel.json` and the paths in it are
relative to `site/`.

## What ships

- The static pages, built by `pnpm build` (`tsc --noEmit && vite build`) into `site/dist/`.
- `site/api/replay.py`, a thin adapter over `currant.replay_api`. Vercel installs Currant from
  `site/requirements.txt`, which pins it to one public commit, and uses Python 3.12
  (`site/.python-version`).
- `site/api/_stores/real.db` and `demo.db`, byte copies of `examples/real/store.db` and
  `examples/demo/store.db` (shipped with the function by `includeFiles` in `site/vercel.json`).

## Order of steps when the replay code changes

A commit cannot name itself, so the code and the pin land in two commits:

1. Commit the change to `src/currant` (and anything else). `scripts/check_replay_pin.py` now fails:
   the pin is behind.
2. Set the pin in `site/requirements.txt` to the full SHA of that commit, and commit that.
   `python -m uv run python scripts/check_replay_pin.py` prints `replay pin OK`.
3. Push both commits together. The pinned commit must be on GitHub before Vercel builds, or the
   install fails.
4. Deploy from `site/` (a preview first: `vercel`, then `vercel --prod` once the checks below
   pass).

CI runs the pin check in its own job (`replay-pin`, with full history).

## When the example stores change

If `examples/real/store.db` or `examples/demo/store.db` is rebuilt, copy it over the file in
`site/api/_stores/`, put its new SHA-256 (and corpus hash, if that changed) in
`currant.replay_api.HOSTED`, then follow the steps above. `tests/test_replay_api.py` fails until
the copies, hashes and corpus hashes agree.

## Checks after a deploy

On the preview URL, from the verify page or with curl:

- the preloaded real receipt replays as `REPLAYED against real.db`;
- a receipt with one field changed is `FAILED`, with its reasons;
- `GET /api/replay` is a 405 with a JSON body.

Not yet measured, to record in `docs/API_NOTES.md` on the first deploy: cold-start time, memory,
that `includeFiles` shipped the stores, that the build image could install the `git+https`
requirement, and that Vercel's Python runtime honoured `site/.python-version` (3.12).

Note: the pin check compares all of `src/currant` with the pinned commit, not only the modules the
replay uses, so any source change asks for a pin move. Stricter than needed, on purpose.
