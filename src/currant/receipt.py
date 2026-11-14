"""Receipts: a record of exactly what a model was shown, and a replay that proves it.

A receipt lists the mode, the extraction and relation runs (model and prompt version), the corpus
hash, the retrieved pages, every action taken with the verbatim quotes behind it, and the SHA-256
of the context text. It holds no clock time, so the same inputs give the same receipt byte for
byte. `receipt_id` is the hash of everything else.

`replay` never trusts the receipt. It re-checks, from the store:

1. `receipt_id` really is the hash of the body (catches any edit that did not re-seal it);
2. the runs exist and used the model and prompt version the receipt names, on the corpus it names;
3. every page's url belongs to that page in the corpus, and its text hashes to its id;
4. **re-grounding** with the same pages, mode and runs gives the same actions and the same context
   hash. A forged receipt whose id was recomputed still fails here, because the store, not the
   receipt, decides what is verified (and `ground` re-checks every quote verbatim, and that every
   relation is verified, each time it runs);

Anything it cannot confirm is a problem. A malformed receipt is a failure with a reason, never an
exception and never a pass (default-deny).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from currant.ground import Grounded, Retrieved, ground
from currant.store import ClaimStore, StoreError

RECEIPT_VERSION = 1
_REQUIRED = (
    "receipt_version",
    "receipt_id",
    "question",
    "mode",
    "corpus",
    "runs",
    "documents",
    "actions",
    "context_sha256",
    "context_chars",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def receipt_id(body: dict[str, Any]) -> str:
    """The hash of a receipt body (everything except `receipt_id` itself)."""
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _as_int(value: object) -> int:
    """Run ids are plain integers. Strings, floats and booleans are refused, not coerced."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("a run id must be an integer")
    return value


def _run_entry(store: ClaimStore, run_id: int) -> dict[str, Any]:
    meta = store.run_meta(run_id)
    return {"run_id": meta.run_id, "model": meta.model, "prompt_version": meta.prompt_version}


def build_receipt(
    store: ClaimStore,
    grounded: Grounded,
    *,
    question: str,
    extract_run_id: int,
    relate_run_id: int,
) -> dict[str, Any]:
    extract = store.run_meta(extract_run_id)
    body: dict[str, Any] = {
        "receipt_version": RECEIPT_VERSION,
        "question": question,
        "mode": grounded.mode,
        "corpus": {"snapshot_date": extract.snapshot_date, "corpus_hash": extract.corpus_hash},
        "runs": {
            "extract": _run_entry(store, extract_run_id),
            "relate": _run_entry(store, relate_run_id),
        },
        "documents": [{"doc_id": d.doc_id, "url": d.url} for d in grounded.documents],
        "actions": [a.to_dict() for a in grounded.actions],
        "context_sha256": grounded.context_sha256,
        "context_chars": len(grounded.context),
    }
    return {**body, "receipt_id": receipt_id(body)}


@dataclass
class ReplayResult:
    ok: bool = False
    problems: list[str] = field(default_factory=list)
    context_sha256: str | None = None  # recomputed by re-grounding, when that got far enough


def _fail(result: ReplayResult, problem: str) -> ReplayResult:
    result.ok = False
    result.problems.append(problem)
    return result


def replay(store: ClaimStore, receipt: object) -> ReplayResult:
    result = ReplayResult()
    if not isinstance(receipt, dict):
        return _fail(result, "the receipt is not a JSON object")
    missing = [key for key in _REQUIRED if key not in receipt]
    if missing:
        return _fail(result, f"missing fields: {', '.join(missing)}")
    if receipt["receipt_version"] != RECEIPT_VERSION:
        return _fail(result, f"unsupported receipt_version {receipt['receipt_version']!r}")
    problems = result.problems

    body = {k: v for k, v in receipt.items() if k != "receipt_id"}
    try:
        if receipt_id(body) != receipt["receipt_id"]:
            problems.append("receipt_id does not match the receipt body")
    except (TypeError, ValueError):
        problems.append("receipt_id cannot be recomputed (the body is not plain JSON)")

    try:
        runs, corpus = receipt["runs"], receipt["corpus"]
        extract_id = _as_int(runs["extract"]["run_id"])
        relate_id = _as_int(runs["relate"]["run_id"])
        documents = [Retrieved(str(d["doc_id"]), str(d["url"])) for d in receipt["documents"]]
        mode = receipt["mode"]
        if not isinstance(mode, str) or not isinstance(receipt["actions"], list):
            raise TypeError("mode or actions has the wrong type")
        for stage, run_id in (("extract", extract_id), ("relate", relate_id)):
            meta = store.run_meta(run_id)
            expected = runs[stage]
            if meta.stage != stage:
                problems.append(f"run {run_id} is a {meta.stage} run, not {stage}")
            if (meta.model, meta.prompt_version) != (expected["model"], expected["prompt_version"]):
                problems.append(f"the {stage} run used a different model or prompt version")
        extract_meta = store.run_meta(extract_id)
        if (extract_meta.snapshot_date, extract_meta.corpus_hash) != (
            corpus["snapshot_date"],
            corpus["corpus_hash"],
        ):
            problems.append("the corpus differs from the one in the receipt")
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, StoreError) as exc:
        problems.append(f"the receipt could not be read ({type(exc).__name__}: {exc})")
        return _fail(result, "stopping: the runs or documents cannot be resolved")

    try:
        for doc in documents:
            text = store.document_text(doc.doc_id)
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != doc.doc_id:
                problems.append(f"document {doc.doc_id[:12]} does not hash to its id")
        regrounded = ground(
            store, documents, mode=mode, extract_run_id=extract_id, relate_run_id=relate_id
        )
    except (ValueError, StoreError) as exc:
        return _fail(result, f"re-grounding failed: {exc}")
    result.context_sha256 = regrounded.context_sha256
    if [a.to_dict() for a in regrounded.actions] != receipt["actions"]:
        problems.append("re-grounding from the store produced different actions")
    if regrounded.context_sha256 != receipt["context_sha256"]:
        problems.append("the recomputed context hash does not match the receipt")
    if len(regrounded.context) != receipt["context_chars"]:
        problems.append("the recomputed context length does not match the receipt")

    result.ok = not problems
    return result
