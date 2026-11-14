from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from currant.detect import PROMPT_VERSION, decide, record
from currant.ground import MODES, REMOVED, Retrieved, ground
from currant.store import ClaimRow, ClaimStore, EvidenceRow

U1, U2, U3 = (f"https://docs.example.com/p{i}.md" for i in (1, 2, 3))
S10 = "New accounts get 10 free evaluations."
S50 = "New accounts get 50 free evaluations."
S70 = "New accounts get 70 free evaluations."
R10 = "This replaces the previous value of 10 in earlier documentation."
R50 = "This replaces the previous value of 50 in earlier documentation."
T10 = f"# Limits\n\nIntro line.\n\n{S10}\n\nOutro line.\n"
T50 = f"# Update notice\n\n{S50}\n\n{R10}\n"
T70 = f"# Newer notice\n\n{S70}\n\n{R50}\n"
T_PLAIN = f"# Reference\n\n{S50}\n"
HISTORY = "Previously accounts got 10 free evaluations, and now they get 50."
T_HISTORY = f"# History\n\n{HISTORY}\n"


def answer(basis_quote: str) -> dict[str, Any]:
    return {
        "relation": "supersedes", "basis": "explicit_text", "ordering_quote": basis_quote,
        "date_quote_a": None, "date_quote_b": None, "explanation": "it says so",
    }  # fmt: skip


class World:
    """Pages on one store, one claim per page, and relations added by hand."""

    def __init__(
        self, *pages: tuple[str, str, str, float, str], open_extract: bool = False
    ) -> None:
        # each page: (url, text, sentence, number, stance)
        self.store = ClaimStore(":memory:")
        self.texts = {p[0]: p[1] for p in pages}
        snap = self.store.ingest_pages("t", [(p[0], p[1]) for p in pages])
        self.snapshot_id = snap.snapshot_id
        self.extract = self.store.start_run("extract", "fake", "extract-v1", snap.snapshot_id)
        self.claims: dict[str, ClaimRow] = {}
        for url, text, sentence, number, stance in pages:
            doc = next(x.doc_id for x in self.store.pages(snap.snapshot_id) if x.url == url)
            start = text.index(sentence)
            claim_id = self.store.add_claim(
                self.extract, doc_id=doc, start=start, end=start + len(sentence), quote=sentence,
                subject="new account", attribute="free evaluations",
                value_text=f"{int(number)} free evaluations", value_type="count",
                value_number=number, stance=stance,
            )  # fmt: skip
            self.claims[url] = next(
                c for c in self.store.claims(self.extract) if c.claim_id == claim_id
            )
        if not open_extract:  # left open, a test can add more claims and finish it itself
            self.store.finish_run(self.extract)  # Ground only reads a finished extract run
        self.relate = self.store.start_run("relate", "fake", PROMPT_VERSION, snap.snapshot_id)

    def doc(self, url: str) -> Retrieved:
        return Retrieved(self.claims[url].doc_id, url)

    def supersede(self, newer: str, older: str, quote: str, run: int | None = None) -> str:
        decision = decide(
            answer(quote),
            self.claims[older],
            self.claims[newer],
            self.texts[older],
            self.texts[newer],
        )
        result = record(
            self.store, run or self.relate, self.claims[older], self.claims[newer], decision
        )
        assert result.outcome == "verified" and decision.kind == "supersedes", decision
        assert result.relation_id is not None
        return result.relation_id

    def contradict(self, a: str, b: str) -> None:
        decision = decide({"relation": "contradicts"}, self.claims[a], self.claims[b], "", "")
        assert (
            record(self.store, self.relate, self.claims[a], self.claims[b], decision).outcome
            == "verified"
        )

    def finish(self) -> None:
        """Relations can only be added to a running run, and Ground only reads a finished one."""
        if self.store.run_meta(self.relate).status == "running":
            self.store.finish_run(self.relate)

    def ground(self, mode: str, urls: list[str], **kw: Any) -> Any:
        self.finish()
        return ground(
            self.store, [self.doc(u) for u in urls], mode=mode,
            extract_run_id=self.extract, relate_run_id=kw.pop("relate", self.relate), **kw,
        )  # fmt: skip


def simple() -> World:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    world.supersede(U2, U1, R10)
    return world


def test_baseline_returns_the_pages_untouched_and_takes_no_action() -> None:
    result = simple().ground("baseline", [U1, U2])
    assert result.actions == []
    assert T10 in result.context and T50 in result.context
    assert REMOVED not in result.context


