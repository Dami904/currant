"""Entry point: parse the arguments and hand them to the command."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from currant.cli.corpus import cmd_crawl, cmd_secrets, cmd_verify
from currant.cli.evaluation import (
    cmd_eval_freeze,
    cmd_eval_root,
    cmd_make_synthetic,
    cmd_run_arms,
    cmd_run_items,
    cmd_score,
    cmd_score_arms,
)
from currant.cli.parser import build_parser
from currant.cli.pipeline import cmd_extract, cmd_ground, cmd_relate, cmd_replay, cmd_serve
from currant.cli.real import cmd_drift_report, cmd_real_import, cmd_real_label, cmd_real_worksheet
from currant.cli.reppo import (
    cmd_audit_prepare,
    cmd_audit_report,
    cmd_audit_submit,
    cmd_reppo_resolve,
    cmd_reppo_status,
)


def _tolerate_console_encoding() -> None:
    """Never crash while printing a page quote. A Windows console is often cp1252, which cannot
    show characters such as an arrow or a cent sign that real documentation contains; an
    unprintable character becomes `?` instead of an uncaught UnicodeEncodeError (seen when
    labelling real items)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _tolerate_console_encoding()
    args = build_parser().parse_args(argv)
    if args.command == "crawl":
        return cmd_crawl(args)
    if args.command == "secrets":
        return cmd_secrets(args)
    if args.command == "extract":
        return cmd_extract(args)
    if args.command == "relate":
        return cmd_relate(args)
    if args.command == "ground":
        return cmd_ground(args)
    if args.command == "replay":
        return cmd_replay(args)
    if args.command == "eval-freeze":
        return cmd_eval_freeze(args)
    if args.command == "eval-root":
        return cmd_eval_root(args)
    if args.command == "make-synthetic":
        return cmd_make_synthetic(args)
    if args.command == "run-items":
        return cmd_run_items(args)
    if args.command == "score":
        return cmd_score(args)
    if args.command == "run-arms":
        return cmd_run_arms(args)
    if args.command == "score-arms":
        return cmd_score_arms(args)
    if args.command == "real-worksheet":
        return cmd_real_worksheet(args)
    if args.command == "real-label":
        return cmd_real_label(args)
    if args.command == "real-import":
        return cmd_real_import(args)
    if args.command == "drift-report":
        return cmd_drift_report(args)
    if args.command == "reppo-audit":
        return {
            "prepare": cmd_audit_prepare,
            "submit": cmd_audit_submit,
            "report": cmd_audit_report,
        }[args.audit_command](args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "reppo-status":
        return cmd_reppo_status(args)
    if args.command == "reppo-resolve":
        return cmd_reppo_resolve(args)
    return cmd_verify(args)
