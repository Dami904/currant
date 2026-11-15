"""Live probe: which SERV models exist, and which can do what Currant needs.

NOT part of the test suite: it uses the real SERV key, the network and a few cents of credits.
Run from the repo root:

    uv run python scripts/live_models.py            # list models, then probe each chat model
    uv run python scripts/live_models.py --list     # list only, no completions

For each model it sends the one request shape the pipeline depends on: a system prompt, a strict
`json_schema` response format, and the `serv_prompt_guard` tool. A model that cannot do all
three cannot replace gpt-6-luna in extraction or detection. The full record (requests,
responses, headers, latency) goes to results/smoke/<utc>-models.json with the key scrubbed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from live_smoke import SERV_BASE, Recorder

from currant.config import MissingSecret, serv_api_key

MAX_MODELS = 15  # a ceiling on spend if the list is unexpectedly long

SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "value": {"type": "string"}},
    "required": ["subject", "value"],
    "additionalProperties": False,
}


def _probe_body(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "Extract the subject and value into the schema."},
            {"role": "user", "content": "Text: The API allows 120 requests per minute."},
        ],
        "max_completion_tokens": 1000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "claim", "strict": True, "schema": SCHEMA},
        },
        "tools": [{"type": "function", "function": {"name": "serv_prompt_guard"}}],
    }


def _verdict(record: dict[str, Any]) -> str:
    body = record.get("response_json")
    if record["outcome"] != "confirmed" or not isinstance(body, dict):
        text = json.dumps(body)[:160] if body is not None else str(record.get("error", ""))[:160]
        return f"FAIL http={record.get('http_status')} {text}"
    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
        finish = choice.get("finish_reason")
        parsed = json.loads(content) if content else None
    except (KeyError, IndexError, TypeError, ValueError):
        return "FAIL unreadable or non-JSON content"
    if finish == "content_filter":
        return "BLOCKED by guard on a benign input"
    if not isinstance(parsed, dict) or set(parsed) != {"subject", "value"}:
        return f"FAIL schema not honoured: {str(content)[:120]}"
    usage = body.get("usage") or {}
    return (
        f"OK value={parsed['value']!r} tokens={usage.get('prompt_tokens')}/"
        f"{usage.get('completion_tokens')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list models only")
    parser.add_argument("--only", nargs="+", help="probe only these model ids")
    args = parser.parse_args(argv)
    try:
        key = serv_api_key()
    except MissingSecret as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    recorder = Recorder("models", [key])
    auth = {"Authorization": f"Bearer {key.reveal()}"}
    listing = recorder.call("list_models", "GET", f"{SERV_BASE}/models", headers=auth)
    body = listing.get("response_json")
    # Measured 2026-11-15: SERV answers {"items": [{"modelId", "provider", "pricing", "specs",
    # "endpoints", ...}]}, not the OpenAI {"data": [{"id"}]} shape. Accept either.
    data = (body.get("items") or body.get("data")) if isinstance(body, dict) else None
    if not isinstance(data, list):
        print(f"model list: {listing['outcome']} http={listing.get('http_status')}")
        print(f"saved {recorder.save()}")
        return 1
    rows = [item for item in data if isinstance(item, dict)]
    ids: list[str] = []
    print(f"{len(rows)} models listed:")
    for item in rows:
        model_id = str(item.get("modelId") or item.get("id"))
        endpoints = item.get("endpoints") or []
        specs = item.get("specs") or {}
        print(
            f"  {model_id:<34} {item.get('provider', '?'):<10} price={item.get('pricing', {})} "
            f"ctx={specs.get('contextWindow')} reasoning={specs.get('reasoning')} "
            f"endpoints={endpoints}"
        )
        if not endpoints or "chatCompletions" in endpoints:
            ids.append(model_id)
    if args.only:
        unknown = sorted(set(args.only) - set(ids))
        if unknown:
            print(f"not in the list (skipped): {unknown}")
        ids = [model for model in args.only if model in ids]
    if not args.list:
        print("\nprobe: system prompt + strict json_schema + serv_prompt_guard")
        headers = {**auth, "Content-Type": "application/json"}
        for model in ids[:MAX_MODELS]:
            record = recorder.call(
                f"probe:{model}",
                "POST",
                f"{SERV_BASE}/chat/completions",
                headers=headers,
                body=_probe_body(model),
                timeout=180.0,
            )
            print(f"  {model:<32} {record['latency_ms']:>6} ms  {_verdict(record)}")
        if len(ids) > MAX_MODELS:
            print(f"  ({len(ids) - MAX_MODELS} more not probed; raise MAX_MODELS to include them)")
    print(f"saved {recorder.save()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
