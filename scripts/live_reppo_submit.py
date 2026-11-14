"""ONE real evaluation through the current Reppo API, to record its measured behaviour.

NOT part of the test suite. This POSTS PUBLICLY and spends 440 credits of the account behind
REPPO_API_KEY. The text is the same harmless public sentence that was posted on 2026-11-05 (the SERV
models page price, which is public documentation). Saved to results/smoke/<utc>-reppo-new-api.json
with the key scrubbed. Runs once; there is no retry of the submit.

    uv run python scripts/live_reppo_submit.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from currant.config import MissingSecret, reppo_api_key

BASE = "https://eval.reppo.xyz/api/v1"
TEXT = (
    "User prompt: What does SERV Reasoning charge for gpt-6-luna?\n\n"
    "AI response: The SERV Reasoning models page lists gpt-6-luna at $0.13 per million input "
    "tokens and $0.65 per million output tokens."
)


def main() -> int:
    try:
        key = reppo_api_key().reveal()
    except MissingSecret as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    log: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        started = time.monotonic()
        response = client.post(
            f"{BASE}/agents/evals", headers=headers, json={"taskType": "response", "input": TEXT}
        )
        log.append(
            {
                "name": "submit",
                "http_status": response.status_code,
                "elapsed_s": round(time.monotonic() - started, 2),
                "headers": {
                    k: v for k, v in response.headers.items() if k.lower() in ("content-type",)
                },
                "body": response.text.replace(key, "<redacted>")[:2000],
            }
        )
        print("submit", response.status_code, response.text[:200])
        if response.status_code != 201:
            _save(log)
            return 1
        eval_id = response.json()["id"]
        status = "QUEUED"
        deadline = time.monotonic() + 600
        while status in ("QUEUED", "PROCESSING") and time.monotonic() < deadline:
            time.sleep(10)
            read = client.get(f"{BASE}/agents/evals/{eval_id}", headers=headers)
            body = read.json() if read.status_code == 200 else {}
            status = str(body.get("status", f"http_{read.status_code}"))
            log.append(
                {
                    "name": "poll",
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "http_status": read.status_code,
                    "body": json.loads(json.dumps(body)) if body else read.text[:300],
                }
            )
            print(f"  {round(time.monotonic() - started):>4}s  {status}")
    _save(log)
    return 0 if status == "COMPLETED" else 1


def _save(log: list[dict[str, Any]]) -> None:
    out = (
        Path("results/smoke") / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-reppo-new-api.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "reppo-new-api", "calls": log}, indent=2) + "\n", "utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    raise SystemExit(main())