def test_redact_removes_only_the_stale_sentence_not_the_page() -> None:
    result = simple().ground("redact", [U1, U2])
    assert S10 not in result.context and REMOVED in result.context
    assert "# Limits" in result.context and "Intro line." in result.context  # the page survives
    assert "Outro line." in result.context
    assert S50 in result.context  # the winning page is untouched
    assert [a.kind for a in result.actions] == ["redact"]


def test_annotate_keeps_the_stale_sentence_and_points_to_the_winner() -> None:
    result = simple().ground("annotate", [U1, U2])
    assert S10 in result.context and REMOVED not in result.context
    assert f'[SUPERSEDED: the current documentation says: "{S50}" ({U2})]' in result.context
    assert [a.kind for a in result.actions] == ["annotate"]


def test_pull_adds_the_newer_evidence_when_only_the_stale_page_was_retrieved() -> None:
    result = simple().ground("pull", [U1])
    assert S10 in result.context  # pull never edits the stale page
    assert f'{U2}: "{S50}"' in result.context
    assert [a.kind for a in result.actions] == ["pull"]


def test_pull_adds_nothing_when_the_newer_page_is_already_in_context() -> None:
    result = simple().ground("pull", [U1, U2])
    assert result.actions == []


def test_redact_plus_pull_does_both() -> None:
    result = simple().ground("redact_pull", [U1])
    assert S10 not in result.context and REMOVED in result.context
    assert f'{U2}: "{S50}"' in result.context
    assert sorted(a.kind for a in result.actions) == ["pull", "redact"]


def test_a_relation_that_is_only_proposed_changes_nothing() -> None:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    world.store.propose_relation(world.relate, "supersedes", world.claims[U2].claim_id,
                                 world.claims[U1].claim_id, "explicit_text")  # fmt: skip
    for mode in MODES:
        result = world.ground(mode, [U1, U2])
        assert result.actions == [] and S10 in result.context


def test_a_relation_from_another_run_is_not_used() -> None:
    world = simple()
    other = world.store.start_run("relate", "fake", PROMPT_VERSION, world.snapshot_id)
    world.store.finish_run(other)
    result = world.ground("redact", [U1, U2], relate=other)
    assert result.actions == [] and S10 in result.context


def test_a_historical_sentence_is_never_cut_even_if_a_relation_says_so() -> None:
    # "Previously X, now Y" is already past tense. It must survive (invariant: cut spans that are
    # stale, not text that reports a change).
    world = World((U3, T_HISTORY, HISTORY, 10, "historical"), (U2, T50, S50, 50, "current"))
    world.supersede(U2, U3, R10)
    result = world.ground("redact", [U3, U2])
    assert HISTORY in result.context and REMOVED not in result.context and result.actions == []


def test_two_winners_over_the_same_span_produce_one_removal() -> None:
    other_notice = f"# Another notice\n\n{S70}\n\n{R10}\n"  # a second page replacing the same value
    world = World(
        (U1, T10, S10, 10, "current"),
        (U2, T50, S50, 50, "current"),
        (U3, other_notice, S70, 70, "current"),
    )
    world.supersede(U2, U1, R10)
    world.supersede(U3, U1, R10)
    result = world.ground("redact", [U1])
    assert result.context.count(REMOVED) == 1 and S10 not in result.context
    assert len(result.actions) == 2  # both reasons are recorded in the receipt


