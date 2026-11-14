"""Run the grounding proxy against the LIVE SERV API once and record what happened.

NOT part of the test suite (real key, network, a few cents). It starts `currant serve`'s proxy in
this process, sends one OpenAI-style chat request through it (with your SERV key as the caller's
Bearer token, which is how the proxy is meant to be used), and saves the measured behaviour to
results/smoke/<utc>-proxy.json: status, latency, the X-Currant headers, SERV's finish_reason and
usage, and the answer text. The key is never saved.

    uv run python scripts/live_proxy.py [--db data/currant.db] [--extract-run 1] [--relate-run 4]

The questions are about public sponsor documentation that is NOT a conflict (no drift is sent
anywhere). Nothing here goes to Reppo.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from currant.config import MissingSecret, serv_api_key
from currant.proxy import GroundingProxy
from currant.proxy_http import make_server
from currant.store import ClaimStore

RESULTS = Path("results/smoke")
QUESTIONS = (
    "How much does gpt-6-luna cost per million input tokens and per million output tokens?",
    "Which tool turns on the SERV prompt injection guard?",
)


def ask(client: httpx.Client, key: str, question: str) -> dict[str, Any]:
    started = time.monotonic()
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "gpt-6-luna",
            "max_completion_tokens": 600,
            "messages": [{"role": "user", "content": question}],
        },
    )
    elapsed = round((time.monotonic() - started) * 1000)
    row: dict[str, Any] = {
        "question": question,
        "http_status": response.status_code,
        "latency_ms": elapsed,
        "content_type": response.headers.get("content-type"),
        "currant_headers": {
            k: v for k, v in response.headers.items() if k.lower().startswith("x-currant-")
        },
    }
    try:
        body = response.json()
    except ValueError:
        row["body_text"] = response.text[:400].replace(key, "<redacted>")
        return row
    choice = (body.get("choices") or [{}])[0]
    row.update(
        finish_reason=choice.get("finish_reason"),
        usage=body.get("usage"),
        answer=((choice.get("message") or {}).get("content") or "")[:800],
        error=body.get("error"),
    )
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/currant.db"))
    parser.add_argument("--extract-run", type=int, default=1)
    parser.add_argument("--relate-run", type=int, default=4)
    parser.add_argument("--mode", default="annotate")
    args = parser.parse_args(argv)
    try:
        key = serv_api_key().reveal()
    except MissingSecret as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    store = ClaimStore(args.db)
    receipts = Path("data/proxy-receipts")
    rows: list[dict[str, Any]] = []
    with httpx.Client(
        timeout=httpx.Timeout(300.0, connect=10.0), follow_redirects=False
    ) as upstream:
        proxy = GroundingProxy(
            store, extract_run_id=args.extract_run, relate_run_id=args.relate_run,
            http=upstream, receipts_dir=receipts, mode=args.mode,
        )  # fmt: skip
        server = make_server(proxy, "127.0.0.1", 0)
        port = server.server_address[1]

        def client_side() -> None:
            # The store belongs to this (main) thread, so the SERVER runs here and the caller runs
            # in a worker, exactly like two separate processes would.
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=300.0) as client:
                    for question in QUESTIONS:
                        row = ask(client, key, question)
                        rows.append(row)
                        print(f"{row['http_status']} {row['latency_ms']:>6} ms  {question[:60]}")
                        print(f"    finish={row.get('finish_reason')} usage={row.get('usage')}")
                        print(
                            f"    {row.get('answer') or row.get('error') or row.get('body_text')}"
                        )
            finally:
                server.shutdown()

        worker = threading.Thread(target=client_side, daemon=True)
        worker.start()
        try:
            server.serve_forever()
        finally:
            worker.join()
            server.server_close()
            proxy.close()
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-proxy.json"
    document = {
        "mode": "proxy-live",
        "proxy_mode": args.mode,
        "extract_run": args.extract_run,
        "relate_run": args.relate_run,
        "saved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "calls": rows,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"saved {path}")
    return 0 if all(r["http_status"] == 200 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
