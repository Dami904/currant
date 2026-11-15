"""Break each guard on purpose and check that a test notices.

CLAUDE.md promises that every guard ships with a test that fails when the guard is removed. This
script makes that a check instead of a promise: each mutant below disables one guard (a Python
check or a SQLite trigger), runs the tests that cover it, and restores the file. A mutant that the
tests do not catch fails the run. No network, no key.

    uv run python scripts/mutation_check.py          # all mutants
    uv run python scripts/mutation_check.py --list   # just list them

The list is curated, not generated: each entry is a guard the README or the threat model names.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str
    original: str
    replacement: str
    tests: tuple[str, ...]


MUTANTS = (
    Mutant(
        "trigger: a claim's quote must be the document text at its span",
        "src/currant/store_schema.py",
        "WHERE {_SLICE} IS NOT NEW.quote;",
        "WHERE 0;",
        ("tests/test_store.py",),
    ),
    Mutant(
        "trigger: relations start as proposed",
        "src/currant/store_schema.py",
        "'relations start as proposed') WHERE NEW.status != 'proposed';",
        "'relations start as proposed') WHERE 0;",
        ("tests/test_store.py",),
    ),
    Mutant(
        "trigger: relations cannot be deleted",
        "src/currant/store_schema.py",
        "BEGIN SELECT RAISE(ABORT, 'relations cannot be deleted'); END;",
        "BEGIN SELECT 1; END;",
        ("tests/test_store.py",),
    ),
    Mutant(
        "extract: the value must be written in the quote",
        "src/currant/extract.py",
        'if _squash(proposal["value_text"]) not in _squash(exact_quote):',
        "if False:",
        ("tests/test_extract.py",),
    ),
    Mutant(
        "detect: an ordering quote must be found on exactly one page",
        "src/currant/detect.py",
        "if len(hits) != 1:",
        "if not hits:",
        ("tests/test_detect.py",),
    ),
    Mutant(
        "detect: two claims with the same number are never related",
        "src/currant/detect.py",
        "and math.isclose(a.value_number, b.value_number)",
        "and False",
        ("tests/test_detect.py",),
    ),
    Mutant(
        "detect: candidate blocking keeps every pair that could reach the threshold",
        "src/currant/detect.py",
        "prefix = len(ordered) - math.floor(min_score * len(ordered)) + 1",
        "prefix = len(ordered) - math.floor(min_score * len(ordered))",
        ("tests/test_blocking.py",),
    ),
    Mutant(
        "crawl-diff: a statement still on the new page is not an edit",
        "src/currant/crawldiff.py",
        "if older.quote in new_text or newer.quote in old_text:",
        "if False:",
        ("tests/test_crawldiff.py",),
    ),
    Mutant(
        "ground: a claim's quote is re-checked against the stored text",
        "src/currant/ground.py",
        "if text[claim.start_char : claim.end_char] != claim.quote:",
        "if False:",
        ("tests/test_ground.py",),
    ),
    Mutant(
        "ground: relation evidence is re-checked against the stored text",
        "src/currant/ground.py",
        "if text[row.start_char : row.end_char] != row.quote:",
        "if False:",
        ("tests/test_ground.py",),
    ),
    Mutant(
        "ground: page text cannot imitate our context markers",
        "src/currant/ground.py",
        'text = _ANGLES.sub(lambda m: " ".join(m.group()), text)',
        "text = text",
        ("tests/test_ground.py", "tests/test_fuzz.py"),
    ),
    Mutant(
        "receipt: the receipt id must match its body",
        "src/currant/receipt.py",
        'if receipt_id(body) != receipt["receipt_id"]:',
        "if False:",
        ("tests/test_receipt.py",),
    ),
    Mutant(
        "receipt: replay must recompute the same context hash",
        "src/currant/receipt.py",
        'if regrounded.context_sha256 != receipt["context_sha256"]:',
        "if False:",
        ("tests/test_receipt.py",),
    ),
    Mutant(
        "answer: contested values must be written in the CONTESTED notice",
        "src/currant/harness/answer.py",
        "for notice in _NOTICE.findall(context):",
        "for notice in [context]:",
        ("tests/test_answer.py", "tests/test_fuzz.py"),
    ),
    Mutant(
        "proxy: with a token set, data routes deny a request without it",
        "src/currant/proxy_http.py",
        "if needs_token and not _token_matches(given_token, token):",
        "if False:",
        ("tests/test_proxy_gate.py",),
    ),
    Mutant(
        "proxy: chat calls are rate-limited per client",
        "src/currant/proxy_http.py",
        "if len(log) >= self.per_minute:",
        "if False:",
        ("tests/test_proxy_gate.py",),
    ),
    Mutant(
        "proxy: a non-loopback server needs a token",
        "src/currant/proxy_http.py",
        "if not loopback and token is None:",
        "if False:",
        ("tests/test_proxy_gate.py",),
    ),
    Mutant(
        "signing: the verifier's trusted key, not the sidecar's, decides",
        "src/currant/signing.py",
        'if str(sidecar.get("public_key", "")).lower() != trusted_public_key_hex.strip().lower():',
        "if False:",
        ("tests/test_signing.py",),
    ),
    Mutant(
        "signing: the signature must verify",
        "src/currant/signing.py",
        "trusted.verify(bytes.fromhex(signature), message(rid, signed_at))",
        "pass",
        ("tests/test_signing.py",),
    ),
    Mutant(
        "signing: a receipt whose id does not match its body is never signed",
        "src/currant/signing.py",
        'raise SigningError("the receipt id does not match its body; refusing to sign it")',
        "pass",
        ("tests/test_signing.py",),
    ),
    Mutant(
        "guardrails: pipeline code may not import the evaluation store",
        "src/currant/guardrails.py",
        "if relative.startswith(LABEL_ISOLATED) and EVALSET_IMPORT.search(text):",
        "if False:",
        ("tests/test_guardrails.py",),
    ),
)


def run(mutant: Mutant) -> bool:
    """True if the tests caught the mutant. The file is always restored."""
    path = ROOT / mutant.path
    original = path.read_bytes()
    text = original.decode("utf-8")
    count = text.count(mutant.original)
    if count != 1:
        raise SystemExit(f"{mutant.name}: the guard occurs {count} times in {mutant.path}")
    try:
        path.write_bytes(text.replace(mutant.original, mutant.replacement).encode("utf-8"))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *mutant.tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        path.write_bytes(original)
    # 1 means tests ran and failed. Anything else (a collection error, say) is not a catch.
    return result.returncode == 1


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for mutant in MUTANTS:
            print(f"{mutant.path:<34} {mutant.name}")
        return 0
    missed = []
    for mutant in MUTANTS:
        caught = run(mutant)
        print(f"{'caught' if caught else 'MISSED'}  {mutant.name}", flush=True)
        if not caught:
            missed.append(mutant.name)
    print(f"{len(MUTANTS) - len(missed)} of {len(MUTANTS)} mutants caught")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
