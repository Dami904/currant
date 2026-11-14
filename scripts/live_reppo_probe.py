"""Read-only probes of the Reppo Evaluation API: which endpoints exist today?

NOT part of the test suite (real key, network). It posts nothing public and spends no credits: it
GETs with a made-up id and POSTs an EMPTY body (which a live endpoint answers with 400, never by
creating an evaluation). Saved to results/smoke/<utc>-reppo-probe.json; the key is never saved.

    uv run python scripts/live_reppo_probe.py

Why it exists: eval.reppo.xyz/agents.md changed between 2026-11-05 and 2026-11-11 and now says the
`/agents/eval-requests/...` endpoints were removed. The docs.reppo.ai pages still describe them.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from currant.config import MissingSecret, reppo_api_key

BASE = "https://eval.reppo.xyz/api/v1"
OLD_ID = "eval_f52b60bd-290d-448f-94d8-35262ea8ef1b"  # our own 2026-11-05 evaluation
PROBES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", f"/agents/eval-requests/{OLD_ID}", None),  # old read endpoint, our own old eval
    ("GET", f"/agents/evals/{OLD_ID}", None),  # new read endpoint, same id
    ("GET", "/agents/evals/does-not-exist", None),  # new read endpoint, nonsense id
    ("POST", "/agents/eval-requests/submit", {}),  # old submit, empty body
    ("POST", "/agents/evals", {}),  # new submit, empty body
    ("GET", "/agents/eval-requests/pending", None),  # old pending list (other accounts' items)
)


def main() -> int:
    try:
        key = reppo_api_key().reveal()
    except MissingSecret as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        for method, path, body in PROBES:
            response = client.request(method, BASE + path, headers=headers, json=body)
            text = response.text.replace(key, "<redacted>")
            row: dict[str, Any] = {
                "method": method,
                "path": path,
                "http_status": response.status_code,
            }
            # Never store another account's data: the old pending list returns it.
            row["body"] = text[:300] if "pending" not in path else f"({len(text)} characters)"
            rows.append(row)
            print(f"{response.status_code}  {method:<4} {path[:60]:<60} {row['body'][:90]}")
    out = Path("results/smoke") / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-reppo-probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "reppo-probe", "probes": rows}, indent=2) + "\n", "utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
