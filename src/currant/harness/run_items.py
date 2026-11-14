"""Run the pipeline on evaluation items. This module never reads a label.

For each item it builds a throwaway in-memory store, loads the item's two pages, extracts claims,
finds candidate pairs, classifies them, verifies the evidence, and records what survived. The
result is a JSON-able prediction: the verified relations with their page and character spans.
Scoring against the sealed label is a separate step (`score.py`).

Pass a `CachingModel` and a rerun costs nothing: every request is keyed by its exact text.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from currant.detect import DetectSummary, run_detection
from currant.evalset import ItemRow
from currant.extract import ExtractionSummary, run_extraction
from currant.store import ClaimRow, ClaimStore


def _claim_json(claim: ClaimRow, page_of_doc: dict[str, str]) -> dict[str, Any]:
    return {
        "page": page_of_doc.get(claim.doc_id, "?"),
        "start": claim.start_char,
        "end": claim.end_char,
        "quote": claim.quote,
        "value_number": claim.value_number,
        "value_text": claim.value_text,
    }


DEFAULT_RETRIES = 2


@dataclass
class Prepared:
    """An item's pages loaded into a throwaway store, with claims extracted and relations found."""

    store: ClaimStore
    snapshot_id: int
    page_of_doc: dict[str, str]  # doc_id -> the item's own page id ("a" / "b")
    extraction: ExtractionSummary
    detection: DetectSummary


def prepare_item(
    item: ItemRow,
    model: Any,
    *,
    retries: int = DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> Prepared:
    """Load an item's pages, extract claims and detect relations. Only the item's spec is used."""
    pages = item.spec["pages"]
    store = ClaimStore(":memory:")
    ingest = store.ingest_pages(f"item-{item.item_id[:12]}", [(p["url"], p["text"]) for p in pages])
    page_of_doc: dict[str, str] = {}
    for stored in store.pages(ingest.snapshot_id):
        for page in pages:
            if page["url"] == stored.url:
                page_of_doc[stored.doc_id] = page["id"]
    extraction = run_extraction(store, ingest.snapshot_id, model, retries=retries, sleep=sleep)
    detection, _ = run_detection(
        store, extraction.run_id, ingest.snapshot_id, model, retries=retries, sleep=sleep
    )
    return Prepared(store, ingest.snapshot_id, page_of_doc, extraction, detection)


def run_item(
    item: ItemRow,
    model: Any,
    *,
    retries: int = DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """The prediction for one item. Only the item's spec is used."""
    prepared = prepare_item(item, model, retries=retries, sleep=sleep)
    store, page_of_doc = prepared.store, prepared.page_of_doc
    extraction, detection = prepared.extraction, prepared.detection
    claims = {c.claim_id: c for c in store.claims(extraction.run_id)}
    relations: list[dict[str, Any]] = []
    for row in store.conn.execute(
        "SELECT kind, ordering_basis, claim_a, claim_b FROM relations WHERE status = 'verified'"
        " ORDER BY relation_id"
    ):
        a, b = claims[row["claim_a"]], claims[row["claim_b"]]
        if row["kind"] == "supersedes":  # claim_a is the newer claim, claim_b the older
            relations.append(
                {
                    "kind": "supersedes",
                    "basis": row["ordering_basis"],
                    "newer": _claim_json(a, page_of_doc),
                    "older": _claim_json(b, page_of_doc),
                }
            )
        else:
            relations.append(
                {
                    "kind": row["kind"],
                    "basis": row["ordering_basis"],
                    "claims": [_claim_json(a, page_of_doc), _claim_json(b, page_of_doc)],
                }
            )
    store.close()
    unfinished = detection.failed > 0 or extraction.pages_failed > 0
    return {
        "item_id": item.item_id,
        # UNKNOWN, not a result: a pair or page that failed was never decided. Such an item is
        # retried on resume and is not counted as proof of anything when scored.
        "status": "unknown" if unfinished else "complete",
        "extraction": {
            "pages_ok": extraction.pages_ok,
            "pages_failed": extraction.pages_failed,
            "guard_blocked": extraction.pages_guard_blocked,
            "proposals": extraction.proposals,
            "accepted": extraction.accepted,
        },
        "detection": {
            "pairs": detection.pairs,
            "supersedes": detection.supersedes,
            "contradicts": detection.contradicts,
            "unrelated": detection.unrelated,
            "downgraded": detection.downgraded,
            "rejected": detection.rejected,
            "guard_blocked": detection.guard_blocked,
            "failed": detection.failed,
            "reasons": detection.reasons,
        },
        "tokens": {
            "in": extraction.prompt_tokens + detection.prompt_tokens,
            "out": extraction.completion_tokens + detection.completion_tokens,
        },
        "relations": relations,
    }


def is_unknown(prediction: dict[str, Any]) -> bool:
    """True if the item did not finish. Older files have no status, so judge by the counts."""
    status = prediction.get("status")
    if status is not None:
        return bool(status != "complete")
    failed = prediction.get("detection", {}).get("failed", 0)
    pages_failed = prediction.get("extraction", {}).get("pages_failed", 0)
    return bool(failed or pages_failed)


def parse_predictions(path: Path, raw: bytes) -> tuple[dict[str, dict[str, Any]], int]:
    """Predictions (the last line for an item wins) and how many BYTES of `raw` are whole
    lines. Bytes after the final newline are an interrupted write and are ignored; a bad
    line anywhere else is an error, never skipped silently."""
    whole = raw[: raw.rfind(b"\n") + 1]
    lines = whole.decode("utf-8").split("\n")
    lines.pop()  # the empty text after the last newline
    loaded: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            loaded[row["item_id"]] = row
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}: line {number} is not a valid prediction") from exc
    return loaded, len(whole)


def check_provenance(out_path: Path, meta: dict[str, Any] | None, has_content: bool) -> None:
    sidecar = out_path.with_name(out_path.name + ".meta.json")
    if meta is None:
        if sidecar.exists():
            raise ValueError(
                f"{out_path} has a provenance record ({sidecar.name}); pass the same settings"
            )
        return
    if sidecar.exists() and has_content:
        try:
            recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(
                f"the provenance record {sidecar.name} is unreadable ({exc}); use a new --out"
            ) from exc
        if recorded != meta:
            raise ValueError(
                f"{out_path} was produced with different settings than this run ({sidecar.name}); "
                "resuming would mix them. Use a new --out."
            )
    elif has_content:
        raise ValueError(
            f"{out_path} already has predictions but no provenance record ({sidecar.name}); "
            "use a new --out."
        )
    else:  # no predictions yet: any settings file left by a crashed start is replaced
        text = json.dumps(meta, indent=2, sort_keys=True) + "\n"
        temporary = sidecar.with_name(sidecar.name + ".tmp")
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, sidecar)  # whole or not at all


