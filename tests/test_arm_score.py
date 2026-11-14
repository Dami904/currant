from __future__ import annotations

from typing import Any

import pytest

from currant.evalset import ItemRow
from currant.harness.arm_score import (
    ArmOutcome,
    format_arm_report,
    score_item_arms,
    stratum_of,
    summarize_arms,
)

LABEL: dict[str, Any] = {
    "scenario": "supersedes_explicit",
    "stale_page_id": "a",
    "update_page_id": "b",
    "stale_span": [100, 140],
    "stale_value_number": 10.0,
    "current_value_number": 50.0,
}


def label(**changes: Any) -> dict[str, Any]:
    return {**LABEL, **changes}


CLEAN = label(scenario="clean", update_page_id=None, current_value_number=10.0)
IMPLICIT = label(scenario="contested_implicit", current_value_number=None)


def answer(value: float | None, verdict: str = "answer") -> dict[str, Any]:
    return {"verdict": verdict, "value": value, "unit": None, "evidence": None}


def run(
    *, k: int = 2, arm: str = "baseline", repeat: int = 0, retrieved: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None, status: str = "ok",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:  # fmt: skip
    return {
        "k": k, "arm": arm, "repeat": repeat, "retrieved": retrieved or ["a", "b"],
        "actions": actions or [], "status": status, "answer": result,
    }  # fmt: skip


def item(cluster: str = "c") -> ItemRow:
    return ItemRow("i", "synthetic", cluster, "dev", False, {})


def score(lab: dict[str, Any], one: dict[str, Any]) -> ArmOutcome:
    (outcome,) = score_item_arms(item(), lab, {"status": "complete", "runs": [one]})
    return outcome


# --- strata --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("retrieved", "expected"),
    [
        (["a", "b"], "both"),
        (["b", "a"], "both"),
        (["a"], "stale_only"),
        (["b"], "update_only"),
        ([], "neither"),
    ],
)
def test_strata_are_decided_from_which_pages_were_retrieved(
    retrieved: list[str], expected: str
) -> None:
    assert stratum_of(LABEL, retrieved) == expected


def test_a_clean_item_has_its_own_stratum() -> None:
    assert stratum_of(CLEAN, ["a"]) == "clean" and stratum_of(CLEAN, []) == "clean"


# --- correctness -----------------------------------------------------------------------------


def test_the_current_value_is_correct_and_the_stale_value_is_stale_stated() -> None:
    right = score(LABEL, run(result=answer(50.0)))
    assert right.correct and not right.stale_stated
    stale = score(LABEL, run(result=answer(10.0)))
    assert not stale.correct and stale.stale_stated


def test_a_value_that_is_neither_is_wrong_but_not_stale_stated() -> None:
    other = score(LABEL, run(result=answer(99.0)))
    assert not other.correct and not other.stale_stated


def test_abstaining_on_a_resolvable_question_is_a_miss() -> None:
    for verdict in ("contested", "unknown"):
        outcome = score(LABEL, run(result=answer(None, verdict)))
        assert not outcome.correct and outcome.abstained


def test_an_implicit_pair_is_answered_correctly_only_by_saying_contested() -> None:
    assert score(IMPLICIT, run(result=answer(None, "contested"))).correct
    for value in (10.0, 50.0):
        picked = score(IMPLICIT, run(result=answer(value)))
        assert not picked.correct  # picking a winner without evidence is wrong either way
    assert score(IMPLICIT, run(result=answer(10.0))).stale_stated


def test_a_clean_item_is_answered_correctly_with_its_only_value() -> None:
    assert score(CLEAN, run(result=answer(10.0))).correct
    assert not score(CLEAN, run(result=answer(None, "contested"))).correct  # a false alarm


@pytest.mark.parametrize("status", ["guard_blocked", "invalid"])
def test_an_answer_that_could_not_be_used_is_wrong_but_counted(status: str) -> None:
    outcome = score(LABEL, run(status=status, result=None))
    assert not outcome.correct and outcome.status == status


def test_a_float_value_matches_by_number_not_by_text() -> None:
    assert score(LABEL, run(result=answer(50.000000001))).correct


# --- what the model was shown ------------------------------------------------------------------


def cut(page: str, start: int, end: int, kind: str = "redact") -> dict[str, Any]:
    return {"kind": kind, "page": page, "start": start, "end": end, "source_page": "b"}


def test_the_stale_span_is_in_context_unless_a_cut_covers_it() -> None:
    assert score(LABEL, run(result=answer(50.0))).stale_in_context
    assert not score(LABEL, run(result=answer(50.0), actions=[cut("a", 90, 150)])).stale_in_context
    assert not score(LABEL, run(result=answer(50.0), actions=[cut("a", 120, 130)])).stale_in_context


def test_a_cut_elsewhere_or_on_another_page_leaves_the_stale_span_in_context() -> None:
    assert score(LABEL, run(result=answer(50.0), actions=[cut("a", 300, 340)])).stale_in_context
    assert score(LABEL, run(result=answer(50.0), actions=[cut("b", 100, 140)])).stale_in_context


