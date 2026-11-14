"""Command line entry point (`currant --help` lists every command)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from currant import __version__
from currant.config import (
    DEFAULT_DOTENV,
    SECRET_NAMES,
    DotenvError,
    MissingSecret,
    Secret,
    all_secret_status,
    dotenv_names,
    reppo_api_key,
    serv_api_key,
)
from currant.crawl.config import ConfigError, load_config
from currant.crawl.runner import run_crawl
from currant.crawl.snapshot import LOG_NAME, SnapshotError, sha256_hex, verify_snapshot
from currant.detect import (
    DEFAULT_MAX_PAIRS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    DETECTOR_VERSION,
    run_detection,
)
from currant.detect import PROMPT_VERSION as RELATE_PROMPT
from currant.drift import drift_report
from currant.evalset import EvalError, EvalStore
from currant.extract import PROMPT_VERSION as EXTRACT_PROMPT
from currant.extract import run_extraction
from currant.ground import MODES, Retrieved, ground
from currant.harness.answer import PROMPT_VERSION as ANSWER_PROMPT
from currant.harness.arm_score import format_arm_report, score_item_arms, summarize_arms
from currant.harness.arms import (
    ALL_ARMS,
    ARMS,
    DEFAULT_KS,
    ORACLE_ARM,
    RETRIEVAL_VERSION,
    run_arms,
)
from currant.harness.oracle import oracle_hints
from currant.harness.real_items import import_worksheet, label_session, make_worksheet
from currant.harness.run_items import DEFAULT_RETRIES, is_unknown, load_predictions, run_items
from currant.harness.score import score_item, summarize
from currant.harness.synth import generate
from currant.llmcache import CachingModel, json_object_reply
from currant.obs import JsonLogger, utc_now
from currant.proxy import GroundingProxy
from currant.proxy_http import make_server
from currant.receipt import build_receipt, replay
from currant.reppo import InvalidSubmission, ReppoClient, ReppoError, ReppoLedger
from currant.reppo_audit import AuditError, load_questions, prepare
from currant.reppo_audit import report as audit_report
from currant.reppo_run import run_submissions, write_submissions
from currant.retrieve import PageIndex
from currant.serv import DEFAULT_MODEL, SERV_BASE, ServClient
from currant.store import ClaimStore, StoreError

# [0-9], not \d: \d also matches non-ASCII digits, and this string becomes a directory name.
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
USER_AGENT = f"currant-crawler/{__version__}"
DEFAULT_EVAL_DB = Path("data/evalset.db")
DEFAULT_REPPO_LEDGER = Path("data/reppo-ledger.jsonl")
DEFAULT_PROXY_RECEIPTS = Path("data/proxy-receipts")
PRIVATE_DIR = Path("docs/private")


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {value}")
    return value


def _int_list(raw: str) -> tuple[int, ...]:
    """Comma-separated positive integers, e.g. "1,2"."""
    try:
        return tuple(_positive_int(part) for part in raw.split(",") if part.strip())
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(f"{raw!r}: {exc}") from None


def _arm_list(raw: str) -> tuple[str, ...]:
    arms = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = [arm for arm in arms if arm not in ALL_ARMS]
    if not arms or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown arm {', '.join(unknown) or raw!r}; choose from {', '.join(ALL_ARMS)}"
        )
    return arms


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def _non_negative_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not value >= 0:  # also rejects NaN
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {raw}")
    return value


def _valid_date(text: str) -> bool:
    if not _DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="currant", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="fetch docs into a dated snapshot")
    crawl.add_argument("--config", type=Path, default=Path("corpora.toml"))
    crawl.add_argument("--out", type=Path, default=Path("snapshots"))
    crawl.add_argument("--date", help="snapshot date YYYY-MM-DD (default: today, UTC)")
    crawl.add_argument("--corpus", action="append", help="only crawl this corpus (repeatable)")
    crawl.add_argument("--refresh", action="store_true", help="refetch pages already snapshotted")
    crawl.add_argument(
        "--allow-truncation",
        action="store_true",
        help="do not fail the run when a corpus hits its max_pages cap",
    )
    crawl.add_argument(
        "--delay", type=_non_negative_float, default=0.25, help="seconds between requests"
    )
    crawl.add_argument("--max-attempts", type=_positive_int, default=4)

    secrets = sub.add_parser("secrets", help="show which API keys are set (never their values)")
    secrets.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV, help="path to .env")

    extract = sub.add_parser(
        "extract", help="extract claims from a crawl snapshot into the claim store"
    )
    extract.add_argument("--snapshot", type=Path, required=True, help="e.g. snapshots/2026-11-05")
    extract.add_argument("--db", type=Path, default=Path("data/currant.db"))
    extract.add_argument("--limit", type=_positive_int, help="only the first N pages")
    extract.add_argument("--model", default=DEFAULT_MODEL)
    extract.add_argument(
        "--shadow",
        action="store_true",
        help="add the SERV shadow-agent check (about 4x slower; no measured benefit so far)",
    )
    extract.add_argument(
        "--allow-unguarded-retry",
        action="store_true",
        help="retry a guard-blocked page without the prompt guard (recorded in the run)",
    )
    extract.add_argument(
        "--resume",
        type=_positive_int,
        metavar="RUN_ID",
        help="carry on an interrupted run: skip pages it finished, retry pages that failed",
    )
    extract.add_argument("--results-dir", type=Path, default=Path("results/extract"))
    extract.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    relate = sub.add_parser(
        "relate", help="find which claims replace or contradict each other (uses the model)"
    )
    relate.add_argument("--db", type=Path, default=Path("data/currant.db"))
    relate.add_argument("--extract-run", type=_positive_int, required=True)
    relate.add_argument("--model", default=DEFAULT_MODEL)
    relate.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    relate.add_argument("--min-score", type=_non_negative_float, default=DEFAULT_MIN_SCORE)
    relate.add_argument("--top-k", type=_positive_int, default=DEFAULT_TOP_K)
    relate.add_argument("--max-pairs", type=_positive_int, default=2000)
    relate.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    grnd = sub.add_parser(
        "ground", help="build the context a model would see, plus a replayable receipt"
    )
    grnd.add_argument("--db", type=Path, default=Path("data/currant.db"))
    grnd.add_argument("--extract-run", type=_positive_int, required=True)
    grnd.add_argument("--relate-run", type=_positive_int, required=True)
    grnd.add_argument("--mode", choices=MODES, default="redact_pull")
    grnd.add_argument(
        "--url",
        action="append",
        help="choose a page yourself (repeatable); without it the pages are retrieved by BM25",
    )
    grnd.add_argument(
        "--top-k",
        type=_positive_int,
        help="how many pages to retrieve for the question (default 10; not with --url)",
    )
    grnd.add_argument("--question", required=True)
    grnd.add_argument("--out", type=Path, required=True, help="where to write the receipt")
    grnd.add_argument("--context-out", type=Path, help="also write the grounded context text")

    rply = sub.add_parser("replay", help="recompute a receipt from the store and check it")
    rply.add_argument("receipt", type=Path)
    rply.add_argument("--db", type=Path, default=Path("data/currant.db"))

    freeze = sub.add_parser(
        "eval-freeze", help="permanently unlock test and held-out labels and close the item set"
    )
    freeze.add_argument("--db", type=Path, default=DEFAULT_EVAL_DB)
    freeze.add_argument("--note", default="", help="why, for the audit log")
    freeze.add_argument("--yes", action="store_true", help="confirm: this cannot be undone")

    synth = sub.add_parser(
        "make-synthetic", help="create sealed synthetic evaluation items from the claim store"
    )
    synth.add_argument("--db", type=Path, default=Path("data/currant.db"))
    synth.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    synth.add_argument("--run", type=_positive_int, required=True, help="extract run to draw from")
    synth.add_argument("--seed", type=_non_negative_int, default=1)
    synth.add_argument("--supersede", type=_non_negative_int, default=99)
    synth.add_argument("--clean", type=_non_negative_int, default=100)

    runi = sub.add_parser("run-items", help="run the pipeline on evaluation items (no labels read)")
    runi.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    runi.add_argument("--split", choices=["dev", "test", "heldout"], default="dev")
    runi.add_argument("--out", type=Path, help="predictions file (reuse it to resume)")
    runi.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    runi.add_argument("--limit", type=_positive_int)
    runi.add_argument("--model", default=DEFAULT_MODEL)
    runi.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    scorer = sub.add_parser("score", help="score predictions against sealed labels")
    scorer.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    scorer.add_argument("--predictions", type=Path, required=True)
    scorer.add_argument("--split", choices=["dev", "test", "heldout"], default="dev")
    scorer.add_argument(
        "--all",
        action="store_true",
        help="count items with no prediction as misses (default: score only predicted items)",
    )

    arms = sub.add_parser(
        "run-arms",
        help="show a model each arm's context for evaluation items and record its answers",
    )
    arms.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    arms.add_argument("--split", choices=["dev", "test", "heldout"], default="dev")
    arms.add_argument("--out", type=Path, help="predictions file (reuse it to resume)")
    arms.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    arms.add_argument("--limit", type=_positive_int)
    arms.add_argument("--model", default=DEFAULT_MODEL)
    arms.add_argument("--ks", type=_int_list, default=DEFAULT_KS, help="retrieval depths, e.g. 1,2")
    arms.add_argument(
        "--arms",
        type=_arm_list,
        default=ARMS,
        help=f"from: {', '.join(ALL_ARMS)} ({ORACLE_ARM} reads labels: an upper bound only)",
    )
    arms.add_argument(
        "--repeats", type=_positive_int, default=1, help="independent answers per arm"
    )
    arms.add_argument("--seed", type=int, default=0, help="seed for the random-cut control")
    arms.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    arm_scorer = sub.add_parser(
        "score-arms", help="score recorded arm answers against sealed labels"
    )
    arm_scorer.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    arm_scorer.add_argument("--predictions", type=Path, required=True)
    arm_scorer.add_argument("--split", choices=["dev", "test", "heldout"], default="dev")

    root = sub.add_parser("eval-root", help="print the commit root over every sealed label")
    root.add_argument("--db", type=Path, default=DEFAULT_EVAL_DB)

    serve = sub.add_parser(
        "serve",
        help="run the OpenAI-compatible grounding proxy and receipt viewer",
        description="Point a client's base_url at http://HOST:PORT/v1. Its questions are grounded "
        "from the store before they reach SERV; the caller's own key is forwarded, never stored.",
    )
    serve.add_argument("--db", type=Path, default=Path("data/currant.db"))
    serve.add_argument("--extract-run", type=int, required=True)
    serve.add_argument("--relate-run", type=int, required=True)
    serve.add_argument(
        "--mode", choices=["redact", "annotate", "pull", "redact_pull"], default="annotate"
    )
    serve.add_argument("--top-k", type=_positive_int, default=4)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--allow-remote", action="store_true", help="listen on a non-loopback host")
    serve.add_argument("--receipts", type=Path, default=DEFAULT_PROXY_RECEIPTS)
    serve.add_argument("--upstream", default=SERV_BASE)

    rwork = sub.add_parser(
        "real-worksheet",
        help="propose candidate real items for a person to label (private)",
        description="Writes under docs/private/ (git-ignored): the pairs are possible conflicts in "
        "sponsor documentation. It shows no detector verdict, so the labels stay independent.",
    )
    rwork.add_argument("--db", type=Path, default=Path("data/currant.db"))
    rwork.add_argument("--extract-run", type=int, required=True)
    rwork.add_argument("--max-items", type=_positive_int, default=60)
    rwork.add_argument("--out", type=Path, default=PRIVATE_DIR / "real-worksheet.json")
    rwork.add_argument("--publish", action="store_true", help="allow writing outside docs/private")

    rlab = sub.add_parser(
        "real-label",
        help="label the worksheet pairs at the terminal, one key each (saves after every answer)",
    )
    rlab.add_argument("--db", type=Path, default=Path("data/currant.db"))
    rlab.add_argument("--worksheet", type=Path, default=PRIVATE_DIR / "real-worksheet.json")

    rimp = sub.add_parser(
        "real-import",
        help="seal the labelled worksheet as real evaluation items (before the freeze)",
    )
    rimp.add_argument("--db", type=Path, default=Path("data/currant.db"))
    rimp.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    rimp.add_argument("--worksheet", type=Path, default=PRIVATE_DIR / "real-worksheet.json")

    drift = sub.add_parser(
        "drift-report",
        help="list the pages that disagree, quoted (private until confirmed by hand)",
        description="Writes under docs/private/ (git-ignored). Sponsor drift stays private until "
        "two sources confirm it and the maintainers are told; --publish overrides that.",
    )
    drift.add_argument("--db", type=Path, default=Path("data/currant.db"))
    drift.add_argument("--extract-run", type=int, required=True)
    drift.add_argument("--relate-run", type=int, required=True)
    drift.add_argument("--out", type=Path, default=PRIVATE_DIR / "drift-report.md")
    drift.add_argument("--publish", action="store_true", help="allow writing outside docs/private")

    audit = sub.add_parser(
        "reppo-audit",
        help="the Reppo audit: prepare a reviewable file, submit it, report the verdicts",
        description="Everything submitted to Reppo is PUBLIC and spends credits (440 each). "
        "`prepare` sends nothing to Reppo; `submit` refuses without the hash of the file you "
        "reviewed.",
    )
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    prep = audit_sub.add_parser("prepare", help="answer each question both ways; write the file")
    prep.add_argument(
        "--questions",
        type=Path,
        required=True,
        help="JSON lines: id, question, reference (recommended)",
    )
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--db", type=Path, default=Path("data/currant.db"))
    prep.add_argument("--extract-run", type=int, required=True)
    prep.add_argument("--relate-run", type=int, required=True)
    prep.add_argument(
        "--arm", choices=["redact", "annotate", "pull", "redact_pull"], default="pull"
    )
    prep.add_argument("--top-k", type=_positive_int, default=2)
    prep.add_argument("--model", default=DEFAULT_MODEL)
    prep.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    prep.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)
    subm = audit_sub.add_parser("submit", help="send the reviewed file to Reppo, one at a time")
    subm.add_argument("--submissions", type=Path, required=True)
    subm.add_argument("--confirm-public", help="the SHA-256 that `prepare` printed, after review")
    subm.add_argument("--results", type=Path, required=True)
    subm.add_argument("--ledger", type=Path, default=DEFAULT_REPPO_LEDGER)
    subm.add_argument("--interval", type=float, default=10.0, help="seconds between polls")
    subm.add_argument("--timeout", type=float, default=600.0, help="seconds to wait per evaluation")
    subm.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)
    rep = audit_sub.add_parser("report", help="summarise the verdicts")
    rep.add_argument("--results", type=Path, required=True)

    rstat = sub.add_parser("reppo-status", help="list Reppo submissions and any unresolved one")
    rstat.add_argument("--ledger", type=Path, default=DEFAULT_REPPO_LEDGER)

    rres = sub.add_parser(
        "reppo-resolve",
        help="record what the Reppo console shows for a submission whose outcome was unknown",
    )
    rres.add_argument("--ledger", type=Path, default=DEFAULT_REPPO_LEDGER)
    rres.add_argument("--key", required=True, help="the submission key from reppo-status")
    which = rres.add_mutually_exclusive_group(required=True)
    which.add_argument("--eval-id", help="the evalId the console shows for it")
    which.add_argument("--none", action="store_true", help="the console shows no such evaluation")

    verify = sub.add_parser("verify", help="check a snapshot against its manifest")
    verify.add_argument("snapshot", type=Path, help="e.g. snapshots/2026-11-05")
    verify.add_argument(
        "--allow-unreconciled",
        action="store_true",
        help="accept unknown / failed / blocked / cap-skipped records",
    )
    return parser


def _crawl(args: argparse.Namespace) -> int:
    snapshot_date: str = args.date or utc_now().date().isoformat()
    if not _valid_date(snapshot_date):
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


def _private_out_refused(out: Path, publish: bool) -> bool:
    if not publish and PRIVATE_DIR.resolve() not in out.resolve().parents:
        print(
            f"error: {out} is outside {PRIVATE_DIR}. Candidate sponsor-documentation conflicts "
            "stay private until two sources confirm them and the maintainers are told; pass "
            "--publish to override",
            file=sys.stderr,
        )
        return True
    return False


def _real_worksheet(args: argparse.Namespace) -> int:
    if _private_out_refused(args.out, args.publish):
        return 2
    try:
        store = _open_existing(args.db)
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


def _real_label(args: argparse.Namespace) -> int:
    def save(worksheet: dict[str, Any]) -> None:
        temporary = args.worksheet.with_name(args.worksheet.name + ".tmp")
        temporary.write_text(
            json.dumps(worksheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, args.worksheet)  # whole or not at all

    try:
        worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
        store = _open_existing(args.db)
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


def _real_import(args: argparse.Namespace) -> int:
    try:
        worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
        store = _open_existing(args.db)
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


def _drift_report(args: argparse.Namespace) -> int:
    if _private_out_refused(args.out, args.publish):
        return 2
    try:
        store = _open_existing(args.db)
        text = drift_report(store, args.extract_run, args.relate_run)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0


def _audit_prepare(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
        questions = load_questions(args.questions)
        store = _open_existing(args.db)
    except (MissingSecret, DotenvError, AuditError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raw_log = args.out.with_name(args.out.name + ".raw.jsonl")
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(300.0, connect=10.0),
        follow_redirects=False,
    ) as http:
        caching = _open_model(http, key, args, raw_log)
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


def _audit_submit(args: argparse.Namespace) -> int:
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


def _audit_report(args: argparse.Namespace) -> int:
    try:
        print(audit_report(args.results))
    except (ReppoError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _serve(args: argparse.Namespace) -> int:
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print(
            "error: the proxy has no login of its own (anyone who can reach it can read receipts, "
            "which contain questions); pass --allow-remote to listen on a non-loopback host",
            file=sys.stderr,
        )
        return 2
    try:
        store = _open_existing(args.db)
        with httpx.Client(
            timeout=httpx.Timeout(300.0, connect=10.0), follow_redirects=False
        ) as http:
            proxy = GroundingProxy(
                store,
                extract_run_id=args.extract_run,
                relate_run_id=args.relate_run,
                http=http,
                receipts_dir=args.receipts,
                mode=args.mode,
                top_k=args.top_k,
                upstream=args.upstream,
            )
            server = make_server(proxy, args.host, args.port)
            print(f"grounding proxy on http://{args.host}:{args.port}/v1  (mode {args.mode})")
            print(
                f"receipt viewer on http://{args.host}:{args.port}/   receipts in {args.receipts}"
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("stopped")
            finally:
                server.server_close()
                proxy.close()
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _reppo_status(args: argparse.Namespace) -> int:
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


def _reppo_resolve(args: argparse.Namespace) -> int:
    try:
        ReppoLedger(args.ledger).resolve(args.key, None if args.none else args.eval_id)
    except (ReppoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"resolved {args.key[:12]}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    problems = verify_snapshot(args.snapshot, allow_unreconciled=args.allow_unreconciled)
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"{len(problems)} problem(s) in {args.snapshot}")
        return 1
    print(f"OK {args.snapshot}")
    return 0


def _extract(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
    except (MissingSecret, DotenvError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        store = ClaimStore(args.db)
        ingest = store.ingest_snapshot(args.snapshot)
    except (StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    headers = {"User-Agent": USER_AGENT}
    # Generous read timeout: the shadow agent makes extra model calls per request.
    timeout = httpx.Timeout(300.0, connect=10.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as http:
        model = ServClient(http, key, model=args.model)
        try:
            summary = run_extraction(
                store,
                ingest.snapshot_id,
                model,
                limit=args.limit,
                allow_unguarded_retry=args.allow_unguarded_retry,
                shadow=args.shadow,
                resume_run_id=args.resume,
                results_dir=args.results_dir,
                delay=0.2,
            )
        except StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"run:          {summary.run_id}  ({summary.pages_total} pages)")
    print(
        f"pages:        {summary.pages_ok} ok, {summary.pages_failed} failed, "
        f"{summary.pages_guard_blocked} blocked by the guard"
    )
    print(f"claims:       {summary.accepted} stored of {summary.proposals} proposed")
    if summary.rejected_by_code:
        print(f"rejected:     {summary.rejected_by_code}")
    if summary.flags:
        print(f"flags:        {summary.flags}")
    print(
        f"est. cost:    ${summary.estimated_cost_usd} (tokens only; guard and shadow overhead "
        "is not in usage)"
    )
    if summary.results_path:
        print(f"raw outputs:  {summary.results_path}")
    for url in summary.guard_blocked_urls:
        print(f"guard blocked: {url}")
    for url in summary.failed_urls:
        print(f"failed:        {url}")
    if summary.pages_failed:
        print(
            f"run {summary.run_id} is INCOMPLETE: the failed pages have no claims. Retry them with "
            f"`currant extract --snapshot {args.snapshot} --resume {summary.run_id}`."
        )
    return 0 if summary.pages_failed == 0 and summary.pages_guard_blocked == 0 else 1


def _open_model(
    http: httpx.Client, key: Secret, args: argparse.Namespace, raw_log: Path
) -> CachingModel | None:
    """The cached SERV client, or None (after printing why) if its cache or raw log cannot be
    opened: an unwritable location is an error message, not a traceback."""
    try:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        return CachingModel(
            ServClient(http, key, model=args.model),
            args.cache,
            accept=json_object_reply,
            raw_log=raw_log,
        )
    except (OSError, sqlite3.Error) as exc:
        print(f"error: cannot open the model cache or raw log: {exc}", file=sys.stderr)
        return None


def _warn_if_log_failed(model: CachingModel, raw_log: Path) -> None:
    if model.log_errors:
        print(
            f"warning: {model.log_errors} raw-log writes to {raw_log} failed; the replies were "
            "still cached, but that part of the audit trail is missing",
            file=sys.stderr,
        )


def _open_existing(path: Path) -> ClaimStore:
    """Open a claim store that must already exist: a typo must not create an empty one."""
    if not path.is_file():
        raise StoreError(f"no claim store at {path}")
    return ClaimStore(path)


def _relate(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
        store = _open_existing(args.db)
        meta = store.run_meta(args.extract_run)
        if meta.stage != "extract":
            raise StoreError(f"run {args.extract_run} is not an extract run ({meta.stage})")
        if meta.params.get("limited"):
            raise StoreError(
                f"extract run {args.extract_run} covered only part of the snapshot (--limit); "
                "run it again without a limit"
            )
        if meta.status != "complete":
            raise StoreError(
                f"extract run {args.extract_run} did not complete (status {meta.status}): "
                "some pages have no claims. "
                f"Resume it: `currant extract --resume {args.extract_run}`."
            )
    except (MissingSecret, DotenvError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(300.0, connect=10.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as http:
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        raw_log = Path("results/relate") / f"{stamp}-extract{args.extract_run}.raw.jsonl"
        caching = _open_model(http, key, args, raw_log)
        if caching is None:
            return 2
        with caching as model:
            try:
                summary, _recorded = run_detection(
                    store,
                    args.extract_run,
                    meta.snapshot_id,
                    model,
                    min_score=args.min_score,
                    top_k=args.top_k,
                    max_pairs=args.max_pairs,
                )
            except Exception as exc:  # the run is already marked failed and the cause logged
                print(f"error: relate stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            hits, misses = model.hits, model.misses
            _warn_if_log_failed(model, raw_log)
    print(f"relate run:   {summary.run_id}  (from extract run {args.extract_run})")
    print(f"pairs:        {summary.pairs} asked about")
    if summary.left_out:
        print(
            f"warning: {summary.left_out} weaker candidate pairs were never asked about "
            "(raise --max-pairs to include them)",
            file=sys.stderr,
        )
    print(
        f"result:       {summary.supersedes} supersedes, {summary.contradicts} contradicts, "
        f"{summary.unrelated} unrelated, {summary.rejected} rejected by the database"
    )
    print(f"downgraded:   {summary.downgraded} (claimed more than the evidence verified)")
    print(f"failed:       {summary.failed}, blocked by the guard: {summary.guard_blocked}")
    print(f"model calls:  {misses} new, {hits} from the cache")
    print(f"raw outputs:  {raw_log}")
    return 0 if summary.failed == 0 and summary.guard_blocked == 0 else 1


def _ground(args: argparse.Namespace) -> int:
    try:
        store = _open_existing(args.db)
        meta = store.run_meta(args.extract_run)
        if args.url and args.top_k is not None:
            raise StoreError("choose pages with --url or retrieve with --top-k, not both")
        if args.url:
            by_url = {page.url: page.doc_id for page in store.pages(meta.snapshot_id)}
            unknown = [url for url in args.url if url not in by_url]
            if unknown:
                raise StoreError(
                    f"not in the snapshot of run {args.extract_run}: {', '.join(unknown)}"
                )
            docs = [Retrieved(by_url[url], url) for url in args.url]
        else:
            with PageIndex(store, meta.snapshot_id) as index:
                docs = index.search(args.question, k=args.top_k or 10)
            if not docs:
                raise StoreError("no page matched the question; choose pages with --url")
        grounded = ground(
            store,
            docs,
            mode=args.mode,
            extract_run_id=args.extract_run,
            relate_run_id=args.relate_run,
        )
        receipt = build_receipt(
            store,
            grounded,
            question=args.question,
            extract_run_id=args.extract_run,
            relate_run_id=args.relate_run,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if args.context_out is not None:
            args.context_out.parent.mkdir(parents=True, exist_ok=True)
            args.context_out.write_text(grounded.context, encoding="utf-8", newline="\n")
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    kinds: dict[str, int] = {}
    for action in grounded.actions:
        kinds[action.kind] = kinds.get(action.kind, 0) + 1
    how = "chosen" if args.url else "retrieved"
    print(f"mode:         {args.mode}  ({len(docs)} pages {how})")
    print(f"actions:      {kinds or 'none'}")
    print(f"context:      {len(grounded.context)} chars, sha256 {grounded.context_sha256}")
    print(f"receipt_id:   {receipt['receipt_id']}")
    print(f"receipt:      {args.out}")
    return 0


def _replay(args: argparse.Namespace) -> int:
    try:
        store = _open_existing(args.db)
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    except (StoreError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = replay(store, receipt)
    if result.ok:
        print(f"REPLAY OK: the context hash recomputes to {result.context_sha256}")
        return 0
    print("REPLAY FAILED")
    for problem in result.problems:
        print(f"  - {problem}")
    return 1


def _eval_freeze(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Refusing: freezing unlocks test and held-out labels for good.", file=sys.stderr)
        print("It cannot be undone and closes the item set.", file=sys.stderr)
        print("Do it at Gate 2 (Nov 11), once the prompt and detector are final.", file=sys.stderr)
        print("Rerun with --yes to confirm.", file=sys.stderr)
        return 2
    try:
        with EvalStore(args.db) as store:
            stamp = store.freeze(args.note)
            print(f"evaluation frozen at {stamp}")
            print(f"commit root: {store.commit_root()}")
    except (EvalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _run_items(args: argparse.Namespace) -> int:
    """Run the pipeline on items. It reads each item's inputs and never its label."""
    try:
        key = serv_api_key(args.dotenv)
        with EvalStore(args.evalset) as evals:
            if args.split != "dev" and not evals.is_frozen():
                raise EvalError(
                    f"refusing to run {args.split} items before the freeze: running them invites "
                    "tuning on them. Run `currant eval-freeze` at Gate 2 first."
                )
            items = evals.items(args.split)
    except (MissingSecret, DotenvError, EvalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("results/items") / f"{args.split}-{stamp}.jsonl"
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(300.0, connect=10.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as http:
        raw_log = out.with_name(out.name + ".raw.jsonl")
        caching = _open_model(http, key, args, raw_log)
        if caching is None:
            return 2
        with caching as model:

            def progress(number: int, total: int, item_id: str) -> None:
                cache = f"cache {model.hits} hit / {model.misses} miss"
                print(f"  {number}/{total} {item_id[:12]}  {cache}", flush=True)

            meta = {
                "model": args.model,
                "split": args.split,
                "extract_prompt": EXTRACT_PROMPT,
                "relate_prompt": RELATE_PROMPT,
                "detector": DETECTOR_VERSION,
                "retries": DEFAULT_RETRIES,
                "min_score": DEFAULT_MIN_SCORE,
                "top_k": DEFAULT_TOP_K,
                "max_pairs": DEFAULT_MAX_PAIRS,
                "raw_log": raw_log.name,
            }
            try:
                ran = run_items(items, model, out, limit=args.limit, progress=progress, meta=meta)
            except (StoreError, OSError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"ran {ran} of {len(items)} {args.split} items -> {out}")
            print(f"model calls: {model.misses} new, {model.hits} from the cache")
            print(f"raw outputs: {raw_log}")
            _warn_if_log_failed(model, raw_log)
            unfinished = sum(is_unknown(p) for p in load_predictions(out).values())
            if unfinished:
                print(
                    f"{unfinished} items did not finish (a pair or page failed): UNKNOWN. "
                    "Run the same command again to retry only those."
                )
    return 0


def _score(args: argparse.Namespace) -> int:
    """Join predictions to sealed labels. Dev labels are readable; the rest need the freeze."""
    try:
        predictions = load_predictions(args.predictions)
        with EvalStore(args.evalset) as evals:
            items = evals.items(args.split)
            labels = evals.labels(args.split)  # EvalLocked before the freeze for test/heldout
    except (EvalError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    chosen = items if args.all else [i for i in items if i.item_id in predictions]
    outcomes = [score_item(i, labels[i.item_id], predictions.get(i.item_id)) for i in chosen]
    summary = summarize(outcomes)
    print(f"{args.split}: {len(predictions)} predictions for {len(items)} items")
    print(f"scored {summary['items']} items from {summary['clusters']} source pages")
    unpredicted = sum(1 for i in items if i.item_id not in predictions)
    print(
        f"unpredicted: {unpredicted} of {len(items)}   "
        f"unknown (a pair or page failed): {summary['unknown']}"
    )
    for name, value in summary["metrics"].items():
        interval = summary["intervals_95_by_cluster"].get(name)
        shown = "n/a" if value is None else f"{value:.3f}"
        band = f"  95% by page [{interval[0]:.3f}, {interval[1]:.3f}]" if interval else ""
        print(f"  {name:<24} {shown}{band}")
    for scenario, row in summary["by_scenario"].items():
        print(f"  {scenario:<22} {row}")
    return 0


def _run_arms(args: argparse.Namespace) -> int:
    """Run every arm on items. It reads each item's inputs and never its label."""
    try:
        key = serv_api_key(args.dotenv)
        with EvalStore(args.evalset) as evals:
            if args.split != "dev" and not evals.is_frozen():
                raise EvalError(
                    f"refusing to run {args.split} items before the freeze: running them invites "
                    "tuning on them. Run `currant eval-freeze` at Gate 2 first."
                )
            items = evals.items(args.split)
            hints = oracle_hints(evals, items) if ORACLE_ARM in args.arms else None
    except (MissingSecret, DotenvError, EvalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("results/arms") / f"{args.split}-{stamp}.jsonl"
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(300.0, connect=10.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=False) as http:
        raw_log = out.with_name(out.name + ".raw.jsonl")
        caching = _open_model(http, key, args, raw_log)
        if caching is None:
            return 2
        with caching as model:

            def progress(number: int, total: int, item_id: str) -> None:
                cache = f"cache {model.hits} hit / {model.misses} miss"
                print(f"  {number}/{total} {item_id[:12]}  {cache}", flush=True)

            meta = {
                "model": args.model,
                "split": args.split,
                "extract_prompt": EXTRACT_PROMPT,
                "relate_prompt": RELATE_PROMPT,
                "detector": DETECTOR_VERSION,
                "answer_prompt": ANSWER_PROMPT,
                "retrieval": RETRIEVAL_VERSION,
                "ks": list(args.ks),
                "arms": list(args.arms),
                "repeats": args.repeats,
                "seed": args.seed,
                "retries": DEFAULT_RETRIES,
                "raw_log": raw_log.name,
            }
            try:
                ran = run_arms(
                    items, model, model, out, limit=args.limit, ks=args.ks, arms=args.arms,
                    repeats=args.repeats, seed=args.seed, progress=progress, meta=meta,
                    oracle=None if hints is None else hints.get,
                )  # fmt: skip
            except (StoreError, OSError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"ran {ran} of {len(items)} {args.split} items -> {out}")
            print(f"model calls: {model.misses} new, {model.hits} from the cache")
            print(f"raw outputs: {raw_log}")
            _warn_if_log_failed(model, raw_log)
            unfinished = sum(is_unknown(p) for p in load_predictions(out).values())
            if unfinished:
                print(
                    f"{unfinished} items did not finish (a step or an answer failed): UNKNOWN. "
                    "Run the same command again to retry only those."
                )
    return 0


def _score_arms(args: argparse.Namespace) -> int:
    """Join recorded arm answers to sealed labels. Dev labels are readable; the rest need the
    freeze."""
    try:
        predictions = load_predictions(args.predictions)
        with EvalStore(args.evalset) as evals:
            items = evals.items(args.split)
            labels = evals.labels(args.split)  # EvalLocked before the freeze for test/heldout
    except (EvalError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    outcomes = []
    for item in items:
        record = predictions.get(item.item_id)
        if record is not None:
            outcomes.extend(score_item_arms(item, labels[item.item_id], record))
    unknown = sum(
        1 for i in items if i.item_id in predictions and is_unknown(predictions[i.item_id])
    )
    unpredicted = sum(1 for i in items if i.item_id not in predictions)
    print(f"{args.split}: {len(predictions)} records for {len(items)} items")
    print(
        format_arm_report(summarize_arms(outcomes, unknown_items=unknown, unpredicted=unpredicted))
    )
    return 0


def _make_synthetic(args: argparse.Namespace) -> int:
    """Counts and the commit root only: never a label."""
    try:
        store = ClaimStore(args.db)
        args.evalset.parent.mkdir(parents=True, exist_ok=True)
        with EvalStore(args.evalset) as evals:
            summary = generate(
                store,
                args.run,
                evals,
                seed=args.seed,
                n_supersede=args.supersede,
                n_clean=args.clean,
            )
    except (StoreError, EvalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"items added:  {summary.items}")
    print(f"scenarios:    {dict(sorted(summary.by_scenario.items()))}")
    print(f"splits:       {dict(sorted(summary.by_split.items()))}  (all items in the store)")
    print(f"commit root:  {summary.commit_root}")
    print("Publish the commit root outside this machine before tuning anything on these items.")
    return 0


def _eval_root(args: argparse.Namespace) -> int:
    """The root plus counts per split: enough to publish as evidence, never a label."""
    try:
        with EvalStore(args.db) as store:
            items = store.items()
            print(f"commit root: {store.commit_root()}")
            print(f"items: {len(items)}  frozen: {store.is_frozen()}")
            for split in ("dev", "test", "heldout"):
                print(f"  {split}: {sum(1 for i in items if i.split == split)}")
    except (EvalError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _secrets(args: argparse.Namespace) -> int:
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
    args = _build_parser().parse_args(argv)
    if args.command == "crawl":
        return _crawl(args)
    if args.command == "secrets":
        return _secrets(args)
    if args.command == "extract":
        return _extract(args)
    if args.command == "relate":
        return _relate(args)
    if args.command == "ground":
        return _ground(args)
    if args.command == "replay":
        return _replay(args)
    if args.command == "eval-freeze":
        return _eval_freeze(args)
    if args.command == "eval-root":
        return _eval_root(args)
    if args.command == "make-synthetic":
        return _make_synthetic(args)
    if args.command == "run-items":
        return _run_items(args)
    if args.command == "score":
        return _score(args)
    if args.command == "run-arms":
        return _run_arms(args)
    if args.command == "score-arms":
        return _score_arms(args)
    if args.command == "real-worksheet":
        return _real_worksheet(args)
    if args.command == "real-label":
        return _real_label(args)
    if args.command == "real-import":
        return _real_import(args)
    if args.command == "drift-report":
        return _drift_report(args)
    if args.command == "reppo-audit":
        return {"prepare": _audit_prepare, "submit": _audit_submit, "report": _audit_report}[
            args.audit_command
        ](args)
    if args.command == "serve":
        return _serve(args)
    if args.command == "reppo-status":
        return _reppo_status(args)
    if args.command == "reppo-resolve":
        return _reppo_resolve(args)
    return _verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
