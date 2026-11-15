"""Commands for the sealed evaluation set: items, runs, scores and the freeze."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from currant.cli._common import (
    USER_AGENT,
    open_model,
    warn_if_log_failed,
)
from currant.config import (
    DotenvError,
    MissingSecret,
    serv_api_key,
)
from currant.detect import (
    DEFAULT_MAX_PAIRS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    DETECTOR_VERSION,
)
from currant.detect import PROMPT_VERSION as RELATE_PROMPT
from currant.evalset import EvalError, EvalStore
from currant.extract import PROMPT_VERSION as EXTRACT_PROMPT
from currant.harness.answer import PROMPT_VERSION as ANSWER_PROMPT
from currant.harness.arm_score import format_arm_report, score_item_arms, summarize_arms
from currant.harness.arms import (
    ORACLE_ARM,
    RETRIEVAL_VERSION,
    run_arms,
)
from currant.harness.oracle import oracle_hints
from currant.harness.run_items import DEFAULT_RETRIES, is_unknown, load_predictions, run_items
from currant.harness.score import score_item, summarize
from currant.harness.synth import generate
from currant.obs import utc_now
from currant.store import ClaimStore, StoreError


def cmd_eval_freeze(args: argparse.Namespace) -> int:
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


def cmd_eval_root(args: argparse.Namespace) -> int:
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


def cmd_make_synthetic(args: argparse.Namespace) -> int:
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


def cmd_run_items(args: argparse.Namespace) -> int:
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
        caching = open_model(http, key, args, raw_log)
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
            warn_if_log_failed(model, raw_log)
            unfinished = sum(is_unknown(p) for p in load_predictions(out).values())
            if unfinished:
                print(
                    f"{unfinished} items did not finish (a pair or page failed): UNKNOWN. "
                    "Run the same command again to retry only those."
                )
    return 0


def cmd_score(args: argparse.Namespace) -> int:
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


def cmd_run_arms(args: argparse.Namespace) -> int:
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
        caching = open_model(http, key, args, raw_log)
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
            warn_if_log_failed(model, raw_log)
            unfinished = sum(is_unknown(p) for p in load_predictions(out).values())
            if unfinished:
                print(
                    f"{unfinished} items did not finish (a step or an answer failed): UNKNOWN. "
                    "Run the same command again to retry only those."
                )
    return 0


def cmd_score_arms(args: argparse.Namespace) -> int:
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