def run_resumable(
    items: list[ItemRow],
    produce: Callable[[ItemRow], dict[str, Any]],
    out_path: Path,
    *,
    limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    """Append one JSON line per item (made by `produce`) to `out_path`. An item is done only if it
    finished (no failed pair, page or answer); unfinished ones are run again on resume, and the
    later line wins. `meta` is written beside the file and must match on resume. Returns the number
    of items run now."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    existing = out_path.read_bytes() if out_path.exists() else b""
    loaded, whole = parse_predictions(out_path, existing) if existing else ({}, 0)
    # Check the settings BEFORE touching the file: a refused resume must change nothing.
    check_provenance(out_path, meta, bool(existing))
    if existing:
        if whole < len(existing):  # repair an interrupted write before appending after it
            with out_path.open("r+b") as handle:
                handle.truncate(whole)
        done = {item_id for item_id, row in loaded.items() if not is_unknown(row)}
    todo = [item for item in items if item.item_id not in done]
    if limit is not None:
        todo = todo[:limit]
    with out_path.open("a", encoding="utf-8", newline="\n") as handle:
        for number, item in enumerate(todo, start=1):
            handle.write(json.dumps(produce(item), ensure_ascii=False) + "\n")
            handle.flush()
            if progress is not None:
                progress(number, len(todo), item.item_id)
    return len(todo)


def run_items(
    items: list[ItemRow],
    model: Any,
    out_path: Path,
    *,
    limit: int | None = None,
    retries: int = DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    """Run the pipeline on items and append one JSON line per item to `out_path` (resumable; see
    `run_resumable`). Returns the number of items run now."""
    return run_resumable(
        items,
        lambda item: run_item(item, model, retries=retries, sleep=sleep),
        out_path,
        limit=limit,
        progress=progress,
        meta=meta,
    )


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    loaded, _whole = parse_predictions(path, path.read_bytes())
    return loaded
