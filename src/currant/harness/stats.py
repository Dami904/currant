"""Small, dependency-free statistics for the arms comparison.

* `wilson`: a 95% interval for a proportion.
* `mcnemar_exact`: the exact two-sided test for paired yes/no outcomes (same items, two arms).
* `paired_cluster_bootstrap`: a 95% interval for the mean per-item difference between two arms,
  resampling whole source-page clusters, because items from one page are not independent.

No effect is claimed from these alone: the plan also requires it to clear a measured noise floor.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for `successes` out of `n`. None when there is nothing to measure."""
    if successes < 0 or successes > n:
        raise ValueError("successes must be between 0 and n")
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value. `b` items were right under the first arm only, `c` under
    the second only; items both got right or both got wrong carry no information."""
    if b < 0 or c < 0:
        raise ValueError("counts cannot be negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2**n
    return float(min(1.0, 2 * tail))


def paired_cluster_bootstrap(
    differences: list[tuple[str, float]], *, rounds: int = 10_000, seed: int = 0
) -> tuple[float, float, float] | None:
    """(mean, low, high): the mean of per-item differences and its 95% interval from resampling
    clusters. `differences` is (cluster id, difference) per item. None for no items."""
    if not differences:
        return None
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for cluster, difference in differences:
        sums[cluster] += difference
        counts[cluster] += 1
    clusters = sorted(sums)
    mean = sum(sums.values()) / sum(counts.values())
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(rounds):
        drawn = [rng.choice(clusters) for _ in clusters]
        total_items = sum(counts[c] for c in drawn)
        estimates.append(sum(sums[c] for c in drawn) / total_items)
    estimates.sort()
    low = estimates[int(0.025 * len(estimates))]
    high = estimates[min(len(estimates) - 1, int(0.975 * len(estimates)))]
    return mean, low, high
