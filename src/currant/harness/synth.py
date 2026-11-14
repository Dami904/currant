"""Synthetic evaluation items: supersessions injected into real pages, with known truth.

Each item is built from one real page and one number in it. An update page states a changed
number in one of three forms, and the label records what the correct answer is:

* `supersedes_explicit`: the update says it replaces the previous value. Correct answer: the new
  value is current, the old span is stale (state CANON).
* `supersedes_dated`: the stale page carries a "Last updated" date and the update is a dated
  changelog entry that is later. Correct answer: the new value is current (state CANON).
* `contested_implicit`: the update restates a different number with no date and no wording about
  replacing anything. Nothing establishes which is newer, so the correct answer is CONTESTED.
* `clean`: nothing is stale. The second page is an unrelated real page. Correct: the original value
  stands and nothing is cut. These controls measure harm.

What the pipeline sees (`spec`) is two neutral pages and a question. The scenario, the expected
state and the values live only in the sealed label. Source claims come from the claim store, so
facts the extractor already found are over-represented: stale-side recall on these items is
optimistic, and the held-out real items are the honest measure.

Every item built from one source page shares a cluster, so it shares a split. Items from one page
are not independent, so the effective sample size is the number of source pages, not the number
of items: any interval must resample by cluster.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from currant.evalset import EvalError, EvalStore
from currant.store import ClaimRow, ClaimStore

SUPERSEDE_TEMPLATES = ("supersedes_explicit", "supersedes_dated", "contested_implicit")
CLEAN = "clean"
SYNTHETIC_URL = "https://synthetic.invalid/update"
NUMERIC_TYPES = frozenset({"number", "count", "money", "duration"})
_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
MIN_QUOTE, MAX_QUOTE = 25, 300
UNKNOWN_URL = "https://unknown.invalid/"


@dataclass(frozen=True)
class Target:
    """A claim we can safely rewrite: one clean sentence with exactly one number."""

    claim: ClaimRow
    url: str
    text: str
    token: str
    token_start: int  # offset of the number inside the claim's quote


@dataclass
class SyntheticSummary:
    items: int = 0
    by_scenario: Counter[str] = field(default_factory=Counter)
    by_split: Counter[str] = field(default_factory=Counter)
    commit_root: str = ""


def _parse(token: str) -> float:
    return float(token.replace(",", ""))


def eligible_targets(store: ClaimStore, run_id: int) -> list[Target]:
    """Claims from `run_id` that are current, numeric, and sit in a single-line sentence whose
    only number is the claimed value. Sorted by claim id, so selection is reproducible."""
    urls = {
        row["doc_id"]: row["url"]
        for row in store.conn.execute(
            "SELECT doc_id, MIN(url) AS url FROM snapshot_pages GROUP BY doc_id"
        )
    }
    targets: list[Target] = []
    for claim in store.claims(run_id):
        if claim.stance != "current" or claim.value_type not in NUMERIC_TYPES:
            continue
        if claim.value_number is None or not MIN_QUOTE <= len(claim.quote) <= MAX_QUOTE:
            continue
        if "\n" in claim.quote:
            continue
        tokens = list(_NUMBER.finditer(claim.quote))
        if len(tokens) != 1 or not math.isclose(_parse(tokens[0].group()), claim.value_number):
            continue
        targets.append(
            Target(claim, urls.get(claim.doc_id, "https://unknown.invalid/"),
                   store.document_text(claim.doc_id), tokens[0].group(), tokens[0].start())
        )  # fmt: skip
    return sorted(targets, key=lambda t: t.claim.claim_id)


def eligible_controls(store: ClaimStore, run_id: int) -> list[Target]:
    """Claims usable as clean controls. Nothing is rewritten, so any current claim with a clean
    single-line sentence will do, numeric or not: far more than can be rewritten."""
    urls = {
        row["doc_id"]: row["url"]
        for row in store.conn.execute(
            "SELECT doc_id, MIN(url) AS url FROM snapshot_pages GROUP BY doc_id"
        )
    }
    controls = [
        Target(c, urls.get(c.doc_id, UNKNOWN_URL), store.document_text(c.doc_id), "", -1)
        for c in store.claims(run_id)
        if c.stance == "current" and MIN_QUOTE <= len(c.quote) <= MAX_QUOTE and "\n" not in c.quote
    ]
    return sorted(controls, key=lambda t: t.claim.claim_id)


def new_value(old: float, *, percent: bool, rng: random.Random) -> float:
    """A different, plausible value: scaled, never equal, integral if the old one was."""
    options = [old * 2, old * 3, old * 5, old * 10, old / 2]
    if float(old).is_integer():
        options = [o for o in options if float(o).is_integer()]
    if percent:
        options = [o for o in options if o <= 100]
    options = [o for o in options if o > 0 and not math.isclose(o, old)]
    if not options:
        return old + 1 if not percent or old < 100 else old - 1
    return rng.choice(options)


def format_like(old_token: str, value: float) -> str:
    """Write `value` the way `old_token` was written: same decimals, same thousands commas."""
    decimals = len(old_token.split(".")[1]) if "." in old_token else 0
    return f"{value:,.{decimals}f}" if "," in old_token else f"{value:.{decimals}f}"


def _cluster_id(doc_id: str) -> str:
    # Hashed so the cluster id (which items() exposes) reveals nothing about the scenario.
    return "syn-" + hashlib.sha256(f"source:{doc_id}".encode()).hexdigest()[:16]


def _rewrite(target: Target, rng: random.Random) -> tuple[str, float]:
    """The claim's sentence with its number changed: (new sentence, new value)."""
    quote, token = target.claim.quote, target.token
    after = quote[target.token_start + len(token) : target.token_start + len(token) + 1]
    value = new_value(_parse(token), percent=(after == "%"), rng=rng)
    new_token = format_like(token, value)
    sentence = quote[: target.token_start] + new_token + quote[target.token_start + len(token) :]
    return sentence, _parse(new_token)


