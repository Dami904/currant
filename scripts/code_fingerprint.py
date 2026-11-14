"""Print one SHA-256 over the code that produces results: the package, its viewer, and the locked
dependencies. Line endings are normalised, so a Windows and a Linux checkout agree.

Put the value in the freeze note (`currant eval-freeze --note "code <fingerprint>"`): anyone can
later rerun this script on the committed tree and check that the held-out results came from the
code that existed when the answers were unlocked.

    uv run python scripts/code_fingerprint.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fingerprint(root: Path = ROOT) -> tuple[int, str]:
    files = sorted(
        [
            *root.glob("src/currant/**/*.py"),
            *root.glob("src/currant/web/*"),
            root / "pyproject.toml",
            root / "uv.lock",
        ]
    )
    digest = hashlib.sha256()
    for path in files:
        data = path.read_bytes().replace(b"\r\n", b"\n")
        line = f"{path.relative_to(root).as_posix()}\0{hashlib.sha256(data).hexdigest()}\n"
        digest.update(line.encode())
    return len(files), digest.hexdigest()


if __name__ == "__main__":
    count, value = fingerprint()
    print(f"{count} files; code fingerprint sha256: {value}")
