"""Export what Currant verified on the crawled documentation, for the site's lineage page.

    python -m uv run python scripts/build_lineage.py          # writes site/src/lineage/lineage.json
    python -m uv run python scripts/build_lineage.py --check  # exits 1 if the file is stale

Reads the local claim stores (`data/*.db`, git-ignored), so only a machine that holds them can
rebuild or `--check` the file. CI builds the site from the committed JSON, and
`tests/test_lineage.py` re-checks its OpenServ and Reppo quotes against the committed snapshots.
Every quote is re-checked verbatim before writing; one that no longer matches stops the build.

Every relation shown carries a reviewed verdict (default-deny, `currant.lineage.apply_reviews`):
- OpenServ and Reppo: only findings already published through `scripts/build_drift_page.py`
  (`docs/drift/`), with that page's verdict and note. Anything else is held back (CLAUDE.md:
  sponsor drift is published only through the drift page).
- Stripe: the hand review in docs/LIMITATIONS.md ("A second vendor's documentation"). The user
  decided on 2026-11-18 that these Stripe quotes may be published.

Not shown: the Kite corpus. Its 33 verified contradictions are almost all dated changelog entries
the detector could not order (docs/LIMITATIONS.md "A third documentation site").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from currant.lineage import LINEAGE_VERSION, LineageError, Source, apply_reviews, export
from currant.store import ClaimStore

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "src" / "lineage" / "lineage.json"
DRIFT = ROOT / "docs" / "drift"
REPO = "https://github.com/Dami904/currant/blob/main/"
STRIPE_REVIEW = (
    REPO + "docs/LIMITATIONS.md#a-second-vendors-documentation-stripe-public-trial-2026-11-12"
)
SOURCES = (
    (ROOT / "data" / "currant.db", Source("OpenServ and Reppo", 7)),  # relate-v1, latest run
    (ROOT / "data" / "currant.db", Source("OpenServ and Reppo, between crawls", 9)),  # crawl-diff
    (ROOT / "data" / "stripe2.db", Source("Stripe", 2)),  # relate-v1
)
# OpenServ and Reppo relation -> (drift page, finding id); verdict and note come from that page.
FROM_DRIFT = {
    "cc331dae2f14eebe4500f09e4bc075ca1ebda26db300d0614ef2e7e6d018cf33": ("reppo-eval-api", "cost"),
    "a256ea7edfc7c80710985de23444e83958ba71da9693d7bd638a8be55cde37f5": (
        "reppo-eval-api",
        "signup-bonus",
    ),
    "3d05bd7731bab54f9a19473ad47c87a6bc2a9c2717c1e6c65fd865ea54a5efd5": (
        "reppo-eval-api",
        "peer-cap",
    ),
    "135beb35690217d386b698e7915a6bc447f8047293f6d28f2d351fcfad0fb99e": (
        "reppo-eval-api",
        "attachment-price",
    ),
    "4e2d24aea0cbe5509dab1c37e4a583afb1588a05c44ba40c835c8b5844608285": (
        "reppo-eval-api",
        "settlement-window",
    ),
    "a76e1df62d8ba9901137012bde849bee4e1e5370910bd7f9e6a0397cbe946575": (
        "openserv-docs",
        "default-port",
    ),
    # the same 3 against 5 on the overview page
    "19fa67cbd299cc3035f84275adf5b2edcf339c7b00bbd613792b6ed76c0e122a": (
        "reppo-eval-api",
        "peer-cap",
    ),
    # crawl-diff run 9
    "1b56b08b69661b7afdac9af24ccf8f5708a340b2ecec5f62ac23c81cc5fdceeb": (
        "reppo-eval-api",
        "decision-values",
    ),
}
# Verified relations kept off the page (none today): add one here, rather than a review, when
# it is not a published drift finding yet.
HELD: frozenset[str] = frozenset()
_REPEATED = (
    "Dated release notes repeat one sentence (set the version header to that release). The "
    "detector ordered the version strings by date, but each note is right for its own release."
)
STRIPE = {
    "4eb576147e64735806bd0e971ffc0873bda1bb26a7be190f88af4dad709a1c88": {
        "verdict": "genuine",
        "note": "A real stale value for an agent: an old preview version string against the page "
        "that states the current version. The release note is correctly dated, so it is not a "
        "documentation error.",
    },
    "66ff9aa46f443a7daf366b6784bfd969d224b7c6bb5ffe157b37b9a0b8555b3b": {
        "verdict": "false-positive",
        "note": _REPEATED,
    },
    "8e3b879389852b1fe86fe50cf036fe40530f2a8c04ebd70d2eb98832d1b2890d": {
        "verdict": "false-positive",
        "note": _REPEATED,
    },
    "99310a2a2a495b30ff49baaa1097c98e10ff3356046c03ff23dea3ccbc83b72f": {
        "verdict": "false-positive",
        "note": _REPEATED,
    },
    "79447e2fa0e660f85396e85120357cada106577fcf3cf6263f8fa5b28f51d63a": {
        "verdict": "not-a-conflict",
        "note": "Wording, not a conflict: two ways of describing the same wait for delayed "
        "payment methods.",
    },
}


def reviews() -> dict[str, dict[str, str]]:
    out = {rid: {**r, "source": STRIPE_REVIEW} for rid, r in STRIPE.items()}
    findings: dict[str, dict[str, dict[str, str]]] = {}
    for page in {p for p, _ in FROM_DRIFT.values()}:
        data = json.loads((DRIFT / f"{page}.json").read_text(encoding="utf-8"))
        findings[page] = {f["id"]: f for f in data["findings"]}
    for rid, (page, finding) in FROM_DRIFT.items():
        f = findings[page].get(finding)
        if f is None:
            raise LineageError(f"docs/drift/{page}.json no longer has the finding {finding!r}")
        md = page.upper().replace("-", "_") + ".md"
        out[rid] = {"verdict": f["kind"], "note": f["note"], "source": f"{REPO}docs/drift/{md}"}
    return out


def build() -> str:
    for path, _ in SOURCES:
        if not path.exists():
            raise LineageError(
                f"{path.relative_to(ROOT)} is missing: the lineage can only be rebuilt where the "
                "local claim stores exist (the site uses the committed JSON)"
            )
    review = reviews()
    corpora = []
    for path, source in SOURCES:
        with ClaimStore(path) as store:
            corpus = apply_reviews(export(store, source), review, HELD)
        if corpus["supersedes"] or corpus["contested"]:
            corpora.append(corpus)
    data = {
        "version": LINEAGE_VERSION,
        "built_by": "scripts/build_lineage.py",
        "not_shown": "Kite: 33 contradictions, almost all changelog history the detector could "
        "not order; see docs/LIMITATIONS.md",
        "corpora": corpora,
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    try:
        text = build()
    except LineageError as e:
        print(f"lineage: {e}", file=sys.stderr)
        return 1
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(
                f"{OUT.relative_to(ROOT)} is stale: run scripts/build_lineage.py", file=sys.stderr
            )
            return 1
        print("lineage OK")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
