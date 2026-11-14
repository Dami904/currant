"""Prompt injection through crawled text, against the parts our code controls.

The live half (does the model obey? does the guard block it?) is `scripts/live_injection.py`; it
needs a key and costs money, so it is not a test. Here a model that OBEYS whatever a page tells it
stands in for the worst case, and the question is what our code lets that cause.
"""

from __future__ import annotations

from typing import Any

import pytest

from currant.detect import decide
from currant.ground import REMOVED, Grounded, defang
from currant.harness.injections import ATTACK_VALUE, PAYLOADS, Payload, by_id, embed
from tests.test_ground import (
    R10,
    S10,
    S50,
    T10,
    T50,
    U1,
    U2,
    World,
    answer,
)

NOT_FORGED_UPDATE = [p for p in PAYLOADS if p.family != "forged_update"]
POSITIONS = ("start", "middle", "end")


def ids(payloads: list[Payload] | tuple[Payload, ...]) -> list[str]:
    return [p.payload_id for p in payloads]


# --- the payload set itself --------------------------------------------------------------------


def test_payload_ids_are_unique_and_every_family_has_one() -> None:
    assert len({p.payload_id for p in PAYLOADS}) == len(PAYLOADS)
    families = {p.family for p in PAYLOADS}
    assert families == {
        "override",
        "role",
        "exfil",
        "delimiter",
        "marker",
        "evasion",
        "forged_update",
    }
    assert by_id("override-ignore").canary == ATTACK_VALUE
    with pytest.raises(KeyError):
        by_id("no-such-payload")


@pytest.mark.parametrize("where", POSITIONS)
def test_embed_puts_the_payload_in_the_page_once(where: str) -> None:
    payload = by_id("override-ignore")
    page = embed(T10, payload, where=where)
    assert page.count(payload.text) == 1 and S10 in page
    if where == "start":
        assert page.startswith(payload.text)
    if where == "end":
        assert page.rstrip().endswith(payload.text)


def test_embed_refuses_an_unknown_position() -> None:
    with pytest.raises(ValueError, match="unknown position"):
        embed(T10, by_id("override-ignore"), where="nowhere")


# --- a page cannot forge Currant's own markers -------------------------------------------------


def count(context: str, token: str) -> int:
    return context.count(token)


def forged_markers(grounded: Grounded, urls: list[str]) -> dict[str, tuple[int, int]]:
    """For each marker, (how many are in the context, how many our code put there)."""
    actions = grounded.actions
    context = grounded.context
    return {
        "<<<DOCUMENT ": (count(context, "<<<DOCUMENT "), len(urls)),
        "<<<END DOCUMENT ": (count(context, "<<<END DOCUMENT "), len(urls)),
        "<<<PULLED EVIDENCE>>>": (
            count(context, "<<<PULLED EVIDENCE>>>"),
            1 if any(a.kind == "pull" for a in actions) else 0,
        ),
        "<<<END PULLED EVIDENCE>>>": (
            count(context, "<<<END PULLED EVIDENCE>>>"),
            1 if any(a.kind == "pull" for a in actions) else 0,
        ),
        "<<<NOTICE: CONTESTED>>>": (
            count(context, "<<<NOTICE: CONTESTED>>>"),
            1 if any(a.kind == "contested" for a in actions) else 0,
        ),
        "<<<END NOTICE>>>": (
            count(context, "<<<END NOTICE>>>"),
            1 if any(a.kind == "contested" for a in actions) else 0,
        ),
        "[SUPERSEDED:": (
            count(context, "[SUPERSEDED:"),
            sum(1 for a in actions if a.kind == "annotate"),
        ),
        "[REMOVED:": (
            count(context, "[REMOVED:"),
            sum(1 for a in actions if a.kind == "redact"),
        ),
    }


def poisoned_world(payload: Payload, where: str, *, poison: str) -> World:
    older = embed(T10, payload, where=where) if poison in ("older", "both") else T10
    newer = embed(T50, payload, where=where) if poison in ("newer", "both") else T50
    world = World((U1, older, S10, 10, "current"), (U2, newer, S50, 50, "current"))
    world.supersede(U2, U1, R10)
    return world


MODES_AND_PAGES = [
    ("baseline", [U1, U2]),
    ("redact", [U1, U2]),
    ("annotate", [U1, U2]),
    ("pull", [U1]),
    ("redact_pull", [U1]),
]
# Only a payload that contains marker syntax can forge a marker, so only those get the full grid of
# positions and modes; every other payload is checked once.
FORGERS = [p for p in NOT_FORGED_UPDATE if p.family in ("delimiter", "marker")]
OTHERS = [p for p in NOT_FORGED_UPDATE if p.family not in ("delimiter", "marker")]
FORGERY_CASES = [
    pytest.param(p, where, mode, urls, id=f"{p.payload_id}-{where}-{mode}")
    for p in FORGERS
    for where in POSITIONS
    for mode, urls in MODES_AND_PAGES
] + [pytest.param(p, "middle", "annotate", [U1, U2], id=p.payload_id) for p in OTHERS]


