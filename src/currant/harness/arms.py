"""The arms comparison: what a model answers when shown different versions of the same context.

For one evaluation item the runner builds a throwaway store from the item's two pages, extracts
claims and finds relations (the offline stage), then for each retrieval depth `k` it takes the BM25
top-k pages of the item's question and shows the model the context each arm produces:

* `baseline`     the retrieved pages as they are
* `redact`       detected stale sentences cut
* `annotate`     detected stale sentences kept and marked with what replaced them
* `pull`         the newer evidence added when only the stale page was retrieved
* `redact_pull`  both
* `random_cut`   as many randomly chosen claim sentences cut as `redact` cut (a control: does
                 cutting anything at all explain the effect?)
* `oracle_pull`  `pull` driven by the labels instead of by detection: the upper bound on what
                 perfect detection could give, reported separately and never as the headline. It
                 needs hints built out of labels and passed in; this module never reads them.

This module never reads a label. It records what it did (which spans each arm cut, which pages were
retrieved, a hash of each context) and what the model answered. Strata, correctness and harm are
decided later by the scorer, which is the only place labels are read. An item whose pipeline or any
answer call failed is UNKNOWN: it is retried on resume and never counted as a result.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from currant.evalset import ItemRow
from currant.ground import Action, Ref, Retrieved, ground, render
from currant.harness.answer import AnswerModel, ask
from currant.harness.run_items import DEFAULT_RETRIES, prepare_item, run_resumable
from currant.retrieve import PageIndex

ARMS = ("baseline", "redact", "annotate", "pull", "redact_pull", "random_cut")
GROUND_MODE = {
    "baseline": "baseline",
    "redact": "redact",
    "annotate": "annotate",
    "pull": "pull",
    "redact_pull": "redact_pull",
}
ORACLE_ARM = "oracle_pull"
ALL_ARMS = (*ARMS, ORACLE_ARM)
DEFAULT_KS = (1, 2)
RETRIEVAL_VERSION = "bm25-fts5-v1"


@dataclass(frozen=True)
class OracleHint:
    """Where the truth is for one item, made from its label by code that is allowed to read labels
    (the command line). The arms runner only uses it."""

    stale_page: str
    stale_start: int
    stale_end: int
    stale_quote: str
    update_page: str
    update_quote: str


def _oracle_pull(
    hint: OracleHint | None,
    store: Any,
    snapshot_id: int,
    retrieved: list[Retrieved],
    page_of_doc: dict[str, str],
) -> list[Action]:
    """Pull the true newer evidence when the stale page was retrieved and the update was not."""
    if hint is None:
        return []
    doc_of_page = {page: doc for doc, page in page_of_doc.items()}
    stale_doc, update_doc = doc_of_page.get(hint.stale_page), doc_of_page.get(hint.update_page)
    in_context = {r.doc_id for r in retrieved}
    if stale_doc is None or update_doc is None:
        return []
    if stale_doc not in in_context or update_doc in in_context:
        return []
    text = store.document_text(update_doc)
    start = text.find(hint.update_quote)
    if start < 0:
        return []
    target = Ref(
        stale_doc, store.url_of(snapshot_id, stale_doc),
        hint.stale_start, hint.stale_end, hint.stale_quote,
    )  # fmt: skip
    source = Ref(
        update_doc, store.url_of(snapshot_id, update_doc),
        start, start + len(hint.update_quote), hint.update_quote,
    )  # fmt: skip
    return [Action("pull", "oracle", target, source, ())]


def _random_cuts(
    claims_in_context: list[Any], retrieved: list[Retrieved], count: int, rng: random.Random
) -> list[Action]:
    """`count` randomly chosen claim sentences, cut. Same granularity as the detector's cuts."""
    url_of = {r.doc_id: r.url for r in retrieved}
    candidates = sorted(claims_in_context, key=lambda c: c.claim_id)
    chosen = rng.sample(candidates, min(count, len(candidates)))
    return [
        Action(
            "redact",
            "random",
            Ref(c.doc_id, url_of[c.doc_id], c.start_char, c.end_char, c.quote),
            Ref(c.doc_id, url_of[c.doc_id], c.start_char, c.end_char, c.quote),
            (),
        )
        for c in chosen
    ]


def _action_record(action: Action, page_of_doc: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "page": page_of_doc.get(action.target.doc_id),
        "start": action.target.start,
        "end": action.target.end,
        "source_page": page_of_doc.get(action.source.doc_id),
    }


