"""Commands for the Reppo audit and its submission ledger."""

from __future__ import annotations

import argparse
import sys

import httpx

from currant.cli._common import (
    USER_AGENT,
    open_existing,
    open_model,
)
from currant.config import (
    DotenvError,
    MissingSecret,
    reppo_api_key,
    serv_api_key,
)
from currant.reppo import InvalidSubmission, ReppoClient, ReppoError, ReppoLedger
from currant.reppo_audit import AuditError, load_questions, prepare
from currant.reppo_audit import report as audit_report
from currant.reppo_run import run_submissions, write_submissions
from currant.store import StoreError


def cmd_audit_prepare(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
        questions = load_questions(args.questions)
        store = open_existing(args.db)
    except (MissingSecret, DotenvError, AuditError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raw_log = args.out.with_name(args.out.name + ".raw.jsonl")
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(300.0, connect=10.0),
        follow_redirects=False,
    ) as http:
        caching = open_model(http, key, args, raw_log)
        if caching is None:
            return 2
        with caching as model:
            try:
                prepared = prepare(
                    store, args.extract_run, args.relate_run, model, questions,
                    arm=args.arm, top_k=args.top_k,
                )  # fmt: skip
                digest = write_submissions(args.out, prepared.submissions)
            except (AuditError, StoreError, ValueError, OSError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
    chars = sum(len(s.text) for s in prepared.submissions)
    count = len(prepared.submissions)
    print(f"wrote {count} submissions for {len(questions)} questions to {args.out}")
    print(f"about {chars} characters will be PUBLIC; each settled evaluation costs 440 credits")
    for qid in prepared.identical:
        print(f"  note: both arms answered {qid!r} the same way, so they share one evaluation")
    print("Read the file. Then, only if you accept it being posted publicly:")
    print(f"  currant reppo-audit submit --submissions {args.out} --confirm-public {digest} \\")
    print("      --results <results.jsonl>")
    return 0


def cmd_audit_submit(args: argparse.Namespace) -> int:
    try:
        key = reppo_api_key(args.dotenv)
    except (MissingSecret, DotenvError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=False,
    ) as http:
        client = ReppoClient(http, key)
        try:
            report = run_submissions(
                client, ReppoLedger(args.ledger), args.submissions, args.confirm_public,
                args.results, interval=args.interval, timeout=args.timeout,
            )  # fmt: skip
        except (InvalidSubmission, ReppoError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"settled {report.settled}, already done {report.skipped}")
    if report.stopped:
        print(f"STOPPED at {report.stopped}")
        return 1
    return 0


def cmd_audit_report(args: argparse.Namespace) -> int:
    try:
        print(audit_report(args.results))
    except (ReppoError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_reppo_status(args: argparse.Namespace) -> int:
    try:
        states = ReppoLedger(args.ledger).states()
    except ReppoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for key, state in states.items():
        print(f"{key}  {state.status:<13} {state.eval_id or ''} {state.reason or ''}".rstrip())
    unresolved = [k for k, st in states.items() if st.status == "intent"]
    print(f"{len(states)} submission(s), {len(unresolved)} unresolved")
    return 1 if unresolved else 0


def cmd_reppo_resolve(args: argparse.Namespace) -> int:
    try:
        ReppoLedger(args.ledger).resolve(args.key, None if args.none else args.eval_id)
    except (ReppoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"resolved {args.key[:12]}")
    return 0
