from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from currant.detect import (
    PROMPT_VERSION,
    RELATION_SCHEMA,
    SYSTEM_PROMPT,
    Decision,
    candidate_pairs,
    decide,
    enclosing_line,
    first_iso_date,
    jaccard,
    record,
    run_detection,
    same_kind,
    tokens,
)
from currant.serv import ModelError, ModelReply
from currant.store import ClaimRow, ClaimStore

URL_OLD, URL_NEW = "https://docs.example.com/old.md", "https://docs.example.com/new.md"
SENT_OLD = "New accounts get 10 free evaluations."
SENT_NEW = "New accounts get 50 free evaluations."
TEXT_OLD = f"# Limits\n\n{SENT_OLD}\n"
REPLACES = "This replaces the previous value of 10 in earlier documentation."
TEXT_EXPLICIT = f"# Update notice\n\n{SENT_NEW}\n\n{REPLACES}\n"
TEXT_OLD_DATED = f"Last updated: 2026-03-14\n\n# Limits\n\n{SENT_OLD}\n"
TEXT_NEW_DATED = f"## Changelog\n\n**2026-09-02**\n\n* {SENT_NEW}\n"
TEXT_PLAIN_NEW = f"# Reference\n\n{SENT_NEW}\n"


class Ctx:
    """A store with two pages and one claim on each."""

    def __init__(self, old: str, new: str) -> None:
        self.store = ClaimStore(":memory:")
        self.snapshot = self.store.ingest_pages("t", [(URL_OLD, old), (URL_NEW, new)])
        self.run = self.store.start_run("extract", "fake", "extract-v1", self.snapshot.snapshot_id)
        self.old_text, self.new_text = old, new
        self.old = self._claim(URL_OLD, old, SENT_OLD, "10 free evaluations", 10)
        self.new = self._claim(URL_NEW, new, SENT_NEW, "50 free evaluations", 50)

    def _claim(self, url: str, text: str, sentence: str, value: str, number: float) -> ClaimRow:
        doc = next(p.doc_id for p in self.store.pages(self.snapshot.snapshot_id) if p.url == url)
        start = text.index(sentence)
        claim_id = self.store.add_claim(
            self.run, doc_id=doc, start=start, end=start + len(sentence), quote=sentence,
            subject="new account", attribute="free evaluations", value_text=value,
            value_type="count", value_number=number, stance="current",
        )  # fmt: skip
        return next(c for c in self.store.claims(self.run) if c.claim_id == claim_id)


def explicit_answer(**overrides: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "relation": "supersedes", "basis": "explicit_text", "ordering_quote": REPLACES,
        "date_quote_a": None, "date_quote_b": None, "explanation": "it says so",
    }  # fmt: skip
    answer.update(overrides)
    return answer


def dated_answer(**overrides: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "relation": "supersedes", "basis": "dated", "ordering_quote": None,
        "date_quote_a": "Last updated: 2026-03-14", "date_quote_b": "**2026-09-02**",
        "explanation": "dates",
    }  # fmt: skip
    answer.update(overrides)
    return answer


# --- candidate pairs -----------------------------------------------------------------------


def test_tokens_keep_content_words_and_drop_numbers_and_stopwords() -> None:
    assert tokens("The 10 free evaluations for a new account") == frozenset(
        {"free", "evaluations", "new", "account"}
    )
    assert jaccard(frozenset({"a1", "b1"}), frozenset({"b1", "c1"})) == pytest.approx(1 / 3)
    assert jaccard(frozenset(), frozenset({"x"})) == 0.0


def test_a_conflicting_pair_on_different_pages_is_a_candidate() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    (cand,) = candidate_pairs([ctx.old, ctx.new])
    assert {cand.a.claim_id, cand.b.claim_id} == {ctx.old.claim_id, ctx.new.claim_id}
    assert cand.a.claim_id < cand.b.claim_id and cand.score > 0.5


def test_candidates_need_different_pages_different_values_and_a_current_stance() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    same_doc = ClaimRow(
        **{**ctx.new.__dict__, "claim_id": "x", "doc_id": ctx.old.doc_id, "value_key": "9"}
    )
    same_value = ClaimRow(**{**ctx.new.__dict__, "claim_id": "y", "value_key": ctx.old.value_key})
    assert candidate_pairs([ctx.old, same_doc]) == []
    assert candidate_pairs([ctx.old, same_value]) == []
    for stance in ("proposed", "rejected", "uncertain"):
        other = ClaimRow(**{**ctx.new.__dict__, "claim_id": "z", "stance": stance})
        assert candidate_pairs([ctx.old, other]) == []


