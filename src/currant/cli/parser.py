"""The argument parser: every command and its options."""

from __future__ import annotations

import argparse
from pathlib import Path

from currant.cli._common import (
    CLI_DOC,
    DEFAULT_EVAL_DB,
    DEFAULT_PROXY_RECEIPTS,
    DEFAULT_REPPO_LEDGER,
    PRIVATE_DIR,
    arm_list,
    int_list,
    non_negative_float,
    non_negative_int,
    positive_int,
)
from currant.config import (
    DEFAULT_DOTENV,
)
from currant.detect import (
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
)
from currant.ground import MODES
from currant.harness.arms import (
    ALL_ARMS,
    ARMS,
    DEFAULT_KS,
    ORACLE_ARM,
)
from currant.serv import DEFAULT_MODEL, SERV_BASE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="currant", description=CLI_DOC)
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
        "--delay", type=non_negative_float, default=0.25, help="seconds between requests"
    )
    crawl.add_argument("--max-attempts", type=positive_int, default=4)

    secrets = sub.add_parser("secrets", help="show which API keys are set (never their values)")
    secrets.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV, help="path to .env")

    extract = sub.add_parser(
        "extract", help="extract claims from a crawl snapshot into the claim store"
    )
    extract.add_argument("--snapshot", type=Path, required=True, help="e.g. snapshots/2026-11-05")
    extract.add_argument("--db", type=Path, default=Path("data/currant.db"))
    extract.add_argument("--limit", type=positive_int, help="only the first N pages")
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
        type=positive_int,
        metavar="RUN_ID",
        help="carry on an interrupted run: skip pages it finished, retry pages that failed",
    )
    extract.add_argument(
        "--only-changed-since",
        metavar="DATE",
        help="only pages whose content differs from the snapshot of DATE (already ingested)",
    )
    extract.add_argument("--results-dir", type=Path, default=Path("results/extract"))
    extract.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    relate = sub.add_parser(
        "relate", help="find which claims replace or contradict each other (uses the model)"
    )
    relate.add_argument("--db", type=Path, default=Path("data/currant.db"))
    relate.add_argument("--extract-run", type=positive_int, required=True)
    relate.add_argument("--model", default=DEFAULT_MODEL)
    relate.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    relate.add_argument("--min-score", type=non_negative_float, default=DEFAULT_MIN_SCORE)
    relate.add_argument("--top-k", type=positive_int, default=DEFAULT_TOP_K)
    relate.add_argument("--max-pairs", type=positive_int, default=2000)
    relate.add_argument("--dotenv", type=Path, default=DEFAULT_DOTENV)

    grnd = sub.add_parser(
        "ground", help="build the context a model would see, plus a replayable receipt"
    )
    grnd.add_argument("--db", type=Path, default=Path("data/currant.db"))
    grnd.add_argument("--extract-run", type=positive_int, required=True)
    grnd.add_argument("--relate-run", type=positive_int, required=True)
    grnd.add_argument("--mode", choices=MODES, default="redact_pull")
    grnd.add_argument(
        "--url",
        action="append",
        help="choose a page yourself (repeatable); without it the pages are retrieved by BM25",
    )
    grnd.add_argument(
        "--top-k",
        type=positive_int,
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
    synth.add_argument("--run", type=positive_int, required=True, help="extract run to draw from")
    synth.add_argument("--seed", type=non_negative_int, default=1)
    synth.add_argument("--supersede", type=non_negative_int, default=99)
    synth.add_argument("--clean", type=non_negative_int, default=100)

    runi = sub.add_parser("run-items", help="run the pipeline on evaluation items (no labels read)")
    runi.add_argument("--evalset", type=Path, default=DEFAULT_EVAL_DB)
    runi.add_argument("--split", choices=["dev", "test", "heldout"], default="dev")
    runi.add_argument("--out", type=Path, help="predictions file (reuse it to resume)")
    runi.add_argument("--cache", type=Path, default=Path("data/llm_cache.db"))
    runi.add_argument("--limit", type=positive_int)
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
    arms.add_argument("--limit", type=positive_int)
    arms.add_argument("--model", default=DEFAULT_MODEL)
    arms.add_argument("--ks", type=int_list, default=DEFAULT_KS, help="retrieval depths, e.g. 1,2")
    arms.add_argument(
        "--arms",
        type=arm_list,
        default=ARMS,
        help=f"from: {', '.join(ALL_ARMS)} ({ORACLE_ARM} reads labels: an upper bound only)",
    )
    arms.add_argument("--repeats", type=positive_int, default=1, help="independent answers per arm")
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
    serve.add_argument("--top-k", type=positive_int, default=4)
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
    rwork.add_argument("--max-items", type=positive_int, default=60)
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
    prep.add_argument("--top-k", type=positive_int, default=2)
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

    cdiff = sub.add_parser(
        "crawl-diff",
        help="record supersessions seen between two crawls of the same page (no model)",
    )
    cdiff.add_argument("--db", type=Path, default=Path("data/currant.db"))
    cdiff.add_argument("--old-run", type=positive_int, required=True, help="extract run, older")
    cdiff.add_argument("--new-run", type=positive_int, required=True, help="extract run, newer")

    asof = sub.add_parser("as-of", help="what Currant had seen for a URL on a given date")
    asof.add_argument("url")
    asof.add_argument("--date", required=True, help="e.g. 2026-11-08")
    asof.add_argument("--db", type=Path, default=Path("data/currant.db"))

    verify = sub.add_parser("verify", help="check a snapshot against its manifest")
    verify.add_argument("snapshot", type=Path, help="e.g. snapshots/2026-11-05")
    verify.add_argument(
        "--allow-unreconciled",
        action="store_true",
        help="accept unknown / failed / blocked / cap-skipped records",
    )
    return parser