def test_an_annotation_keeps_the_stale_text_in_context() -> None:
    outcome = score(LABEL, run(result=answer(50.0), actions=[cut("a", 100, 140, kind="annotate")]))
    assert outcome.stale_in_context


def test_a_stale_page_that_was_not_retrieved_is_not_in_context() -> None:
    assert not score(LABEL, run(retrieved=["b"], result=answer(50.0))).stale_in_context


def test_a_clean_item_loses_content_if_it_is_cut_or_not_retrieved() -> None:
    assert not score(CLEAN, run(result=answer(10.0))).content_missing
    assert score(CLEAN, run(result=answer(10.0), actions=[cut("a", 100, 140)])).content_missing
    assert score(CLEAN, run(retrieved=["b"], result=answer(10.0))).content_missing


def test_contested_notices_and_pulls_are_not_cuts() -> None:
    notice = {"kind": "contested", "page": "a", "start": 100, "end": 140, "source_page": "b"}
    pulled = {"kind": "pull", "page": "a", "start": 100, "end": 140, "source_page": "b"}
    assert score(CLEAN, run(result=answer(10.0), actions=[notice, pulled])).content_missing is False


# --- records that cannot be scored ---------------------------------------------------------------


def test_an_unknown_item_yields_no_outcomes_and_no_retrieval_runs_are_skipped() -> None:
    assert score_item_arms(item(), LABEL, {"status": "unknown", "runs": [run()]}) == []
    skipped = {
        "status": "complete",
        "runs": [{"k": 1, "arm": "*", "repeat": 0, "status": "no_retrieval"}],
    }
    assert score_item_arms(item(), LABEL, skipped) == []


# --- tables, lifts, and the noise floor --------------------------------------------------------


def outcome(cluster: str, arm: str, correct: bool, *, repeat: int = 0, k: int = 2,
            stratum: str = "both", item_id: str | None = None) -> ArmOutcome:  # fmt: skip
    return ArmOutcome(
        item_id or cluster, cluster, "supersedes_explicit", k, arm, repeat, stratum, "ok",
        correct, False, False, True, None,
    )  # fmt: skip


def paired(n: int, base_right: int, arm_right: int, arm: str = "redact") -> list[ArmOutcome]:
    """n items: the first `base_right` are right under baseline, the last `arm_right` under arm."""
    out: list[ArmOutcome] = []
    for i in range(n):
        out.append(outcome(f"c{i}", "baseline", i < base_right))
        out.append(outcome(f"c{i}", arm, i >= n - arm_right))
    return out


def test_cells_report_accuracy_and_counts_per_arm_stratum_and_depth() -> None:
    summary = summarize_arms(paired(10, 3, 8), unknown_items=0, unpredicted=0)
    base, redact = (
        summary["cells"][(2, "both", "baseline")],
        summary["cells"][(2, "both", "redact")],
    )
    assert base["n_items"] == 10 and base["accuracy"] == pytest.approx(0.3)
    assert redact["accuracy"] == pytest.approx(0.8)
    assert redact["ci"] is not None and redact["ci"][0] <= 0.8 <= redact["ci"][1]


def test_a_lift_is_paired_with_the_baseline_and_carries_a_test() -> None:
    summary = summarize_arms(paired(40, 10, 30), unknown_items=0, unpredicted=0)
    lift = summary["lifts"][(2, "both", "redact")]
    assert lift["lift"] == pytest.approx(0.5)
    # base right: items 0..9; redact right: items 10..39 -> disjoint: 30 redact-only, 10 base-only
    assert (lift["arm_only"], lift["baseline_only"]) == (30, 10)
    assert lift["mcnemar_p"] < 0.01 and lift["ci"][0] > 0


def test_there_is_no_lift_row_for_the_baseline_itself() -> None:
    summary = summarize_arms(paired(10, 3, 8), unknown_items=0, unpredicted=0)
    assert (2, "both", "baseline") not in summary["lifts"]


def test_the_noise_floor_is_the_baselines_spread_across_repeats() -> None:
    data: list[ArmOutcome] = []
    for repeat, right in enumerate([4, 6, 5]):  # baseline accuracy per repeat: .4 .6 .5
        for i in range(10):
            data.append(outcome(f"c{i}", "baseline", i < right, repeat=repeat))
            data.append(outcome(f"c{i}", "redact", i < 9, repeat=repeat))
    lift = summarize_arms(data, unknown_items=0, unpredicted=0)["lifts"][(2, "both", "redact")]
    assert lift["floor"] == pytest.approx(0.2) and lift["clears_floor"] is True
    small = [o for o in data if o.arm == "baseline" or o.item_id != "c9"]
    assert small  # (smoke: the filter above leaves data to summarise)


def test_a_lift_smaller_than_the_noise_floor_is_not_claimed() -> None:
    data: list[ArmOutcome] = []
    for repeat, right in enumerate([2, 8, 5]):  # a very noisy baseline: spread .6
        for i in range(10):
            data.append(outcome(f"c{i}", "baseline", i < right, repeat=repeat))
            data.append(outcome(f"c{i}", "redact", i < 7, repeat=repeat))
    lift = summarize_arms(data, unknown_items=0, unpredicted=0)["lifts"][(2, "both", "redact")]
    assert lift["floor"] == pytest.approx(0.6) and lift["clears_floor"] is False


