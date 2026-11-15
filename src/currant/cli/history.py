"""Commands over Currant's own observation history: crawl-diff supersession and as-of views."""

from __future__ import annotations

import argparse
import sys

from currant.cli._common import open_existing, valid_date
from currant.crawldiff import as_of, run_crawl_diff
from currant.store import StoreError


def cmd_crawl_diff(args: argparse.Namespace) -> int:
    try:
        store = open_existing(args.db)
        summary = run_crawl_diff(store, args.old_run, args.new_run)
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"relate run:   {summary.run_id}  (crawl_diff, no model)")
    print(f"changed:      {summary.changed_pages} pages between the two snapshots")
    print(f"superseded:   {summary.verified} verified, {summary.refused} refused by the database")
    for pair in summary.pairs:
        print(f"  {pair.url}")
        print(f"    was: {pair.older.quote}")
        print(f"    now: {pair.newer.quote}")
    return 0


def cmd_as_of(args: argparse.Namespace) -> int:
    if not valid_date(args.date):
        print(f"--date must be a real date like 2026-11-05, got {args.date!r}", file=sys.stderr)
        return 2
    try:
        store = open_existing(args.db)
        view = as_of(store, args.url, args.date)
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if view.version_date is None:
        print(f"no snapshot on or before {args.date} has {args.url}")
        return 1
    print(f"{args.url} as of {args.date}:")
    print(f"  latest version seen: {view.version_date} (document {view.doc_id})")
    if not view.changes:
        print("  no verified crawl-diff change on this page")
    for change in view.changes:
        when = "before" if change.seen_new <= args.date else "after"
        print(
            f"  changed between {change.seen_old} and {change.seen_new} ({when} this date; the "
            "exact moment is not known):"
        )
        print(f"    was: {change.older_quote}")
        print(f"    now: {change.newer_quote}")
    return 0
