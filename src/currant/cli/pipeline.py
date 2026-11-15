"""Commands that run the pipeline: extract, relate, ground, replay and the proxy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from currant.cli._common import (
    USER_AGENT,
    open_existing,
    open_model,
    warn_if_log_failed,
)
from currant.config import (
    DotenvError,
    MissingSecret,
    serv_api_key,
)
from currant.crawldiff import changed_pages
from currant.detect import (
    run_detection,
)
from currant.extract import run_extraction
from currant.ground import Retrieved, ground
from currant.obs import utc_now
from currant.proxy import GroundingProxy
from currant.proxy_http import make_server
from currant.receipt import build_receipt, replay
from currant.retrieve import PageIndex
from currant.serv import ServClient
from currant.store import ClaimStore, StoreError


def _changed_since(store: ClaimStore, snapshot_id: int, since: str) -> frozenset[str]:
    """Documents of this snapshot whose URL had different content in the snapshot dated `since`
    (which must already be in the store)."""
    row = store.conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE snapshot_date = ? ORDER BY snapshot_id DESC",
        (since,),
    ).fetchone()
    if row is None:
        raise StoreError(f"no snapshot dated {since} in the store; ingest it first")
    pages = changed_pages(store, int(row["snapshot_id"]), snapshot_id)
    return frozenset(page.new_doc for page in pages)


def cmd_extract(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
    except (MissingSecret, DotenvError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        store = ClaimStore(args.db)
        ingest = store.ingest_snapshot(args.snapshot, allow_unreconciled=args.allow_unreconciled)
        only_docs = None
        if args.only_changed_since is not None:
            only_docs = _changed_since(store, ingest.snapshot_id, args.only_changed_since)
            print(f"only the {len(only_docs)} pages changed since {args.only_changed_since}")
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
                only_docs=only_docs,
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


def cmd_relate(args: argparse.Namespace) -> int:
    try:
        key = serv_api_key(args.dotenv)
        store = open_existing(args.db)
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
        caching = open_model(http, key, args, raw_log)
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
            warn_if_log_failed(model, raw_log)
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


def cmd_ground(args: argparse.Namespace) -> int:
    try:
        store = open_existing(args.db)
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


def cmd_replay(args: argparse.Namespace) -> int:
    try:
        store = open_existing(args.db)
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


def cmd_serve(args: argparse.Namespace) -> int:
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print(
            "error: the proxy has no login of its own (anyone who can reach it can read receipts, "
            "which contain questions); pass --allow-remote to listen on a non-loopback host",
            file=sys.stderr,
        )
        return 2
    try:
        store = open_existing(args.db)
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