def test_a_historical_claim_can_pair_with_a_current_one_but_not_with_another_historical() -> None:
    # A changelog entry is stored as historical, yet it can supersede an older page.
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    changelog = ClaimRow(**{**ctx.new.__dict__, "claim_id": "z", "stance": "historical"})
    assert len(candidate_pairs([ctx.old, changelog])) == 1
    old_historical = ClaimRow(**{**ctx.old.__dict__, "claim_id": "h", "stance": "historical"})
    assert candidate_pairs([old_historical, changelog]) == []


def test_unrelated_claims_fall_below_the_similarity_threshold() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    other = ClaimRow(
        **{
            **ctx.new.__dict__,
            "claim_id": "q",
            "subject": "billing",
            "attribute": "invoice currency",
            "quote": "Invoices are issued in euros.",
            "value_key": "euro",
        }
    )  # fmt: skip
    assert candidate_pairs([ctx.old, other]) == []


def test_max_pairs_bounds_the_work_and_the_best_pairs_come_first() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    extras = [
        ClaimRow(**{**ctx.new.__dict__, "claim_id": f"n{i}", "value_key": f"v{i}"})
        for i in range(6)
    ]
    pairs = candidate_pairs([ctx.old, *extras], max_pairs=3)
    assert len(pairs) == 3
    assert [p.score for p in pairs] == sorted((p.score for p in pairs), reverse=True)


def test_a_pair_is_kept_if_it_is_in_the_top_k_of_either_claim() -> None:
    # Recall-friendly on purpose: a claim with many look-alikes (a table of similar rows) must not
    # lose its true partner just because the partner has other admirers.
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    extras = [
        ClaimRow(**{**ctx.new.__dict__, "claim_id": f"n{i}", "value_key": f"v{i}"})
        for i in range(4)
    ]
    assert (
        len(candidate_pairs([ctx.old, *extras], top_k=1)) == 4
    )  # each extra's best partner is old


# --- deciding -------------------------------------------------------------------------------