def chain() -> World:
    world = World(
        (U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"), (U3, T70, S70, 70, "current")
    )
    world.supersede(U2, U1, R10)
    world.supersede(U3, U2, R50)
    return world


def test_pull_follows_a_chain_to_the_latest_value_never_an_intermediate_one() -> None:
    result = chain().ground("pull", [U1])
    assert f'{U3}: "{S70}"' in result.context
    assert S50 not in result.context  # the middle value is stale too


def test_annotate_follows_a_chain_to_the_latest_value() -> None:
    result = chain().ground("annotate", [U1])
    assert f'"{S70}" ({U3})' in result.context and f'"{S50}"' not in result.context


def test_both_stale_pages_are_handled_when_both_are_retrieved() -> None:
    result = chain().ground("redact", [U1, U2, U3])
    assert S10 not in result.context and S50 not in result.context and S70 in result.context
    assert result.context.count(REMOVED) == 2


def contested() -> World:
    world = World((U1, T10, S10, 10, "current"), (U2, T_PLAIN, S50, 50, "current"))
    world.contradict(U1, U2)
    return world


@pytest.mark.parametrize("mode", [m for m in MODES if m != "baseline"])
def test_contested_pairs_get_a_notice_with_both_quotes_and_nothing_is_cut(mode: str) -> None:
    result = contested().ground(mode, [U1, U2])
    assert "CONTESTED" in result.context
    assert f'{U1}: "{S10}"' in result.context and f'{U2}: "{S50}"' in result.context
    assert REMOVED not in result.context and S10 in result.context and S50 in result.context
    assert [a.kind for a in result.actions] == ["contested"]


def test_baseline_never_adds_a_contested_notice() -> None:
    assert "CONTESTED" not in contested().ground("baseline", [U1, U2]).context


def test_a_contested_notice_appears_when_only_one_side_was_retrieved() -> None:
    result = contested().ground("redact", [U1])
    assert "CONTESTED" in result.context and f'{U2}: "{S50}"' in result.context


def test_a_contradiction_already_resolved_by_a_supersession_is_not_contested() -> None:
    world = simple()
    world.contradict(U1, U2)
    result = world.ground("redact", [U1, U2])
    assert "CONTESTED" not in result.context and [a.kind for a in result.actions] == ["redact"]


def test_a_sentence_already_put_in_order_gets_no_contested_notice() -> None:
    # Seen on dev: one sentence held several claims. Its number was rightly superseded, and another
    # claim of the SAME sentence was contested against the newer page; the notice made the model
    # abstain on a question the pages answered.
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"), open_extract=True)
    extra = {}
    for url, sentence, value in ((U1, S10, "New accounts"), (U2, S50, "accounts")):
        start = world.texts[url].index(sentence)
        claim_id = world.store.add_claim(
            world.extract, doc_id=world.claims[url].doc_id, start=start,
            end=start + len(sentence), quote=sentence, subject="account", attribute="who",
            value_text=value, value_type="text", value_number=None, stance="current",
        )  # fmt: skip
        extra[url] = next(c for c in world.store.claims(world.extract) if c.claim_id == claim_id)
    world.store.finish_run(world.extract)
    world.supersede(U2, U1, R10)
    decision = decide({"relation": "contradicts"}, extra[U1], extra[U2], "", "")
    assert record(world.store, world.relate, extra[U1], extra[U2], decision).outcome == "verified"
    result = world.ground("annotate", [U1, U2])
    assert "CONTESTED" not in result.context and [a.kind for a in result.actions] == ["annotate"]


def test_grounding_is_deterministic() -> None:
    world = chain()
    first, second = world.ground("redact_pull", [U1]), world.ground("redact_pull", [U1])
    assert first.context == second.context and first.actions == second.actions


def test_the_order_pages_were_retrieved_in_is_kept() -> None:
    world = simple()
    forward, backward = world.ground("baseline", [U1, U2]), world.ground("baseline", [U2, U1])
    assert forward.context.index(U1) < forward.context.index(U2)
    assert backward.context.index(U2) < backward.context.index(U1)


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="mode"):
        simple().ground("shred", [U1])


def test_a_document_not_in_the_store_is_refused() -> None:
    world = simple()
    world.finish()
    with pytest.raises(Exception, match="unknown document"):
        ground(
            world.store, [Retrieved("0" * 64, "https://x/y.md")], mode="baseline",
            extract_run_id=world.extract, relate_run_id=world.relate,
        )  # fmt: skip


def test_a_forged_url_is_refused_so_it_cannot_reach_a_receipt() -> None:
    world = simple()
    world.finish()
    forged = Retrieved(world.claims[U1].doc_id, "https://evil.example/fake.md")
    with pytest.raises(ValueError, match="not the url"):
        ground(
            world.store, [forged], mode="baseline",
            extract_run_id=world.extract, relate_run_id=world.relate,
        )  # fmt: skip


def test_only_the_winner_retrieved_means_nothing_to_cut_or_annotate() -> None:
    for mode in ("redact", "annotate", "pull", "redact_pull"):
        assert simple().ground(mode, [U2]).actions == []


def test_a_branching_chain_has_no_single_winner_so_no_annotation_and_no_pull() -> None:
    u4 = "https://docs.example.com/p4.md"
    s90 = "New accounts get 90 free evaluations."
    branch = "\n\n".join(["# Branch notice", s90, R50]) + "\n"
    world = World(
        (U1, T10, S10, 10, "current"),
        (U2, T50, S50, 50, "current"),
        (U3, T70, S70, 70, "current"),
        (u4, branch, s90, 90, "current"),
    )
    world.supersede(U2, U1, R10)
    world.supersede(U3, U2, R50)
    world.supersede(u4, U2, R50)  # two different replacements of the same value
    for mode in ("annotate", "pull"):
        assert world.ground(mode, [U1]).actions == [], mode
    assert [a.kind for a in world.ground("redact", [U1]).actions] == ["redact"]  # still stale


