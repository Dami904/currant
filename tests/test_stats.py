from __future__ import annotations

import math

import pytest

from currant.harness.stats import mcnemar_exact, paired_cluster_bootstrap, wilson


def test_wilson_of_nothing_is_undefined() -> None:
    assert wilson(0, 0) is None


@pytest.mark.parametrize(
    ("successes", "n", "low", "high"),
    [(5, 10, 0.237, 0.763), (0, 10, 0.0, 0.278), (10, 10, 0.722, 1.0), (30, 31, 0.838, 0.994)],
)
def test_wilson_matches_known_intervals(successes: int, n: int, low: float, high: float) -> None:
    interval = wilson(successes, n)
    assert interval is not None
    assert interval[0] == pytest.approx(low, abs=0.002) and interval[1] == pytest.approx(
        high, abs=0.002
    )


@pytest.mark.parametrize("bad", [(-1, 5), (6, 5)])
def test_wilson_refuses_impossible_counts(bad: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="between 0 and n"):
        wilson(*bad)


def test_mcnemar_exact_values() -> None:
    assert mcnemar_exact(0, 10) == pytest.approx(2 * 0.5**10)
    assert mcnemar_exact(10, 0) == pytest.approx(2 * 0.5**10)  # symmetric
    assert mcnemar_exact(2, 8) == pytest.approx(0.109375)  # 2 * P(X <= 2 | n=10, p=.5)
    assert mcnemar_exact(5, 5) == 1.0 and mcnemar_exact(0, 0) == 1.0  # capped at one


def test_mcnemar_refuses_negative_counts() -> None:
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 3)


def pairs(spec: dict[str, list[float]]) -> list[tuple[str, float]]:
    return [(cluster, diff) for cluster, diffs in spec.items() for diff in diffs]


def boot(
    data: list[tuple[str, float]], *, rounds: int = 500, seed: int = 0
) -> tuple[float, float, float]:
    result = paired_cluster_bootstrap(data, rounds=rounds, seed=seed)
    assert result is not None
    return result


def test_bootstrap_of_a_constant_difference_is_that_constant() -> None:
    mean, low, high = boot(pairs({f"c{i}": [0.5, 0.5] for i in range(10)}), rounds=300)
    assert mean == 0.5 and low == 0.5 and high == 0.5


def test_bootstrap_is_deterministic_for_a_seed_and_differs_across_seeds() -> None:
    data = pairs({f"c{i}": [(i * 37 % 11) / 10] for i in range(15)})
    assert boot(data, seed=1) == boot(data, seed=1)
    assert boot(data, seed=1)[1:] != boot(data, seed=2)[1:]  # the interval, not the mean


def test_bootstrap_resamples_whole_clusters_so_correlated_items_widen_the_interval() -> None:
    # Ten items in 2 clusters (all +1 and all -1) are much less certain than ten independent items.
    correlated = pairs({"good": [1.0] * 5, "bad": [-1.0] * 5})
    independent = pairs({f"c{i}": [1.0 if i < 5 else -1.0] for i in range(10)})
    _, c_low, c_high = boot(correlated, rounds=800, seed=3)
    _, i_low, i_high = boot(independent, rounds=800, seed=3)
    assert (c_high - c_low) > (i_high - i_low)


def test_bootstrap_interval_excludes_zero_for_a_consistent_gain() -> None:
    mean, low, high = boot(pairs({f"c{i}": [1.0, 1.0, 0.0] for i in range(30)}))
    assert mean == pytest.approx(2 / 3) and low > 0.0 and high <= 1.0


def test_bootstrap_of_nothing_is_undefined() -> None:
    assert paired_cluster_bootstrap([], rounds=100) is None


def test_the_mean_is_the_plain_mean_of_the_items() -> None:
    mean, _, _ = boot(pairs({"a": [1.0, 0.0], "b": [0.0]}), rounds=100)
    assert math.isclose(mean, 1 / 3)
