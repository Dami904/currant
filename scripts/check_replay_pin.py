"""Check that the hosted replay runs the code in this repository, not an older commit.

    python -m uv run python scripts/check_replay_pin.py

The Vercel function installs Currant from GitHub at the commit pinned in site/requirements.txt.
A commit cannot name itself, so the replay code lands in one commit and the pin moves to it in
the next (docs/DEPLOYING.md). This fails when:
- the pinned commit does not contain src/currant/replay_api.py (the pin predates the code), or
- src/currant differs between the pinned commit and HEAD (the deployed code would not be the code
  that was tested here).

It needs the full git history (CI checks out with fetch-depth 0). Exit 0 when current, 1 when not,
2 when git cannot answer.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "site" / "requirements.txt"
_PIN = re.compile(r"^currant @ git\+https://github\.com/Dami904/currant@([0-9a-f]{40})$", re.M)

Git = Callable[..., int]


def pinned_sha(requirements: Path) -> str:
    found = _PIN.findall(requirements.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise ValueError(f"{requirements}: expected exactly one pinned currant commit")
    sha: str = found[0]
    return sha


def check(sha: str, git: Git) -> list[str]:
    if git("cat-file", "-e", f"{sha}:src/currant/replay_api.py") != 0:
        return [f"the pinned commit {sha[:12]} does not contain src/currant/replay_api.py"]
    if git("diff", "--quiet", sha, "HEAD", "--", "src/currant") != 0:
        return [
            f"src/currant changed since the pinned commit {sha[:12]}: move the pin in "
            "site/requirements.txt to the commit that holds this code (docs/DEPLOYING.md)"
        ]
    return []


def _git(*args: str) -> int:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False).returncode


def main() -> int:
    try:
        sha = pinned_sha(REQUIREMENTS)
        if _git("cat-file", "-e", f"{sha}^{{commit}}") != 0:
            print(f"replay pin: commit {sha[:12]} is not in this clone (fetch-depth 0?)")
            return 2
        problems = check(sha, _git)
    except (OSError, ValueError) as exc:
        print(f"replay pin: {exc}")
        return 2
    for problem in problems:
        print(f"replay pin: {problem}")
    if problems:
        return 1
    print(f"replay pin OK: {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
