"""Score the arms comparison. This is where labels are read (dev labels only, until the freeze).

For every recorded answer it decides:

* the STRATUM from which pages were retrieved: `both`, `stale_only` (the case Currant is for: the
  newer page was not retrieved), `update_only`, `neither`, or `clean` for a control item;
* CORRECT by typed-value match. A resolvable item is right if the answer is the current value; an
  implicit pair (no evidence of order) is right only if the model says CONTESTED; a clean control is
  right if the answer is its only value;
* STALE STATED: it answered with the superseded value;
* STALE IN CONTEXT: the stale sentence survived into what the model was shown (a cut that touches
  it removes it; an annotation keeps it);
* CONTENT MISSING (clean items only): the control's own sentence was cut or never retrieved, the
  plan's definition of harm.

Each item is averaged over its repeats first, then arms are compared on the same items. Intervals
resample whole source-page clusters. A lift is reported with a paired bootstrap interval and an
exact McNemar test on the first repeat, and it only counts as an effect if it clears the baseline's
run-to-run spread, which is NOT measured (shown as `unmeasured`) when there is a single repeat.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from currant.evalset import ItemRow
from currant.harness.score import overlaps
from currant.harness.stats import mcnemar_exact, paired_cluster_bootstrap

RESOLVABLE = ("supersedes_explicit", "supersedes_dated")
BOOTSTRAP_ROUNDS = 2000


@dataclass(frozen=True)
class ArmOutcome:
    item_id: str
    cluster: str
    scenario: str
    k: int
    arm: str
    repeat: int
    stratum: str
    status: str
    correct: bool
    stale_stated: bool
    abstained: bool
    stale_in_context: bool
    content_missing: bool | None  # only for clean items
    # False when the label has no number to match (a clean control whose answer is a token
    # address, an identifier, a range): such an item cannot be right or wrong by typed value, so
    # it is left out of accuracy. Its harm measures still count.
    scorable: bool = True


def stratum_of(label: dict[str, Any], retrieved: list[str]) -> str:
    if label["scenario"] == "clean":
        return "clean"
    stale, update = label["stale_page_id"] in retrieved, label["update_page_id"] in retrieved
    if stale and update:
        return "both"
    if stale:
        return "stale_only"
    if update:
        return "update_only"
    return "neither"


def _stratum_with_group(label: dict[str, Any], retrieved: list[str]) -> str:
    """The stratum, split by whether an order exists. Resolvable items (a newer value exists) and
    implicit ones (the right answer is CONTESTED) respond to the arms in opposite ways, so pooling
    them hides what each arm does."""
    base = stratum_of(label, retrieved)
    if base == "clean":
        return base
    group = "resolvable" if label["scenario"] in RESOLVABLE else "implicit"
    return f"{base}/{group}"


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def _score_run(item: ItemRow, label: dict[str, Any], run: dict[str, Any]) -> ArmOutcome:
    scenario = label["scenario"]
    answer = run["answer"] if run["status"] == "ok" else None
    verdict = answer["verdict"] if answer else None
    value = answer["value"] if answer else None
    if scenario in RESOLVABLE or scenario == "clean":
        correct = verdict == "answer" and _close(value, label["current_value_number"])
    else:  # contested_implicit: nothing says which is current
        correct = verdict == "contested"
    stale_stated = (
        scenario != "clean" and verdict == "answer" and _close(value, label["stale_value_number"])
    )
    stale_span = (label["stale_span"][0], label["stale_span"][1])
    cut = any(
        a["kind"] == "redact"
        and a["page"] == label["stale_page_id"]
        and overlaps((a["start"], a["end"]), stale_span)
        for a in run["actions"]
    )
    present = label["stale_page_id"] in run["retrieved"] and not cut
    scorable = scenario == "contested_implicit" or label["current_value_number"] is not None
    return ArmOutcome(
        item.item_id,
        item.cluster_id,
        scenario,
        run["k"],
        run["arm"],
        run["repeat"],
        _stratum_with_group(label, run["retrieved"]),
        run["status"],
        bool(correct),
        bool(stale_stated),
        verdict in ("contested", "unknown"),
        present,
        (not present) if scenario == "clean" else None,
        scorable,
    )


def score_item_arms(
    item: ItemRow, label: dict[str, Any], record: dict[str, Any]
) -> list[ArmOutcome]:
    """Outcomes for one item's record. An unknown item, and a depth with no retrieved page, give
    none: they carry no information about the arms."""
    if record.get("status") != "complete":
        return []
    return [
        _score_run(item, label, run) for run in record["runs"] if run["status"] != "no_retrieval"
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _item_rate(by_item: dict[str, list[ArmOutcome]], pick: Callable[[ArmOutcome], float]) -> float:
    """Mean over items of the mean over each item's repeats."""
    return _mean([_mean([pick(o) for o in runs]) for runs in by_item.values()])


