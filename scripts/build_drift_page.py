"""Build the public drift pages from the data files in docs/drift/.

Offline and deterministic. Every quote is re-checked, verbatim, against the committed snapshot
pages (the same rule as everything else in Currant: the data file proposes, this code checks), and
each page accepts only quotes from its own vendor's hosts, so an item cannot be filed under the
wrong vendor.

    python scripts/build_drift_page.py           # rewrites every page in docs/drift/
    python scripts/build_drift_page.py --check   # exits 1 if a page is not what its data builds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
DRIFT = ROOT / "docs" / "drift"


class Source(NamedTuple):
    data: Path
    page: Path
    title: str
    hosts: tuple[str, ...]


REPPO = Source(
    DRIFT / "reppo-eval-api.json",
    DRIFT / "REPPO_EVAL_API.md",
    "Reppo Evaluation API: where the documentation disagrees with itself",
    ("https://docs.reppo.ai/", "https://eval.reppo.xyz/"),
)
OPENSERV = Source(
    DRIFT / "openserv-docs.json",
    DRIFT / "OPENSERV_DOCS.md",
    "OpenServ and SERV: where the documentation disagrees with itself",
    ("https://docs.openserv.ai/",),
)
SOURCES = (REPPO, OPENSERV)
# Kept for callers that only build the Reppo page.
DATA = REPPO.data
PAGE = REPPO.page
REPORTED_HOSTS = REPPO.hosts
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


def check_side(snapshots: Path, side: dict[str, Any], hosts: tuple[str, ...]) -> None:
    url = side["url"]
    if not url.startswith(hosts):
        raise ValueError(f"{url} is not a reported host")
    for date in side["snapshots"]:
        if side["quote"] not in page_text(snapshots, date, url):
            raise ValueError(
                f"quote not found verbatim in {url} (snapshot {date}): {side['quote']!r}"
            )


def build(data: dict[str, Any], snapshots: Path, source: Source = REPPO) -> str:
    out = [
        f"# {source.title}",
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
        if not found and kind != "conflict":
            continue
        out.append(f"## {label} ({len(found)})")
        out.append("")
        for finding in found:
            out.append(f"### {finding['title']}")
            out.append("")
            for side in finding["sides"]:
                check_side(snapshots, side, source.hosts)
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
    stale = False
    for source in SOURCES:
        data = json.loads(source.data.read_text(encoding="utf-8"))
        text = build(data, ROOT / "snapshots", source)
        name = source.page.relative_to(ROOT).as_posix()
        if args.check:
            exists = source.page.exists()
            current = (
                source.page.read_text(encoding="utf-8").replace("\r\n", "\n") if exists else ""
            )
            if current != text:
                print(f"{name} is out of date", file=sys.stderr)
                stale = True
            continue
        source.page.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {name}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