def run_arms_item(
    item: ItemRow,
    pipeline_model: Any,
    answer_model: AnswerModel,
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    arms: tuple[str, ...] = ARMS,
    repeats: int = 1,
    seed: int = 0,
    retries: int = DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    oracle: Callable[[str], OracleHint | None] | None = None,
) -> dict[str, Any]:
    """Every (k, arm, repeat) answer for one item. Only the item's spec is used."""
    for arm in arms:
        if arm not in ALL_ARMS:
            raise ValueError(f"unknown arm {arm!r}; choose from {', '.join(ALL_ARMS)}")
    if ORACLE_ARM in arms and oracle is None:
        raise ValueError(f"the {ORACLE_ARM} arm needs oracle hints built out of labels")
    prepared = prepare_item(item, pipeline_model, retries=retries, sleep=sleep)
    store, page_of_doc = prepared.store, prepared.page_of_doc
    extraction, detection = prepared.extraction, prepared.detection
    record: dict[str, Any] = {
        "item_id": item.item_id,
        "status": "complete",
        "pipeline": {
            "pages_failed": extraction.pages_failed,
            "pairs": detection.pairs,
            "pairs_failed": detection.failed,
            "supersedes": detection.supersedes,
            "contradicts": detection.contradicts,
        },
        "runs": [],
    }
    if extraction.pages_failed or detection.failed:
        record["status"] = "unknown"  # the offline stage did not finish: nothing to compare
        record["reason"] = "the extraction or relation step left something undecided"
        store.close()
        return record

    question: str = item.spec["question"]
    claims = store.claims(extraction.run_id)
    runs: list[dict[str, Any]] = record["runs"]
    with PageIndex(store, prepared.snapshot_id) as index:
        for k in ks:
            retrieved = index.search(question, k=k)
            if not retrieved:
                runs.append({"k": k, "arm": "*", "repeat": 0, "status": "no_retrieval"})
                continue
            page_ids = [page_of_doc.get(r.doc_id) for r in retrieved]
            doc_ids = {r.doc_id for r in retrieved}
            texts = {r.doc_id: store.document_text(r.doc_id) for r in retrieved}
            detector_cuts = sum(
                1
                for a in ground(
                    store,
                    retrieved,
                    mode="redact",
                    extract_run_id=extraction.run_id,
                    relate_run_id=detection.run_id,
                ).actions
                if a.kind == "redact"
            )
            digest = hashlib.sha256(f"{seed}|{item.item_id}|{k}".encode()).hexdigest()
            rng = random.Random(int(digest, 16))
            for arm in arms:
                if arm == "random_cut":
                    actions = _random_cuts(
                        [c for c in claims if c.doc_id in doc_ids and c.stance == "current"],
                        retrieved,
                        detector_cuts,
                        rng,
                    )
                    context = render(tuple(retrieved), texts, actions)
                elif arm == ORACLE_ARM:
                    assert oracle is not None
                    actions = _oracle_pull(
                        oracle(item.item_id), store, prepared.snapshot_id, retrieved, page_of_doc
                    )
                    context = render(tuple(retrieved), texts, actions)
                else:
                    grounded = ground(
                        store,
                        retrieved,
                        mode=GROUND_MODE[arm],
                        extract_run_id=extraction.run_id,
                        relate_run_id=detection.run_id,
                    )
                    actions, context = grounded.actions, grounded.context
                sha = hashlib.sha256(context.encode("utf-8")).hexdigest()
                for repeat in range(repeats):
                    result = ask(
                        answer_model,
                        question,
                        context,
                        repeat=repeat,
                        retries=retries,
                        sleep=sleep,
                    )
                    runs.append(
                        {
                            "k": k,
                            "arm": arm,
                            "repeat": repeat,
                            "retrieved": page_ids,
                            "actions": [_action_record(a, page_of_doc) for a in actions],
                            "context_sha256": sha,
                            "context_chars": len(context),
                            "status": result.status,
                            "reason": result.reason,
                            "answer": asdict(result.answer) if result.answer else None,
                            "tokens": {"in": result.tokens_in, "out": result.tokens_out},
                            "request_id": result.request_id,
                        }
                    )
    store.close()
    if any(r["status"] == "failed" for r in runs):
        record["status"] = "unknown"  # an unanswered question is undecided, never a wrong answer
        record["reason"] = "an answer call failed"
    return record


def run_arms(
    items: list[ItemRow],
    pipeline_model: Any,
    answer_model: AnswerModel,
    out_path: Path,
    *,
    limit: int | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
    arms: tuple[str, ...] = ARMS,
    repeats: int = 1,
    seed: int = 0,
    retries: int = DEFAULT_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
    meta: dict[str, Any] | None = None,
    oracle: Callable[[str], OracleHint | None] | None = None,
) -> int:
    """Run the arms on items, one JSON line per item, resumable (see `run_resumable`)."""
    return run_resumable(
        items,
        lambda item: run_arms_item(
            item,
            pipeline_model,
            answer_model,
            ks=ks,
            arms=arms,
            repeats=repeats,
            seed=seed,
            retries=retries,
            sleep=sleep,
            oracle=oracle,
        ),
        out_path,
        limit=limit,
        progress=progress,
        meta=meta,
    )
