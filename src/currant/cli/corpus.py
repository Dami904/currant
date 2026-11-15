"""Commands that fetch and check the crawled docs, and report which keys are set."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import httpx

from currant import __version__
from currant.cli._common import (
    USER_AGENT,
    valid_date,
)
from currant.config import (
    SECRET_NAMES,
    DotenvError,
    all_secret_status,
    dotenv_names,
)
from currant.crawl.config import ConfigError, load_config
from currant.crawl.runner import run_crawl
from currant.crawl.snapshot import LOG_NAME, SnapshotError, sha256_hex, verify_snapshot
from currant.obs import JsonLogger, utc_now


def cmd_crawl(args: argparse.Namespace) -> int:
    snapshot_date: str = args.date or utc_now().date().isoformat()
    if not valid_date(snapshot_date):
        print(f"--date must be a real date like 2026-11-05, got {snapshot_date!r}", file=sys.stderr)
        return 2
    try:
        corpora = load_config(args.config)
        config_sha256 = sha256_hex(args.config.read_bytes())
    except (ConfigError, OSError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.corpus:
        known = {c.name for c in corpora}
        unknown = sorted(set(args.corpus) - known)
        if unknown:
            print(f"unknown corpus: {', '.join(unknown)} (known: {sorted(known)})", file=sys.stderr)
            return 2
        # --corpus selects; anything not named is switched off for this run (its earlier
        # records in the snapshot are kept untouched).
        corpora = [replace(c, enabled=c.name in args.corpus) for c in corpora]

    snapshot_dir: Path = args.out / snapshot_date
    headers = {"User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain;q=0.9, */*;q=0.1"}
    timeout = httpx.Timeout(20.0, connect=10.0)

    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        with (
            (snapshot_dir / LOG_NAME).open("a", encoding="utf-8") as log_file,
            httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as client,
        ):
            logger = JsonLogger(file=log_file)
            logger.info("crawl_start", snapshot_date=snapshot_date, version=__version__)
            summary = run_crawl(
                corpora,
                out_root=args.out,
                snapshot_date=snapshot_date,
                config_sha256=config_sha256,
                client=client,
                logger=logger,
                refresh=args.refresh,
                allow_truncation=args.allow_truncation,
                delay=args.delay,
                max_attempts=args.max_attempts,
            )
            logger.info(
                "crawl_done",
                corpus_hash=summary.manifest["corpus_hash"],
                counts=summary.manifest["counts"],
                complete=summary.manifest["complete"],
                problems=summary.problems,
            )
    except (SnapshotError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    manifest = summary.manifest
    print(f"snapshot:    {snapshot_dir}")
    print(f"pages:       {manifest['counts']}")
    print(f"corpus_hash: {manifest['corpus_hash']}")
    print(f"complete:    {'yes' if manifest['complete'] else 'NO'}")
    for name, detail in manifest["truncated"].items():
        print(
            f"WARNING: page cap reached for {name}: kept {detail['kept']} of {detail['found']}; "
            f"dropped {len(detail['dropped'])} (listed in the manifest)"
        )
    if summary.problems:
        print(f"{summary.problems} item(s) need attention; see {snapshot_dir / LOG_NAME}")
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    problems = verify_snapshot(args.snapshot, allow_unreconciled=args.allow_unreconciled)
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"{len(problems)} problem(s) in {args.snapshot}")
        return 1
    print(f"OK {args.snapshot}")
    return 0


def cmd_secrets(args: argparse.Namespace) -> int:
    """Presence, source and length only: enough to debug a setup, never a value or a prefix."""
    try:
        statuses = all_secret_status(dotenv_path=args.dotenv)
        found = dotenv_names(args.dotenv)
    except DotenvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for status in statuses:
        if status.source is None:
            print(f"{status.name:<20} NOT SET")
        else:
            alias = f" as {status.found_as}" if status.found_as != status.name else ""
            print(f"{status.name:<20} set ({status.source}{alias}, {status.length} chars)")
    used = {name for status in statuses if status.found_as for name in (status.found_as,)}
    others = [name for name in found if name not in SECRET_NAMES and name not in used]
    if others:
        print(f"other names in {args.dotenv} (not used by Currant): {', '.join(others)}")
    return 0
