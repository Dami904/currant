"""Commands for real items and the drift report; both write under docs/private."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from currant.cli._common import (
    open_existing,
    private_out_refused,
)
from currant.drift import drift_report
from currant.evalset import EvalError, EvalStore
from currant.harness.real_items import import_worksheet, label_session, make_worksheet
from currant.store import StoreError


def cmd_real_worksheet(args: argparse.Namespace) -> int:
    if private_out_refused(args.out, args.publish):
        return 2
    try:
        store = open_existing(args.db)
        worksheet = make_worksheet(store, args.extract_run, max_items=args.max_items)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(worksheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {len(worksheet['items'])} candidate pairs to {args.out}")
    print("Fill in `verdict` for each pair you can judge (see `instructions` in the file), then:")
    print(f"  currant real-import --worksheet {args.out}")
    return 0


def cmd_real_label(args: argparse.Namespace) -> int:
    def save(worksheet: dict[str, Any]) -> None:
        temporary = args.worksheet.with_name(args.worksheet.name + ".tmp")
        temporary.write_text(
            json.dumps(worksheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, args.worksheet)  # whole or not at all

    try:
        worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
        store = open_existing(args.db)
        counts = label_session(store, int(worksheet["extract_run"]), worksheet, input, print, save)
    except (StoreError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\nstopped; every answer so far was saved")
        return 130
    print(f"\nlabelled {counts['labelled']}, skipped {counts['skipped']}, left {counts['left']}")
    print("Next: currant real-import   (then publish the commit root it prints, THEN freeze)")
    return 0


def cmd_real_import(args: argparse.Namespace) -> int:
    try:
        worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
        store = open_existing(args.db)
        run_id = int(worksheet["extract_run"])
        with EvalStore(args.evalset) as evals:
            result = import_worksheet(store, run_id, evals, worksheet)
            root = evals.commit_root()
            counts = {split: len(evals.items(split)) for split in ("dev", "test", "heldout")}
    except (StoreError, EvalError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"added {result.added} real items")
    print(f"skipped {len(result.skipped)} (no verdict, or not a conflict)")
    for problem in result.problems:
        print(f"  refused {problem}")
    print(f"items now: {counts}")
    print(f"commit root: {root}")
    print("Publish that root outside this machine BEFORE `currant eval-freeze --yes`.")
    return 1 if result.problems else 0


def cmd_drift_report(args: argparse.Namespace) -> int:
    if private_out_refused(args.out, args.publish):
        return 2
    try:
        store = open_existing(args.db)
        text = drift_report(store, args.extract_run, args.relate_run)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0
