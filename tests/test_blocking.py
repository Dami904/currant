"""Candidate pairing by token blocking must return exactly what comparing every pair returned.

`reference_pairs` is the all-pairs algorithm as it stood before blocking (commit fc18f21), kept
verbatim here as the specification. The property test generates claim sets with shared and
unshared vocabulary, competing and non-competing stances, repeated values and pages, and
requires identical output for every min_score, top_k and max_pairs.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from currant.detect import COMPETING_STANCES, Candidate, candidate_pairs, jaccard, tokens
from currant.store import ClaimRow


def reference_pairs(
    claims: list[ClaimRow],
    *,
    min_score: float = 0.30,
    top_k: int = 3,
    max_pairs: int = 40,
    lines: dict[str, str] | None = None,
) -> list[Candidate]:
    current = sorted((c for c in claims if c.stance in COMPETING_STANCES), key=lambda c: c.claim_id)
    lines = lines or {}
    profile = {
        c.claim_id: (
            tokens(f"{c.subject} {c.attribute}"),
            tokens(c.quote),
            tokens(lines.get(c.claim_id, c.quote)),
        )
        for c in current
    }
    scored: list[tuple[float, ClaimRow, ClaimRow]] = []
    for i, a in enumerate(current):
        for b in current[i + 1 :]:
            if a.doc_id == b.doc_id or a.value_key == b.value_key:
                continue
            if "current" not in (a.stance, b.stance):
                continue
            (ka, qa, la), (kb, qb, lb) = profile[a.claim_id], profile[b.claim_id]
            score = 0.5 * jaccard(ka, kb) + 0.5 * max(jaccard(qa, qb), jaccard(la, lb))
            if score >= min_score:
                scored.append((score, a, b))
    keep: set[tuple[str, str]] = set()
    for claim in current:
        mine = sorted(
            (s for s in scored if claim.claim_id in (s[1].claim_id, s[2].claim_id)),
            key=lambda s: (-s[0], s[1].claim_id, s[2].claim_id),
        )
        keep.update((s[1].claim_id, s[2].claim_id) for s in mine[:top_k])
    chosen = [s for s in scored if (s[1].claim_id, s[2].claim_id) in keep]
    chosen.sort(key=lambda s: (-s[0], s[1].claim_id, s[2].claim_id))
    return [Candidate(a, b, score) for score, a, b in chosen[:max_pairs]]


VOCAB = ["rate", "limit", "upload", "size", "free", "credits", "window", "epoch", "api", "max"]
words = st.lists(st.sampled_from(VOCAB), min_size=0, max_size=7).map(" ".join)


@st.composite
def claim_sets(draw: st.DrawFn) -> tuple[list[ClaimRow], dict[str, str]]:
    n = draw(st.integers(0, 14))
    claims, lines = [], {}
    for i in range(n):
        claim_id = f"c{i:02d}"
        quote = draw(words) + " 10"
        claims.append(
            ClaimRow(
                claim_id=claim_id,
                doc_id=f"d{draw(st.integers(0, 3))}",
                run_id=1,
                start_char=0,
                end_char=len(quote),
                quote=quote,
                subject=draw(words),
                subject_key="s",
                attribute=draw(words),
                attribute_key="a",
                value_text="v",
                value_key=f"v{draw(st.integers(0, 3))}",
                value_type="count",
                value_number=None,
                unit=None,
                stance=draw(st.sampled_from(["current", "current", "historical", "proposed"])),
                asserted_at=None,
            )
        )
        if draw(st.booleans()):
            lines[claim_id] = draw(words)
    return claims, lines


@settings(max_examples=1500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    case=claim_sets(),
    min_score=st.one_of(
        st.sampled_from([0.0, 0.05, 0.1, 0.3, 1 / 3, 0.45, 0.5, 0.6, 0.7, 1.0]),
        st.floats(0.001, 1.0),
    ),
    top_k=st.integers(1, 4),
    max_pairs=st.integers(1, 50),
)
def test_blocking_returns_exactly_the_all_pairs_result(
    case: tuple[list[ClaimRow], dict[str, str]], min_score: float, top_k: int, max_pairs: int
) -> None:
    claims, lines = case
    blocked = candidate_pairs(
        claims, min_score=min_score, top_k=top_k, max_pairs=max_pairs, lines=lines
    )
    assert blocked == reference_pairs(
        claims, min_score=min_score, top_k=top_k, max_pairs=max_pairs, lines=lines
    )


def _claim(claim_id: str, doc: str, keys: str, quote: str, value: str) -> ClaimRow:
    return ClaimRow(claim_id, doc, 1, 0, len(quote), quote, keys, "s", "", "a", "v", value,
                    "count", None, None, "current", None)  # fmt: skip


def test_a_pair_exactly_at_the_threshold_is_still_found() -> None:
    # Keys and quotes each have Jaccard exactly 0.5, so the score is exactly 0.5, and 0.5 * |x| is
    # a whole number. The shared word sits in the last prefix slot: a prefix one token shorter
    # would miss this pair (the off-by-one random cases rarely reach).
    a = _claim("a", "d1", "alpha beta", "kappa lambda 10", "v1")
    b = _claim("b", "d2", "alpha beta gamma delta", "kappa lambda sigma omega 20", "v2")
    expected = reference_pairs([a, b], min_score=0.5)
    assert len(expected) == 1 and expected[0].score == 0.5
    assert candidate_pairs([a, b], min_score=0.5) == expected