def summarize_arms(
    outcomes: list[ArmOutcome], *, unknown_items: int, unpredicted: int
) -> dict[str, Any]:
    grouped: dict[tuple[int, str, str], dict[str, list[ArmOutcome]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for o in outcomes:
        grouped[(o.k, o.stratum, o.arm)][o.item_id].append(o)

    cells: dict[tuple[int, str, str], dict[str, Any]] = {}
    item_means: dict[tuple[int, str, str], dict[str, float]] = {}
    for key, by_item in grouped.items():
        means = {
            i: _mean([float(o.correct) for o in runs if o.scorable])
            for i, runs in by_item.items()
            if any(o.scorable for o in runs)
        }
        item_means[key] = means
        clusters = {i: runs[0].cluster for i, runs in by_item.items()}
        interval = paired_cluster_bootstrap(
            [(clusters[i], m) for i, m in means.items()], rounds=BOOTSTRAP_ROUNDS
        )
        flat = [o for runs in by_item.values() for o in runs]
        missing = [float(o.content_missing) for o in flat if o.content_missing is not None]
        cells[key] = {
            "n_items": len(by_item),
            "n_runs": len(flat),
            "n_scored": len(means),
            "accuracy": _mean(list(means.values())) if means else None,
            "ci": (interval[1], interval[2]) if interval else None,
            "stale_stated": _item_rate(by_item, lambda o: float(o.stale_stated)),
            "abstained": _item_rate(by_item, lambda o: float(o.abstained)),
            "stale_in_context": _item_rate(by_item, lambda o: float(o.stale_in_context)),
            "content_missing": _mean(missing) if missing else None,
        }

    lifts: dict[tuple[int, str, str], dict[str, Any]] = {}
    for (k, stratum, arm), means in item_means.items():
        base_key = (k, stratum, "baseline")
        if arm == "baseline" or base_key not in item_means:
            continue
        shared = sorted(set(means) & set(item_means[base_key]))
        if not shared:
            continue
        clusters = {
            o.item_id: o.cluster for runs in grouped[(k, stratum, arm)].values() for o in runs
        }
        diffs = [(clusters[i], means[i] - item_means[base_key][i]) for i in shared]
        interval = paired_cluster_bootstrap(diffs, rounds=BOOTSTRAP_ROUNDS)
        first_arm = _first_repeat(grouped[(k, stratum, arm)])
        first_base = _first_repeat(grouped[base_key])
        arm_only = sum(1 for i in shared if first_arm[i] and not first_base[i])
        base_only = sum(1 for i in shared if first_base[i] and not first_arm[i])
        floor = _spread(grouped[base_key])
        lift = interval[0] if interval else 0.0
        lifts[(k, stratum, arm)] = {
            "lift": lift,
            "ci": (interval[1], interval[2]) if interval else None,
            "n_items": len(shared),
            "arm_only": arm_only,
            "baseline_only": base_only,
            "mcnemar_p": mcnemar_exact(arm_only, base_only),
            "floor": floor,
            "clears_floor": None if floor is None else abs(lift) > floor,
        }

    return {
        "cells": dict(sorted(cells.items())),
        "lifts": dict(sorted(lifts.items())),
        "items": len({o.item_id for o in outcomes}),
        "clusters": len({o.cluster for o in outcomes}),
        "unknown_items": unknown_items,
        "unpredicted": unpredicted,
    }


def _first_repeat(by_item: dict[str, list[ArmOutcome]]) -> dict[str, bool]:
    return {i: min(runs, key=lambda o: o.repeat).correct for i, runs in by_item.items()}


def _spread(by_item: dict[str, list[ArmOutcome]]) -> float | None:
    """Range of the baseline's accuracy across repeats; None if there is only one repeat."""
    per_repeat: dict[int, list[float]] = defaultdict(list)
    for runs in by_item.values():
        for o in runs:
            if o.scorable:
                per_repeat[o.repeat].append(float(o.correct))
    if len(per_repeat) < 2:
        return None
    accuracies = [_mean(v) for v in per_repeat.values()]
    return max(accuracies) - min(accuracies)


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{100 * value:5.1f}"


def floor_verdict(lift: dict[str, Any]) -> str:
    """The report's words for a lift against the noise floor. A loss larger than the floor is an
    effect too, but it must not be read as a gain."""
    if lift["clears_floor"] is None:
        return "floor unmeasured"
    if not lift["clears_floor"]:
        return "BELOW floor"
    return "clears floor" if lift["lift"] > 0 else "LOSS larger than floor"


def format_arm_report(summary: dict[str, Any]) -> str:
    lines = [
        f"{summary['items']} items from {summary['clusters']} source pages   "
        f"unknown (a step failed): {summary['unknown_items']}   "
        f"unpredicted: {summary['unpredicted']}",
        "",
    ]
    last: tuple[int, str] | None = None
    for (k, stratum, arm), cell in summary["cells"].items():
        if (k, stratum) != last:
            lines.append(f"k={k}  stratum={stratum}")
            lines.append(
                "  arm            items  correct%   95% by page   stale-said%  abstain%"
                "  stale-in-ctx%  harm%"
            )
            last = (k, stratum)
        ci = cell["ci"]
        band = f"[{100 * ci[0]:4.0f},{100 * ci[1]:4.0f}]" if ci else "      n/a   "
        lines.append(
            f"  {arm:<14}{cell['n_items']:>5}  {_pct(cell['accuracy'])}   {band}   "
            f"{_pct(cell['stale_stated'])}      {_pct(cell['abstained'])}    "
            f"{_pct(cell['stale_in_context'])}        {_pct(cell['content_missing'])}"
        )
        lift = summary["lifts"].get((k, stratum, arm))
        if lift:
            lci = lift["ci"]
            lband = f"[{100 * lci[0]:+.0f},{100 * lci[1]:+.0f}]" if lci else "n/a"
            floor = "unmeasured" if lift["floor"] is None else f"{100 * lift['floor']:.0f} pts"
            verdict = floor_verdict(lift)
            lines.append(
                f"      lift vs baseline {100 * lift['lift']:+.1f} pts {lband}  McNemar p="
                f"{lift['mcnemar_p']:.3g} ({lift['arm_only']} vs {lift['baseline_only']})  "
                f"noise floor {floor}: {verdict}"
            )
    return "\n".join(lines)