def test_an_explicit_replacement_makes_the_page_with_the_quote_the_newer_one() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    # Page A is the old page, page B the update: the quote is on B, so B is newer.
    decision = decide(explicit_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert (decision.kind, decision.newer, decision.basis) == ("supersedes", "b", "explicit_text")
    ((page, start, end, text),) = decision.ordering
    assert page == "b" and ctx.new_text[start:end] == text == REPLACES
    # Swap which claim is A and which is B: the direction follows the evidence, not the order.
    swapped = decide(explicit_answer(), ctx.new, ctx.old, ctx.new_text, ctx.old_text)
    assert (swapped.kind, swapped.newer) == ("supersedes", "a")


def test_the_model_cannot_choose_the_direction() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    lying = explicit_answer(newer="a", explanation="page A is newer")  # extra field is ignored
    assert decide(lying, ctx.old, ctx.new, ctx.old_text, ctx.new_text).newer == "b"


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (explicit_answer(ordering_quote=None), "without an ordering quote"),
        (explicit_answer(ordering_quote="   "), "without an ordering quote"),
        (explicit_answer(ordering_quote="This invented sentence is on neither page."), "exactly 1"),
        (explicit_answer(ordering_quote=SENT_OLD + " It is a rule."), "exactly 1"),
        (explicit_answer(ordering_quote="This replaces the previous value of 99."), "exactly 1"),
        (explicit_answer(basis="none"), "without verifiable ordering"),
        (explicit_answer(basis="crawl_diff"), "without verifiable ordering"),
        ({"relation": "supersedes"}, "without verifiable ordering"),
    ],
)
def test_unverifiable_ordering_is_downgraded_to_contradicts_never_to_a_cut(
    answer: dict[str, Any], why: str
) -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    decision = decide(answer, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert (decision.kind, decision.newer, decision.downgraded) == ("contradicts", None, True)
    assert why in decision.reason


def test_a_quote_on_both_pages_is_ambiguous_and_downgraded() -> None:
    both = Ctx(f"{TEXT_OLD}\n{REPLACES}\n", TEXT_EXPLICIT)
    decision = decide(explicit_answer(), both.old, both.new, both.old_text, both.new_text)
    assert decision.downgraded and "found verbatim on 2 pages" in decision.reason


def test_an_ordering_sentence_must_mention_the_replaced_value() -> None:
    vague = "Please note this value changed recently."
    ctx = Ctx(TEXT_OLD, f"# Notice\n\n{SENT_NEW}\n\n{vague}\n")
    decision = decide(
        explicit_answer(ordering_quote=vague), ctx.old, ctx.new, ctx.old_text, ctx.new_text
    )
    assert decision.downgraded and "does not mention the replaced value" in decision.reason


def test_dates_decide_the_direction_and_our_code_compares_them() -> None:
    ctx = Ctx(TEXT_OLD_DATED, TEXT_NEW_DATED)
    decision = decide(dated_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert (decision.kind, decision.newer, decision.basis) == ("supersedes", "b", "dated")
    assert len(decision.ordering) == 2
    reversed_pages = decide(
        dated_answer(date_quote_a="**2026-09-02**", date_quote_b="Last updated: 2026-03-14"),
        ctx.new, ctx.old, ctx.new_text, ctx.old_text,
    )  # fmt: skip
    assert reversed_pages.newer == "a"  # whichever page holds the later date


@pytest.mark.parametrize(
    "overrides",
    [
        {"date_quote_a": None},
        {"date_quote_b": None},
        {"date_quote_a": "Last updated: 2030-01-01"},  # not on the page
        {"date_quote_b": "no date in this passage"},
    ],
)
def test_a_bad_date_quote_is_downgraded(overrides: dict[str, Any]) -> None:
    ctx = Ctx(TEXT_OLD_DATED, TEXT_NEW_DATED)
    decision = decide(dated_answer(**overrides), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert decision.kind == "contradicts" and decision.downgraded


def test_equal_dates_do_not_order_anything() -> None:
    same = "Last updated: 2026-03-14"
    ctx = Ctx(TEXT_OLD_DATED, f"{same}\n\n{SENT_NEW}\n")
    decision = decide(dated_answer(date_quote_b=same), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert decision.downgraded and "same date" in decision.reason


def test_first_iso_date_ignores_impossible_dates() -> None:
    assert first_iso_date("on 2026-13-45 and then 2026-09-02") == "2026-09-02"
    assert first_iso_date("no date") is None


def test_contradicts_and_unrelated_pass_through() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_PLAIN_NEW)
    contra = decide({"relation": "contradicts"}, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert (contra.kind, contra.downgraded) == ("contradicts", False)
    none = decide({"relation": "unrelated"}, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert none.kind == "unrelated"
    odd = decide({"relation": "banana"}, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert odd.kind == "contradicts" and odd.downgraded


# --- recording ------------------------------------------------------------------------------


def relate_run(ctx: Ctx) -> int:
    return ctx.store.start_run("relate", "fake", PROMPT_VERSION, ctx.snapshot.snapshot_id)


def test_a_verified_supersession_is_written_with_all_its_evidence() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    decision = decide(explicit_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    result = record(ctx.store, relate_run(ctx), ctx.old, ctx.new, decision)
    assert (result.outcome, result.kind) == ("verified", "supersedes") and result.relation_id
    row = ctx.store.conn.execute(
        "SELECT claim_a, claim_b, status, ordering_basis FROM relations"
    ).fetchone()
    assert (row["claim_a"], row["claim_b"]) == (ctx.new.claim_id, ctx.old.claim_id)  # newer, older
    assert (row["status"], row["ordering_basis"]) == ("verified", "explicit_text")
    roles = sorted(r["role"] for r in ctx.store.conn.execute("SELECT role FROM relation_evidence"))
    assert roles == ["newer", "older", "ordering"]
    assert ctx.store.check_integrity() == []


def test_a_dated_supersession_records_both_date_quotes() -> None:
    ctx = Ctx(TEXT_OLD_DATED, TEXT_NEW_DATED)
    decision = decide(dated_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert record(ctx.store, relate_run(ctx), ctx.old, ctx.new, decision).outcome == "verified"
    roles = [r["role"] for r in ctx.store.conn.execute("SELECT role FROM relation_evidence")]
    assert roles.count("ordering") == 2


def test_a_contradiction_is_recorded_with_both_claims_as_evidence() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_PLAIN_NEW)
    decision = decide({"relation": "contradicts"}, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    result = record(ctx.store, relate_run(ctx), ctx.old, ctx.new, decision)
    assert (result.outcome, result.kind) == ("verified", "contradicts")
    key = ctx.store.key_state(ctx.run, "new account", "free evaluations", relate_run_id=None)
    assert key.state == "CONTESTED"


def test_an_unrelated_pair_writes_nothing() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_PLAIN_NEW)
    decision = decide({"relation": "unrelated"}, ctx.old, ctx.new, ctx.old_text, ctx.new_text)
    assert record(ctx.store, relate_run(ctx), ctx.old, ctx.new, decision).outcome == "skipped"
    assert ctx.store.conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0


def test_evidence_that_is_not_verbatim_is_refused_by_the_database_and_rejected() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    forged = Decision(
        "supersedes", "b", "explicit_text", (("b", 0, 20, "a quote that is not there"),), "forged"
    )
    result = record(ctx.store, relate_run(ctx), ctx.old, ctx.new, forged)
    assert result.outcome == "rejected"
    assert ctx.store.conn.execute("SELECT status FROM relations").fetchone()["status"] == "rejected"
    key = ctx.store.key_state(
        ctx.run, "new account", "free evaluations", relate_run_id=result_run(ctx)
    )
    assert key.state == "CONTESTED"  # a rejected relation never resolves anything


def result_run(ctx: Ctx) -> int:
    return int(ctx.store.conn.execute("SELECT run_id FROM relations").fetchone()["run_id"])


# --- running over a store ------------------------------------------------------------------


class FakeModel:
    model = "fake"

    def __init__(self, respond: Callable[[str], ModelReply]) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, system: str, user: str, *, schema: dict[str, Any], schema_name: str,
        guard: bool, shadow_hint: str | None = None, max_completion_tokens: int | None = None,
    ) -> ModelReply:  # fmt: skip
        self.calls.append({"system": system, "user": user, "schema": schema, "guard": guard})
        return self.respond(user)


def fixed_content(content: str) -> FakeModel:
    reply = ModelReply(content, "stop", 1, 1, 5, "r")
    return FakeModel(lambda _u: reply)


def answer_reply(answer: dict[str, Any], finish: str = "stop") -> ModelReply:
    return ModelReply(json.dumps(answer), finish, 400, 60, 5, "req")


def test_run_detection_records_a_verified_supersession_behind_the_guard() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    model = FakeModel(lambda _u: answer_reply(explicit_answer()))
    summary, recorded = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, sleep=lambda _s: None
    )
    assert (summary.pairs, summary.supersedes, summary.rejected) == (1, 1, 0)
    assert [r.outcome for r in recorded] == ["verified"]
    (call,) = model.calls
    assert call["guard"] is True and call["system"] == SYSTEM_PROMPT
    assert call["schema"] is RELATION_SCHEMA
    assert (
        "<<<BEGIN PAGE A>>>" in call["user"]
        and URL_OLD in call["user"]
        and TEXT_EXPLICIT in call["user"]
    )
    status = ctx.store.conn.execute(
        "SELECT stage, status FROM runs WHERE stage = 'relate'"
    ).fetchone()
    assert (status["stage"], status["status"]) == ("relate", "complete")


def test_a_failed_verification_is_counted_as_a_downgrade_not_a_cut() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    model = FakeModel(lambda _u: answer_reply(explicit_answer(ordering_quote="not on any page")))
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, sleep=lambda _s: None
    )
    assert (summary.supersedes, summary.contradicts, summary.downgraded) == (0, 1, 1)
    assert any("exactly 1" in reason for reason in summary.reasons)


def test_a_guard_blocked_pair_is_skipped_and_logged() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    model = FakeModel(lambda _u: ModelReply("I can't share that.", "content_filter", 0, 0, 5, "r"))
    summary, recorded = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, sleep=lambda _s: None
    )
    assert (summary.guard_blocked, summary.supersedes) == (1, 0) and recorded == []
    assert any(e.kind == "pair_guard_blocked" for e in ctx.store.events())


def test_unusable_model_output_fails_the_pair_without_recording_anything() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    for content in ("not json", "[1, 2]", ""):
        model = fixed_content(content)
        summary, _ = run_detection(
            ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, sleep=lambda _s: None
        )
        assert summary.failed == 1
    assert ctx.store.conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0


def test_transient_errors_are_retried_and_permanent_ones_are_not() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    state = {"n": 0}

    def flaky(_u: str) -> ModelReply:
        state["n"] += 1
        if state["n"] < 3:
            raise ModelError("http 503", transient=True)
        return answer_reply(explicit_answer())

    waits: list[float] = []
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, FakeModel(flaky), sleep=waits.append
    )
    assert summary.supersedes == 1 and state["n"] == 3 and waits == [2.0, 4.0]

    def permanent(_u: str) -> ModelReply:
        raise ModelError("http 400", transient=False)

    model = FakeModel(permanent)
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, sleep=lambda _s: None
    )
    assert len(model.calls) == 1 and summary.failed == 1


def test_doc_ids_limit_which_claims_are_compared() -> None:
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    model = FakeModel(lambda _u: answer_reply(explicit_answer()))
    summary, _ = run_detection(
        ctx.store,
        ctx.run,
        ctx.snapshot.snapshot_id,
        model,
        doc_ids={ctx.old.doc_id},
        sleep=lambda _s: None,
    )
    assert summary.pairs == 0 and model.calls == []  # one page alone has nothing to conflict with


def test_pairs_beyond_the_cap_are_counted_and_logged_not_dropped_silently() -> None:
    # Seen on the real corpus: a cap of 400 silently dropped a real conflict ranked 424th.
    ctx = Ctx(TEXT_OLD, TEXT_EXPLICIT)
    model = FakeModel(lambda _u: answer_reply(explicit_answer()))
    summary, _ = run_detection(
        ctx.store, ctx.run, ctx.snapshot.snapshot_id, model, max_pairs=0, sleep=lambda _s: None
    )
    assert (summary.pairs, summary.left_out, model.calls) == (0, 1, [])
    assert [e.kind for e in ctx.store.events()].count("pairs_left_out") == 1


@pytest.mark.parametrize("swap", [False, True])
@pytest.mark.parametrize(
    ("old_text", "new_text", "answer"),
    [
        (TEXT_OLD, TEXT_EXPLICIT, explicit_answer()),
        (TEXT_OLD_DATED, TEXT_NEW_DATED, dated_answer()),
        (TEXT_OLD, TEXT_PLAIN_NEW, {"relation": "contradicts"}),
    ],
)
def test_a_value_cannot_be_superseded_or_contested_by_a_different_kind_of_value(
    old_text: str, new_text: str, answer: dict[str, Any], swap: bool
) -> None:
    # Seen on a real dev item: a page date orders PAGES, not claims, so "48-hour" was "superseded"
    # by an unrelated claim ("for or against") extracted from the newer page's same sentence. Nor
    # is it CONTESTED: two kinds of value are not one fact, and a false notice makes the answering
    # model abstain.
    ctx = Ctx(old_text, new_text)
    other_kind = ClaimRow(**{**ctx.new.__dict__, "value_type": "enum", "value_number": None})
    a, b = (other_kind, ctx.old) if swap else (ctx.old, other_kind)
    text_a, text_b = (new_text, old_text) if swap else (old_text, new_text)
    if swap:  # the date quotes follow their pages
        answer = {
            **answer,
            "date_quote_a": answer.get("date_quote_b"),
            "date_quote_b": answer.get("date_quote_a"),
        }
    decision = decide(answer, a, b, text_a, text_b)
    assert decision.kind == "unrelated" and decision.downgraded
    assert "same kind of value" in decision.reason


def test_the_same_kind_of_value_still_supersedes() -> None:
    ctx = Ctx(TEXT_OLD_DATED, TEXT_NEW_DATED)
    assert decide(dated_answer(), ctx.old, ctx.new, ctx.old_text, ctx.new_text).kind == "supersedes"


def row(**fields: Any) -> ClaimRow:
    base: dict[str, Any] = {
        "claim_id": "c", "doc_id": "d", "run_id": 1, "start_char": 0, "end_char": 1,
        "quote": "q", "subject": "s", "subject_key": "s", "attribute": "a", "attribute_key": "a",
        "value_text": "v", "value_key": "v", "value_type": "count", "value_number": 1.0,
        "unit": None, "stance": "current", "asserted_at": None,
    }  # fmt: skip
    base.update(fields)
    return ClaimRow(**base)


def test_numeric_types_match_only_when_they_name_the_same_unit() -> None:
    # Seen on dev: "100 credits" typed as a count on one page and "50 credits" as money on the
    # other, so a dated update was never applied.
    count = row(value_text="100 credits", value_type="count")
    assert same_kind(count, row(value_text="50 credits", value_type="money", unit="Credits"))
    assert same_kind(  # a bare number takes its unit from the sentence
        row(value_text="240", value_type="number", quote="Max 240 characters"),
        row(value_text="80 characters", value_type="count"),
    )
    assert not same_kind(count, row(value_text="$50", value_type="money", unit="$"))
    assert not same_kind(count, row(value_text="100 credits", value_type="enum"))
    assert not same_kind(  # no unit on one side: no guess
        row(value_text="30", value_type="number", quote="the previous value of 30 in the docs"),
        row(value_text="30 days", value_type="duration"),
    )


def test_a_claim_quoted_as_a_fragment_still_meets_its_counterpart_through_its_line() -> None:
    # Seen on dev: the newer row was quoted as "Maximum 50 characters." and never paired.
    new_line = "| `symbol` | Ticker symbol of the primary token. Maximum 50 characters. |"
    old = row(
        claim_id="o", doc_id="d1", value_key="5", value_text="5 characters",
        quote="Ticker symbol of the primary token. Maximum 5 characters.",
        subject="Datanet draft", attribute="nativeTokenSymbol maximum length",
    )  # fmt: skip
    start = new_line.index("Maximum")
    new = row(
        claim_id="n", doc_id="d2", value_key="50", value_text="50 characters",
        quote="Maximum 50 characters.", subject="Ticker symbol of the primary token",
        attribute="maximum length", start_char=start, end_char=start + 22,
    )  # fmt: skip
    assert enclosing_line(f"# Fields\n{new_line}\nmore", start + 9, start + 31) == new_line
    assert candidate_pairs([old, new]) == []
    (cand,) = candidate_pairs([old, new], lines={"n": new_line, "o": old.quote})
    assert {cand.a.claim_id, cand.b.claim_id} == {"o", "n"}


OLD_TABLE = (
    "Last updated: 2026-03-14\n\n"
    "| `context` | Optional, up to 32 KB |\n| `criteria` | Optional, up to 2 KB |\n"
)
NEW_TABLE = "## Changelog\n\n**2026-09-02**\n\n* `context` | Optional, up to 320 KB\n"


def test_one_new_value_retires_only_one_old_value_per_page() -> None:
    # Seen on dev: a new `context` limit also "superseded" the `criteria` limit in the next row,
    # because page dates order pages, not claims. The better-matching pair wins; the other is
    # neither cut nor contested.
    store = ClaimStore(":memory:")
    snap = store.ingest_pages("t", [(URL_OLD, OLD_TABLE), (URL_NEW, NEW_TABLE)])
    run = store.start_run("extract", "fake", "extract-v1", snap.snapshot_id)
    docs = {p.url: p.doc_id for p in store.pages(snap.snapshot_id)}
    for url, text, field, size in (
        (URL_OLD, OLD_TABLE, "context", 32), (URL_OLD, OLD_TABLE, "criteria", 2),
        (URL_NEW, NEW_TABLE, "context", 320),
    ):  # fmt: skip
        quote = f"`{field}` | Optional, up to {size} KB"
        start = text.index(quote)
        store.add_claim(
            run, doc_id=docs[url], start=start, end=start + len(quote), quote=quote,
            subject=field, attribute="maximum size", value_text=f"up to {size} KB",
            value_type="number", value_number=size, stance="current",
        )  # fmt: skip
    store.finish_run(run)

    def respond(user: str) -> ModelReply:
        old_is_a = f"(page A, {URL_OLD})" in user
        dates = ("Last updated: 2026-03-14", "**2026-09-02**")
        a, b = dates if old_is_a else dates[::-1]
        return answer_reply(dated_answer(date_quote_a=a, date_quote_b=b))

    summary, recorded = run_detection(
        store, run, snap.snapshot_id, FakeModel(respond), sleep=lambda _s: None
    )
    assert summary.pairs == 2 and summary.supersedes == 1
    assert [r.outcome for r in recorded] == ["verified", "skipped"]
    assert "already replaces a different value" in recorded[1].reason
    (older,) = store.conn.execute(
        "SELECT c.value_text FROM relations r JOIN claims c ON c.claim_id = r.claim_b"
        " WHERE r.status = 'verified'"
    ).fetchall()
    assert older["value_text"] == "up to 32 KB"