def build_item(
    target: Target, scenario: str, rng: random.Random, distractor: tuple[str, str] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(spec, label) for one item. The spec carries pipeline inputs only. For a clean control,
    `distractor` is the (url, text) of another real page, kept under its own real URL."""
    claim = target.claim
    old_number = claim.value_number
    stale_text = target.text
    stale_start = claim.start_char
    update_url, update_text = f"{SYNTHETIC_URL}/{rng.randrange(10**8):08d}.md", ""
    label: dict[str, Any] = {"scenario": scenario, "stale_value_number": old_number}

    if scenario == CLEAN:
        assert distractor is not None
        update_url, update_text = distractor
        label.update(
            expected_state="CANON", current_value_number=old_number,
            current_value_text=claim.value_text, update_quote=None, ordering_basis="none",
        )  # fmt: skip
    else:
        sentence, new_number = _rewrite(target, rng)
        if scenario == "supersedes_explicit":
            update_text = (
                f"# Update notice\n\n{sentence}\n\n"
                f"This replaces the previous value of {target.token} in earlier documentation.\n"
            )
            state, current, basis = "CANON", new_number, "explicit_text"
        elif scenario == "supersedes_dated":
            old_date = date(2026, 1, 1) + timedelta(days=rng.randrange(180))
            new_date = date(2026, 8, 1) + timedelta(days=rng.randrange(90))
            prefix = f"Last updated: {old_date.isoformat()}\n\n"
            stale_text, stale_start = prefix + stale_text, stale_start + len(prefix)
            update_text = f"## Changelog\n\n**{new_date.isoformat()}**\n\n* {sentence}\n"
            state, current, basis = "CANON", new_number, "dated"
        elif scenario == "contested_implicit":
            update_text = f"# Reference\n\n{sentence}\n"
            state, current, basis = "CONTESTED", None, "none"
        else:
            raise EvalError(f"unknown scenario {scenario!r}")
        label.update(
            expected_state=state, current_value_number=current, update_quote=sentence,
            ordering_basis=basis,
        )  # fmt: skip

    pages = [
        {"id": "a", "url": target.url, "text": stale_text},
        {"id": "b", "url": update_url, "text": update_text},
    ]
    stale_id = "a"
    if rng.random() < 0.5:  # the stale page is not always first
        pages = [{**pages[1], "id": "a"}, {**pages[0], "id": "b"}]
        stale_id = "b"
    label.update(
        stale_page_id=stale_id,
        update_page_id=None if scenario == CLEAN else ("a" if stale_id == "b" else "b"),
        stale_quote=claim.quote,
        stale_span=[stale_start, stale_start + len(claim.quote)],
    )
    spec = {"question": f"What is the {claim.attribute} for {claim.subject}?", "pages": pages}
    return spec, label


def generate(
    store: ClaimStore,
    run_id: int,
    evals: EvalStore,
    *,
    seed: int,
    n_supersede: int = 99,
    n_clean: int = 100,
) -> SyntheticSummary:
    """Create `n_supersede` injected-supersession items (spread over the three templates) and
    `n_clean` controls in `evals`. Deterministic for a given store, run and seed."""
    rng = random.Random(seed)
    pool = eligible_targets(store, run_id)
    if len(pool) < n_supersede:
        raise EvalError(
            f"only {len(pool)} rewritable claims; {n_supersede} supersession items were requested"
        )
    rng.shuffle(pool)
    supersede = pool[:n_supersede]
    used = {t.claim.claim_id for t in supersede}
    controls = [t for t in eligible_controls(store, run_id) if t.claim.claim_id not in used]
    if len(controls) < n_clean:
        raise EvalError(f"only {len(controls)} eligible controls; {n_clean} were requested")
    rng.shuffle(controls)
    controls = controls[:n_clean]

    plan = [(t, SUPERSEDE_TEMPLATES[i % 3]) for i, t in enumerate(supersede)]
    plan += [(t, CLEAN) for t in controls]
    pages = {t.claim.doc_id: (t.url, t.text) for t in (*pool, *controls)}
    doc_ids = sorted(pages)
    summary = SyntheticSummary()
    for target, scenario in plan:
        distractor: tuple[str, str] | None = None
        if scenario == CLEAN:
            other = rng.choice([d for d in doc_ids if d != target.claim.doc_id])
            distractor = pages[other]
        spec, label = build_item(target, scenario, rng, distractor)
        evals.add_item("synthetic", _cluster_id(target.claim.doc_id), spec, label)
        summary.items += 1
        summary.by_scenario[scenario] += 1
    for item in evals.items():
        summary.by_split[item.split] += 1
    summary.commit_root = evals.commit_root()
    return summary