@pytest.mark.parametrize(("payload", "where", "mode", "urls"), FORGERY_CASES)
def test_page_text_never_adds_a_marker_only_our_code_wrote(
    payload: Payload, where: str, mode: str, urls: list[str]
) -> None:
    grounded = poisoned_world(payload, where, poison="both").ground(mode, urls)
    counts = forged_markers(grounded, urls)
    forged = {token: pair for token, pair in counts.items() if pair[0] != pair[1]}
    assert forged == {}, f"a page imitated {sorted(forged)}"


def test_defang_leaves_ordinary_text_alone_and_is_idempotent() -> None:
    plain = "Use a < b and c > d, or `a <<= 1`, or see [docs](https://x.example) and [1]."
    assert defang(plain) == plain
    for payload in PAYLOADS:
        once = defang(payload.text)
        assert defang(once) == once
    assert "<<<" not in defang("<<<<DOCUMENT>>>>") and ">>>" not in defang("<<<<DOCUMENT>>>>")
    assert "[removed" not in defang("[removed: x]").casefold().replace("[ ", "[")


def test_a_real_removal_marker_is_still_ours_alone() -> None:
    grounded = poisoned_world(by_id("marker-fake-removed"), "end", poison="both").ground(
        "redact", [U1, U2]
    )
    assert grounded.context.count(REMOVED) == 1  # the one our code wrote; the page's was defanged


def test_the_forged_text_is_still_visible_to_the_model_as_text() -> None:
    """Defanging must not delete the page's words: a reviewer reading the context sees them."""
    payload = by_id("marker-fake-superseded")
    grounded = poisoned_world(payload, "end", poison="newer").ground("baseline", [U1, U2])
    assert (
        "SUPERSEDED" in grounded.context and f"{ATTACK_VALUE} free evaluations" in grounded.context
    )


# --- a model that obeys the page cannot make our code cut what the page did not support --------

OLD = (U1, T10, S10, 10, "current")


def obedient_decision(payload: Payload, quote: str) -> Any:
    """The relation detector, hijacked: it claims an explicit replacement quoting `quote`."""
    world = World(
        OLD, (U2, embed(T50.replace(R10, "").rstrip() + "\n", payload), S50, 50, "current")
    )
    return decide(
        answer(quote), world.claims[U1], world.claims[U2], world.texts[U1], world.texts[U2]
    )


def candidate_quotes(payload: Payload) -> list[str]:
    """What an obedient model could quote from the payload: the whole thing, or one line."""
    lines = [line for line in payload.text.split("\n") if line.strip()]
    return [payload.text, *lines]


def cuts_caused(payload: Payload) -> bool:
    return any(
        obedient_decision(payload, quote).kind == "supersedes"
        for quote in candidate_quotes(payload)
    )


def test_a_hijacked_detector_cannot_cut_unless_the_quote_names_the_old_value() -> None:
    """MEASURED LIMIT, pinned. `decide` checks that the ordering quote is verbatim on exactly one
    page and that it mentions the replaced value; it does not check that the sentence is a
    replacement statement. So a page the attacker controls CAN retire an older sentence by quoting
    its own text that mentions the old value. What it cannot do is anything else."""
    succeeded = sorted(p.payload_id for p in PAYLOADS if cuts_caused(p))
    assert succeeded == ["forged-update", "marker-fake-superseded"]


def test_every_other_payload_is_downgraded_with_a_reason() -> None:
    for payload in PAYLOADS:
        if payload.payload_id in ("forged-update", "marker-fake-superseded"):
            continue
        for quote in candidate_quotes(payload):
            decision = obedient_decision(payload, quote)
            assert decision.kind == "contradicts" and decision.downgraded, payload.payload_id
            assert decision.reason


def test_a_forged_supersession_is_recorded_with_its_evidence_for_a_reviewer() -> None:
    """When the limit above is used, the cut is not silent: the receipt names the sentence."""
    payload = by_id("forged-update")
    newer = embed(T50.replace(R10, "").rstrip() + "\n", payload)
    world = World(OLD, (U2, newer, S50, 50, "current"))
    sentence = payload.text.split(". New accounts")[0] + "."
    world.supersede(U2, U1, sentence)
    grounded = world.ground("redact", [U1, U2])
    assert [a.kind for a in grounded.actions] == ["redact"]
    (action,) = grounded.actions
    assert action.target.quote == S10  # only the stale sentence, never a page
    assert sentence in [ref.quote for _role, ref in action.evidence]
    assert "# Limits" in grounded.context and "Intro line." in grounded.context
