"""Repo rules that fail the build instead of living in a README.

Run with `python -m currant.guardrails [repo_root]`. CI runs it on every push.

Rules:
1. Secret env var names (SERV_API_KEY, ...) and any read of the process environment may only
   appear in `src/currant/config.py`, so keys have exactly one entry point.
2. No secret-shaped strings anywhere in the tree (private key blocks, 0x + 64 hex, API key
   prefixes). The top-level `snapshots/` directory is skipped: it holds crawled third-party
   docs. Bare 64-hex strings are not flagged because SHA-256 hashes look identical.
3. `.gitignore` must ignore `.env`. Files named `.env` or `.env.*` are never read (except
   `.env.example`, which is committed and therefore checked).
4. HTTP clients may only be constructed in `src/currant/cli.py` or `live_*` scripts, so
   "anything that touches the network is a demo path" is enforced, not just stated.
5. No skipped / xfail tests, no type-check suppressions, no lint exemptions without a rule
   code in src/, tests/ or scripts/.

Anything that cannot be scanned (too large, not UTF-8, unreadable) is reported as a note
instead of being skipped silently.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

SECRET_ENV_NAMES = ("SERV_API_KEY", "OPENSERV_API_KEY", "REPPO_API_KEY", "WALLET_PRIVATE_KEY")
ENV_ENTRY_POINTS = frozenset({"src/currant/config.py", "src/currant/guardrails.py"})
RULE_DEFINITIONS = "src/currant/guardrails.py"  # names the patterns, so exempt from them
NETWORK_ALLOWED = frozenset({"src/currant/cli.py"})

SECRET_SHAPES = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "0x-prefixed 32-byte hex (wallet key shape)": re.compile(r"\b0x[0-9a-fA-F]{64}\b"),
    "sk- style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
}
ENV_READ = re.compile(
    r"\bos\.(?:environ|getenv)\b|\bfrom\s+os\s+import\b[^\n]*\b(?:environ|getenv)\b"
)
NETWORK_CALL = re.compile(
    r"\bhttpx\.(?:Client|AsyncClient)\(|\burlopen\(|\burllib\.request\.\w+\("
    r"|\brequests\.(?:get|post|put|delete|request|Session)\b|\bsocket\.create_connection\("
)
SKIPPED_TEST = re.compile(r"\bpytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\(")
TYPE_SUPPRESSION = re.compile(r"#\s*type:\s*ignore")
BARE_LINT_EXEMPTION = re.compile(r"#\s*noqa(?!\s*:)")

# Pipeline code must not import the evaluation store: labels never reach the pipeline. Only the
# CLI (which freezes and reports) and a future src/currant/harness/ may.
LABEL_ISOLATED = (
    "src/currant/crawl/",
    "src/currant/extract.py",
    "src/currant/store.py",
    "src/currant/store_schema.py",
    "src/currant/serv.py",
    "src/currant/config.py",
    "src/currant/detect.py",
    "src/currant/ground.py",
    "src/currant/receipt.py",
    "src/currant/llmcache.py",
    "src/currant/obs.py",
    "src/currant/retrieve.py",
    "src/currant/harness/answer.py",
    "src/currant/harness/stats.py",
)
# The item runner imports the item TYPE, so the import ban cannot cover it; it may not call a
# label accessor instead.
LABEL_FREE_FILES = (
    "src/currant/harness/run_items.py",
    "src/currant/harness/arms.py",
)
LABEL_ACCESS = re.compile(
    r"\.labels?\s*\(|\b_read_label|\bgetattr\([^)]*label|\bFROM\s+labels\b", re.IGNORECASE
)
# Notes about sponsor documentation conflicts must stay out of tracked docs until a second
# source confirms them and the maintainers are told. They live in docs/private/ (ignored).
NOT_FOR_PUBLICATION = re.compile(r"not for publication", re.IGNORECASE)
PRIVATE_DIR = "docs/private"
EVALSET_IMPORT = re.compile(
    r"^\s*(?:from\s+currant\.evalset\b|import\s+currant\.evalset\b"
    r"|from\s+currant\s+import\s+[^\n]*\bevalset\b)",
    re.MULTILINE,
)

ALWAYS_SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules"}
)
# snapshots/ is third-party text, data/ is the rebuildable claim store, dist/ and build/ are output.
TOP_LEVEL_SKIP_DIRS = frozenset({"snapshots", "data", "dist", "build"})
SKIP_FILES = frozenset({"uv.lock"})
CODE_ROOTS = ("src/", "tests/", "scripts/")
MAX_SCAN_BYTES = 1_000_000


@dataclass
class ScanResult:
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _is_private_dotenv(name: str) -> bool:
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def _files(root: Path) -> Iterator[Path]:
    for current, dirs, names in os.walk(root):
        at_top = Path(current) == root
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in ALWAYS_SKIP_DIRS and not (at_top and d in TOP_LEVEL_SKIP_DIRS)
        )
        for name in sorted(names):
            if name not in SKIP_FILES and not _is_private_dotenv(name):
                yield Path(current) / name


def scan(root: Path) -> ScanResult:
    result = ScanResult()
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        binary = False
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                result.notes.append(f"{relative}: not scanned (larger than {MAX_SCAN_BYTES} bytes)")
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # Binary (a SQLite file, say): still look for key-shaped strings in it. latin-1
                # maps every byte to a character, so nothing is lost or skipped.
                text, binary = raw.decode("latin-1"), True
        except OSError as exc:
            result.notes.append(f"{relative}: not scanned (unreadable: {exc})")
            continue

        for label, pattern in SECRET_SHAPES.items():
            if pattern.search(text):
                result.violations.append(f"{relative}: looks like a {label}")

        if binary:
            continue  # only the secret-shape scan applies to binary files
        if (
            relative.endswith(".md")
            and not relative.startswith(PRIVATE_DIR + "/")
            and NOT_FOR_PUBLICATION.search(text)
        ):
            result.violations.append(
                f"{relative}: marked 'not for publication' but tracked; move it to {PRIVATE_DIR}/"
            )

        if relative.startswith("src/") and relative not in ENV_ENTRY_POINTS:
            for name in SECRET_ENV_NAMES:
                if name in text:
                    result.violations.append(
                        f"{relative}: references {name}; only src/currant/config.py may"
                    )
            if ENV_READ.search(text):
                result.violations.append(
                    f"{relative}: reads the process environment; only src/currant/config.py may"
                )

        is_code = relative.endswith(".py") and relative.startswith(CODE_ROOTS)
        if not is_code or relative == RULE_DEFINITIONS:
            continue
        if NETWORK_CALL.search(text) and not _may_use_network(relative):
            result.violations.append(
                f"{relative}: builds an HTTP client; only src/currant/cli.py or a live_* script may"
            )
        if relative.startswith(LABEL_ISOLATED) and EVALSET_IMPORT.search(text):
            result.violations.append(
                f"{relative}: imports the evaluation store; labels must never reach the pipeline"
            )
        if relative in LABEL_FREE_FILES and LABEL_ACCESS.search(text):
            result.violations.append(
                f"{relative}: the item runner reads a label; labels must never reach the pipeline"
            )
        if SKIPPED_TEST.search(text):
            result.violations.append(f"{relative}: skipped or xfail test; fix it or delete it")
        if TYPE_SUPPRESSION.search(text):
            result.violations.append(f"{relative}: suppresses a type-check failure")
        if BARE_LINT_EXEMPTION.search(text):
            result.violations.append(f"{relative}: lint exemption without a rule code")

    gitignore = root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if ".env" not in (line.strip() for line in lines):
        result.violations.append(".gitignore: must contain a line that is exactly '.env'")
    ignored = {line.strip() for line in lines}
    if (root / PRIVATE_DIR).is_dir() and f"{PRIVATE_DIR}/" not in ignored:
        result.violations.append(
            f".gitignore: must ignore {PRIVATE_DIR}/ (private notes live there)"
        )
    return result


def _may_use_network(relative: str) -> bool:
    if relative.startswith("tests/"):
        return True  # tests only ever use httpx.MockTransport; conftest blocks real sockets
    return relative in NETWORK_ALLOWED or Path(relative).name.startswith("live_")


def check(root: Path) -> list[str]:
    return scan(root).violations


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    result = scan(root)
    for note in result.notes:
        print(f"NOT SCANNED {note}")
    for violation in result.violations:
        print(f"GUARDRAIL {violation}")
    if result.violations:
        print(f"{len(result.violations)} guardrail violation(s)")
        return 1
    print("guardrails OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