def test_a_replacement_loop_has_no_winner_so_no_annotation_and_no_pull() -> None:
    first = "\n\n".join(["# A", S10, R50]) + "\n"  # says it replaces 50
    second = "\n\n".join(["# B", S50, R10]) + "\n"  # says it replaces 10
    world = World((U1, first, S10, 10, "current"), (U2, second, S50, 50, "current"))
    world.supersede(U2, U1, R10)
    world.supersede(U1, U2, R50)
    for mode in ("annotate", "pull"):
        assert world.ground(mode, [U1]).actions == [], mode


def test_a_contradiction_with_a_historical_side_is_not_contested() -> None:
    world = World((U3, T_HISTORY, HISTORY, 10, "historical"), (U2, T_PLAIN, S50, 50, "current"))
    world.contradict(U3, U2)
    result = world.ground("redact", [U3, U2])
    assert result.actions == [] and "CONTESTED" not in result.context


def test_a_contradiction_between_pages_nobody_retrieved_is_not_raised() -> None:
    world = World(
        (U1, T10, S10, 10, "current"),
        (U2, T_PLAIN, S50, 50, "current"),
        (U3, T70, S70, 70, "current"),
    )
    world.contradict(U1, U2)
    assert world.ground("redact", [U3]).actions == []


def test_a_fully_evidenced_relation_that_was_never_verified_is_not_used() -> None:
    # Everything is in place except the database's decision. Only that decision may count.
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    store, old, new = world.store, world.claims[U1], world.claims[U2]
    rid = store.propose_relation(world.relate, "supersedes", new.claim_id, old.claim_id,
                                 "explicit_text")  # fmt: skip
    store.add_evidence(rid, old.doc_id, old.start_char, old.end_char, old.quote, "older")
    store.add_evidence(rid, new.doc_id, new.start_char, new.end_char, new.quote, "newer")
    start = T50.index(R10)
    assert store.add_evidence(rid, new.doc_id, start, start + len(R10), R10, "ordering")
    assert store.relation_status(rid) == "proposed"
    for mode in MODES:
        assert world.ground(mode, [U1, U2]).actions == [], mode


class Tampered:
    """A store whose reads can be bent, to test checks that normally never trigger because the
    database forbids the bad state in the first place."""

    def __init__(self, inner: ClaimStore, *, claims: Any = None, evidence: Any = None) -> None:
        self._inner, self._claims, self._evidence = inner, claims, evidence

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def claims(self, run_id: int) -> list[ClaimRow]:
        rows = self._inner.claims(run_id)
        return self._claims(rows) if self._claims else rows

    def relation_evidence(self, relation_id: str) -> list[EvidenceRow]:
        rows = self._inner.relation_evidence(relation_id)
        return self._evidence(rows) if self._evidence else rows


def grounded_with(world: World, mode: str, tampered: Tampered) -> Any:
    world.finish()
    return ground(
        cast(ClaimStore, tampered), [world.doc(U1), world.doc(U2)], mode=mode,
        extract_run_id=world.extract, relate_run_id=world.relate,
    )  # fmt: skip


def test_evidence_the_database_marked_unverified_never_appears_in_an_action() -> None:
    world = simple()
    junk = EvidenceRow(world.claims[U1].doc_id, 0, 5, "bogus", "ordering", False)
    result = grounded_with(world, "redact", Tampered(world.store, evidence=lambda r: [*r, junk]))
    (action,) = result.actions
    assert all(ref.quote != "bogus" for _role, ref in action.evidence)


def test_a_stale_span_that_is_no_longer_verbatim_is_not_cut() -> None:
    world = simple()
    bent = Tampered(
        world.store,
        claims=lambda rows: [replace(c, quote="Not what the page says.") for c in rows],
    )
    result = grounded_with(world, "redact", bent)
    assert result.actions == [] and S10 in result.context


def test_evidence_that_is_no_longer_verbatim_blocks_the_action() -> None:
    world = simple()
    bent = Tampered(
        world.store, evidence=lambda rows: [replace(r, quote="Altered quote.") for r in rows]
    )
    result = grounded_with(world, "redact", bent)
    assert result.actions == [] and S10 in result.context
