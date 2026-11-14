"""Score predictions against sealed labels.

The unit of correctness is a CUT: a verified `supersedes` relation the pipeline asserts. A cut is
correct only if its older claim is the stale span the label names, its newer claim is on the
update page, and the newer value is the label's current value. Every other cut, including a cut
on a clean item or on a pair that is really undecidable, is wrong. A wrong cut is the costly error
(it hides a true fact), so precision is reported before recall.

Items from one source page are not independent, so every interval resamples whole clusters.

Dev labels are readable at any time; test and held-out labels need the freeze (EvalLocked).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from currant.evalset import ItemRow
from currant.harness.run_items import is_unknown


def overlaps(span_a: tuple[int, int], span_b: tuple[int, int]) -> bool:
    return min(span_a[1], span_b[1]) - max(span_a[0], span_b[0]) > 0


@dataclass(frozen=True)
class Outcome:
    item_id: str
    cluster: str
    scenario: str
    cuts: int  # verified supersedes relations the pipeline asserted on this item
    correct_cuts: int
    cut_on_stale: bool  # some cut removes the stale span (right or wrong direction)
    contested_on_stale: bool  # a verified contradicts relation involves the stale span
    ran: bool  # the pipeline produced a prediction at all
    unknown: bool = False  # a pair or page failed: undecided, not a success


def score_item(item: ItemRow, label: dict[str, Any], prediction: dict[str, Any] | None) -> Outcome:
    scenario = label["scenario"]
    if prediction is None:
        return Outcome(item.item_id, item.cluster_id, scenario, 0, 0, False, False, False)
    stale_page = label["stale_page_id"]
    stale = (label["stale_span"][0], label["stale_span"][1])
    cuts = correct = 0
    cut_on_stale = contested = False
    for relation in prediction["relations"]:
        if relation["kind"] == "supersedes":
            cuts += 1
            older, newer = relation["older"], relation["newer"]
            on_stale = older["page"] == stale_page and overlaps(
                (older["start"], older["end"]), stale
            )
            cut_on_stale = cut_on_stale or on_stale
            wanted = label["current_value_number"]
            right = (
                scenario in ("supersedes_explicit", "supersedes_dated")
                and on_stale
                and newer["page"] == label["update_page_id"]
                and newer["value_number"] is not None
                and wanted is not None
                and math.isclose(newer["value_number"], wanted)
            )
            correct += bool(right)
        elif relation["kind"] == "contradicts":
            contested = contested or any(
                c["page"] == stale_page and overlaps((c["start"], c["end"]), stale)
                for c in relation["claims"]
            )
    return Outcome(
        item.item_id,
        item.cluster_id,
        scenario,
        cuts,
        correct,
        cut_on_stale,
        contested,
        True,
        is_unknown(prediction),
    )


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def pooled(outcomes: list[Outcome]) -> dict[str, float | None]:
    sup = [o for o in outcomes if o.scenario in ("supersedes_explicit", "supersedes_dated")]
    # An item with an undecided pair proves nothing about harm or abstention, so it is left
    # out of those rates (and counts as a miss for recall, which keeps it in `sup`).
    imp = [o for o in outcomes if o.scenario == "contested_implicit" and o.ran and not o.unknown]
    clean = [o for o in outcomes if o.scenario == "clean" and o.ran and not o.unknown]
    cuts = sum(o.cuts for o in outcomes)
    return {
        "precision": _ratio(sum(o.correct_cuts for o in outcomes), cuts),
        "recall": _ratio(sum(1 for o in sup if o.correct_cuts > 0), len(sup)),
        "implicit_contested": _ratio(sum(o.contested_on_stale for o in imp), len(imp)),
        "implicit_false_cut": _ratio(sum(o.cuts > 0 for o in imp), len(imp)),
        "clean_false_cut": _ratio(sum(o.cuts > 0 for o in clean), len(clean)),
        "clean_false_contested": _ratio(sum(o.contested_on_stale for o in clean), len(clean)),
        "cuts": float(cuts),
    }


def cluster_bootstrap(
    outcomes: list[Outcome], *, rounds: int = 2000, seed: int = 0
) -> dict[str, tuple[float, float] | None]:
    """95% intervals from resampling whole source-page clusters."""
    by_cluster: dict[str, list[Outcome]] = defaultdict(list)
    for outcome in outcomes:
        by_cluster[outcome.cluster].append(outcome)
    clusters = sorted(by_cluster)
    rng = random.Random(seed)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(rounds):
        drawn = [o for c in (rng.choice(clusters) for _ in clusters) for o in by_cluster[c]]
        for name, value in pooled(drawn).items():
            if value is not None and name != "cuts":
                samples[name].append(value)
    intervals: dict[str, tuple[float, float] | None] = {}
    names = (
        "precision",
        "recall",
        "implicit_contested",
        "implicit_false_cut",
        "clean_false_cut",
        "clean_false_contested",
    )
    for name in names:
        values = sorted(samples[name])
        intervals[name] = (
            (
                values[int(0.025 * len(values))],
                values[min(len(values) - 1, int(0.975 * len(values)))],
            )
            if len(values) > 20
            else None
        )
    return intervals


def summarize(outcomes: list[Outcome]) -> dict[str, Any]:
    by_scenario: dict[str, dict[str, Any]] = {}
    for scenario in sorted({o.scenario for o in outcomes}):
        group = [o for o in outcomes if o.scenario == scenario]
        by_scenario[scenario] = {
            "items": len(group),
            "ran": sum(o.ran for o in group),
            "correct_cut": sum(1 for o in group if o.correct_cuts > 0),
            "any_cut": sum(1 for o in group if o.cuts > 0),
            "contested": sum(o.contested_on_stale for o in group),
            "unknown": sum(o.unknown for o in group),
        }
    return {
        "items": len(outcomes),
        "clusters": len({o.cluster for o in outcomes}),
        "unknown": sum(o.unknown for o in outcomes),
        "metrics": pooled(outcomes),
        "intervals_95_by_cluster": cluster_bootstrap(outcomes),
        "by_scenario": by_scenario,
    }