def test_the_report_never_calls_a_loss_a_gain() -> None:
    from currant.harness.arm_score import floor_verdict

    assert floor_verdict({"clears_floor": True, "lift": 0.2}) == "clears floor"
    assert floor_verdict({"clears_floor": True, "lift": -0.04}) == "LOSS larger than floor"
    assert floor_verdict({"clears_floor": False, "lift": -0.01}) == "BELOW floor"
    assert floor_verdict({"clears_floor": None, "lift": 0.5}) == "floor unmeasured"


def test_with_a_single_repeat_the_floor_is_unmeasured_not_zero() -> None:
    lift = summarize_arms(paired(10, 3, 8), unknown_items=0, unpredicted=0)["lifts"][
        (2, "both", "redact")
    ]
    assert lift["floor"] is None and lift["clears_floor"] is None


def test_repeats_are_averaged_within_an_item_before_items_are_compared() -> None:
    data = [outcome("c0", "baseline", True, repeat=0), outcome("c0", "baseline", False, repeat=1)]
    cell = summarize_arms(data, unknown_items=0, unpredicted=0)["cells"][(2, "both", "baseline")]
    assert cell["n_items"] == 1 and cell["accuracy"] == pytest.approx(0.5) and cell["n_runs"] == 2


def test_items_in_one_cluster_share_one_interval_draw() -> None:
    # 20 items, but only 2 clusters: the interval must be very wide, as it would be for 2 items.
    data = [outcome("good", "baseline", True, item_id=f"g{i}") for i in range(10)]
    data += [outcome("bad", "baseline", False, item_id=f"b{i}") for i in range(10)]
    low, high = summarize_arms(data, unknown_items=0, unpredicted=0)["cells"][
        (2, "both", "baseline")
    ]["ci"]
    assert low == 0.0 and high == 1.0


def test_the_report_names_unknown_and_unpredicted_items_and_every_cell() -> None:
    summary = summarize_arms(paired(10, 3, 8), unknown_items=2, unpredicted=5)
    text = format_arm_report(summary)
    assert "unknown" in text and "2" in text and "unpredicted" in text and "5" in text
    assert "baseline" in text and "redact" in text and "both" in text
    assert "lift" in text.lower()


def test_a_clean_items_only_value_is_never_called_stale() -> None:
    # On a clean control the stale value and the current value are the same number.
    assert not score(CLEAN, run(result=answer(10.0))).stale_stated


# --- items whose answer is not a number cannot be scored for correctness -------------------------

TEXT_CLEAN = label(scenario="clean", update_page_id=None, current_value_number=None)


def test_a_control_with_no_numeric_value_is_not_scorable_for_correctness() -> None:
    outcome = score(TEXT_CLEAN, run(result=answer(25.0)))
    assert outcome.scorable is False
    assert score(CLEAN, run(result=answer(10.0))).scorable is True
    assert score(LABEL, run(result=answer(50.0))).scorable is True
    assert score(IMPLICIT, run(result=answer(None, "contested"))).scorable is True


def clean_outcome(cluster: str, *, scorable: bool, correct: bool, missing: bool) -> ArmOutcome:
    return ArmOutcome(
        cluster, cluster, "clean", 2, "redact", 0, "clean", "ok", correct, False, False,
        not missing, missing, scorable,
    )  # fmt: skip


def test_unscorable_items_are_left_out_of_accuracy_but_still_count_for_harm() -> None:
    data = [
        clean_outcome("a", scorable=True, correct=True, missing=False),
        clean_outcome("b", scorable=False, correct=False, missing=True),
        clean_outcome("c", scorable=False, correct=False, missing=False),
    ]
    cell = summarize_arms(data, unknown_items=0, unpredicted=0)["cells"][(2, "clean", "redact")]
    assert cell["n_items"] == 3 and cell["n_scored"] == 1
    assert cell["accuracy"] == pytest.approx(1.0)  # only the scorable item
    assert cell["content_missing"] == pytest.approx(1 / 3)  # but all three count for harm


def test_a_cell_with_nothing_scorable_has_no_accuracy_rather_than_zero() -> None:
    data = [clean_outcome("b", scorable=False, correct=False, missing=False)]
    cell = summarize_arms(data, unknown_items=0, unpredicted=0)["cells"][(2, "clean", "redact")]
    assert cell["accuracy"] is None and cell["ci"] is None and cell["n_scored"] == 0


# --- resolvable and implicit items are reported separately ---------------------------------------


def test_strata_are_split_by_whether_an_order_exists() -> None:
    resolvable = score(LABEL, run(result=answer(50.0)))
    implicit = score(IMPLICIT, run(result=answer(None, "contested")))
    clean = score(CLEAN, run(result=answer(10.0)))
    assert resolvable.stratum == "both/resolvable"
    assert implicit.stratum == "both/implicit"
    assert clean.stratum == "clean"
    stale_only = score(LABEL, run(retrieved=["a"], result=answer(10.0)))
    assert stale_only.stratum == "stale_only/resolvable"
