"""Build the public drift page from docs/drift/reppo-eval-api.json.

Offline and deterministic. Every quote is re-checked, verbatim, against the committed snapshot
pages (the same rule as everything else in Currant: the data file proposes, this code checks), and
only pages on the hosts that were reported to the maintainers are allowed, so an unreported
sponsor item cannot slip into the public page.

    python scripts/build_drift_page.py           # rewrites docs/drift/REPPO_EVAL_API.md
    python scripts/build_drift_page.py --check   # exits 1 if the page is not what the data builds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "drift" / "reppo-eval-api.json"
PAGE = ROOT / "docs" / "drift" / "REPPO_EVAL_API.md"
REPORTED_HOSTS = ("https://docs.reppo.ai/", "https://eval.reppo.xyz/")  # reported in issue #11
KINDS = {
    "conflict": "Conflict",
    "resolved-by-removal": "Resolved by removal (not a live conflict)",
    "not-a-conflict": "Not a conflict (detector false positive)",
}


def page_text(snapshots: Path, date: str, url: str) -> str:
    manifest = json.loads((snapshots / date / "manifest.json").read_text(encoding="utf-8"))
    for page in manifest["pages"]:
        if page.get("url") == url and page.get("path"):
            text: str = (snapshots / date / page["path"]).read_text(encoding="utf-8")
            return text
    raise ValueError(f"{url} is not in snapshot {date}")


def check_side(snapshots: Path, side: dict[str, Any]) -> None:
    url = side["url"]
    if not url.startswith(REPORTED_HOSTS):
        raise ValueError(f"{url} is not a reported host")
    for date in side["snapshots"]:
        if side["quote"] not in page_text(snapshots, date, url):
            raise ValueError(
                f"quote not found verbatim in {url} (snapshot {date}): {side['quote']!r}"
            )


def build(data: dict[str, Any], snapshots: Path) -> str:
    out = [
        "# Reppo Evaluation API: where the documentation disagrees with itself",
        "",
        data["intro"],
        "",
        "Every quote below was checked verbatim against the committed snapshot page named",
        "next to it (`snapshots/<date>/`, verifiable with `currant verify`). Whether two quotes",
        "describe the same fact is a judgement, so each finding says which it is and why.",
        "",
        f"Reported to the maintainers: {data['reported']}",
        "",
    ]
    for kind, label in KINDS.items():
        found = [f for f in data["findings"] if f["kind"] == kind]
        out.append(f"## {label} ({len(found)})")
        out.append("")
        for finding in found:
            out.append(f"### {finding['title']}")
            out.append("")
            for side in finding["sides"]:
                check_side(snapshots, side)
                out.append(f"- “{side['quote']}”  ")
                out.append(f"  {side['url']} (snapshots {', '.join(side['snapshots'])})")
            out.append("")
            out.append(finding["note"])
            out.append("")
    unknown = {f["kind"] for f in data["findings"]} - set(KINDS)
    if unknown:
        raise ValueError(f"unknown finding kind: {sorted(unknown)}")
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    text = build(data, ROOT / "snapshots")
    if args.check:
        current = PAGE.read_text(encoding="utf-8").replace("\r\n", "\n") if PAGE.exists() else ""
        if current != text:
            print("docs/drift/REPPO_EVAL_API.md is out of date", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
