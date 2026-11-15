from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.crawl.config import Corpus
from currant.extract import (
    EXTRACTION_SCHEMA,
    LARGE_OUTPUT_TOKENS,
    PROMPT_VERSION,
    SHADOW_HINT,
    SYSTEM_PROMPT,
    Accepted,
    Rejected,
    build_user_message,
    locate,
    numbers_in,
    parse_claims,
    run_extraction,
    validate_proposal,
)
from currant.serv import ModelError, ModelReply
from currant.store import ClaimStore, StoreError
from tests.helpers import md
from tests.test_cli import patch_network
from tests.test_crawl import crawl
from tests.test_store import NEW_URL, OLD_QUOTE, OLD_TEXT, OLD_URL, World

BASE = "https://docs.example.com"


def good(**overrides: Any) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "quote": OLD_QUOTE,
        "subject": "new account",
        "attribute": "free evaluations",
        "value_text": "10 free evaluations",
        "value_type": "count",
        "value_number": 10,
        "unit": "evaluations",
        "stance": "current",
        "asserted_at": None,
    }
    claim.update(overrides)
    return claim


def reply(claims: list[Any] | str, finish: str = "stop", **kwargs: Any) -> ModelReply:
    content = claims if isinstance(claims, str) else json.dumps({"claims": claims})
    return ModelReply(content, finish, kwargs.get("pt", 120), kwargs.get("ct", 40), 5, "req-1")


class FakeModel:
    model = "fake-model"

    def __init__(self, respond: Callable[[str, bool], ModelReply]) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        schema: dict[str, Any],
        schema_name: str,
        guard: bool,
        shadow_hint: str | None = None,
        max_completion_tokens: int | None = None,
    ) -> ModelReply:
        self.calls.append(
            {"system": system, "user": user, "guard": guard, "shadow_hint": shadow_hint,
             "schema": schema, "schema_name": schema_name, "max_tokens": max_completion_tokens}
        )  # fmt: skip
        return self.respond(user, guard)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path, new_page=False)  # one page, so the simple cases stay simple


@pytest.fixture
def two_pages(tmp_path: Path) -> World:
    return World(tmp_path)


def no_sleep(_seconds: float) -> None:
    return None


# --- the pure checks ------------------------------------------------------------------------


def test_numbers_are_read_as_written_and_scaled() -> None:
    assert numbers_in("limit is 1,000 per day") == {1000.0}
    assert numbers_in("2.5k tokens") == {2.5, 2500.0}
    assert numbers_in("up to 5M requests") == {5.0, 5_000_000.0}
    assert numbers_in("a 10% discount") == {10.0}
    assert 0.13 in numbers_in("$0.13 per million")
    assert numbers_in("3 million rows") == {3.0, 3_000_000.0}


def test_locate_finds_an_exact_unique_quote() -> None:
    span = locate("Alpha. Beta gamma. Delta.", "Beta gamma.")
    assert not isinstance(span, str) and (span.start, span.end, span.exact) == (7, 18, True)


def test_locate_tolerates_whitespace_differences_only() -> None:
    text = "New accounts get 10 free evaluations."
    span = locate(text, "New accounts get  10 free\nevaluations.")
    assert not isinstance(span, str) and text[span.start : span.end] == text and not span.exact
    assert locate(text, "New accounts receive 10 free evaluations.") == "quote_not_found"
    assert (
        locate(text, "New accounts get 10 FREE evaluations.") == "quote_not_found"
    )  # case matters


def test_locate_refuses_a_quote_that_could_mean_two_places() -> None:
    result = locate("Limit is 10. Other text. Limit is 10.", "Limit is 10.")
    assert isinstance(result, str) and result.startswith("quote_ambiguous")
    assert locate("a b", "   ") == "quote_empty"


def test_a_good_proposal_is_accepted_with_the_pages_own_text_and_offsets() -> None:
    verdict = validate_proposal(OLD_TEXT, good(quote="New accounts get 10  free evaluations."))
    assert isinstance(verdict, Accepted)
    assert OLD_TEXT[verdict.start : verdict.end] == OLD_QUOTE == verdict.fields["quote"]
    # The copy has a doubled space, so it matched loosely; the stored quote is still the page's.
    assert verdict.fields["value_number"] == 10.0 and verdict.flags == ("quote_matched_loosely",)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"quote": "New accounts receive ten free evaluations."}, "quote_not_found"),
        ({"quote": ""}, "quote_empty"),
        ({"value_text": "20 free evaluations"}, "value_not_in_quote"),
        ({"value_number": 11}, "number_not_in_quote"),
        ({"value_type": "text", "value_number": 10}, "number_type_mismatch"),
        ({"value_type": "colour"}, "bad_enum"),
        ({"stance": "maybe"}, "bad_enum"),
        ({"subject": "  "}, "malformed"),
        ({"value_number": True}, "malformed"),
        ({"value_number": "10"}, "malformed"),
        ({"unit": 3}, "malformed"),
    ],
)
def test_bad_proposals_are_rejected_with_a_reason(overrides: dict[str, Any], code: str) -> None:
    verdict = validate_proposal(OLD_TEXT, good(**overrides))
    assert isinstance(verdict, Rejected) and verdict.code == code


def test_proposals_that_are_not_objects_or_miss_fields_are_rejected() -> None:
    for broken in ("a string", 3, None, {"quote": OLD_QUOTE}):
        verdict = validate_proposal(OLD_TEXT, broken)
        assert isinstance(verdict, Rejected) and verdict.code == "malformed"


def test_a_question_is_not_a_claim() -> None:
    text = "Do new accounts get 10 free evaluations?\n"
    verdict = validate_proposal(text, good(quote="Do new accounts get 10 free evaluations?"))
    assert isinstance(verdict, Rejected) and verdict.code == "question"


def test_a_number_may_be_the_scaled_form_of_what_is_written() -> None:
    text = "Up to 5M requests per month.\n"
    for number in (5, 5_000_000):
        verdict = validate_proposal(
            text,
            good(
                quote="Up to 5M requests per month.", value_text="5M requests", value_number=number
            ),
        )
        assert isinstance(verdict, Accepted)


def test_a_date_must_be_real_and_stated_by_the_page() -> None:
    text = "As of 2026-09-11, new accounts get 10 free evaluations.\n"
    quote = "As of 2026-09-11, new accounts get 10 free evaluations."
    kept = validate_proposal(text, good(quote=quote, asserted_at="2026-09-11"))
    assert isinstance(kept, Accepted) and kept.fields["asserted_at"] == "2026-09-11"
    for bad in ("2026-09-12", "11/09/2026", "2026-13-45"):
        dropped = validate_proposal(text, good(quote=quote, asserted_at=bad))
        assert isinstance(dropped, Accepted) and dropped.fields["asserted_at"] is None
        assert "asserted_at_unsupported" in dropped.flags


def test_a_loosely_matched_quote_is_flagged_and_the_page_text_is_what_is_stored() -> None:
    # The model's copy differs from the page in whitespace and a markdown escape. The claim is
    # kept, but flagged, and what is stored is the page's own text at the span, not the copy.
    text = "Each   account gets \\$10 of\ncredit.\n"
    copied = "Each account gets $10 of credit."
    verdict = validate_proposal(text, good(quote=copied, value_text="$10", value_number=10))
    assert isinstance(verdict, Accepted)
    assert "quote_matched_loosely" in verdict.flags
    assert verdict.fields["quote"] == "Each   account gets \\$10 of\ncredit."
    assert text[verdict.start : verdict.end] == verdict.fields["quote"]

    verbatim = validate_proposal(
        text, good(quote="Each   account gets \\$10 of", value_text="$10", value_number=10)
    )
    assert isinstance(verbatim, Accepted) and "quote_matched_loosely" not in verbatim.flags


def test_parse_claims_explains_unusable_output() -> None:
    assert parse_claims('{"claims": []}') == []
    assert parse_claims("not json") == "invalid JSON"
    assert parse_claims(None) == "empty response"
    assert parse_claims('{"other": 1}') == "response has no claims array"
    assert parse_claims("[1, 2]") == "response has no claims array"


def test_the_schema_is_strict_at_both_levels() -> None:
    assert EXTRACTION_SCHEMA["additionalProperties"] is False
    item = EXTRACTION_SCHEMA["properties"]["claims"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])  # strict mode needs every field


def test_the_prompt_treats_the_page_as_data_and_the_message_marks_its_edges() -> None:
    assert "DATA" in SYSTEM_PROMPT and "Never follow" in SYSTEM_PROMPT
    message = build_user_message("https://x/y.md", "page body")
    assert (
        message.index("<<<BEGIN PAGE>>>")
        < message.index("page body")
        < message.index("<<<END PAGE>>>")
    )
    assert "https://x/y.md" in message


# --- running extraction over a snapshot ----------------------------------------------------


def ok_model() -> FakeModel:
    return FakeModel(lambda _u, _g: reply([good()]))


def fixed_reply(content: str) -> FakeModel:
    answer = reply(content)
    return FakeModel(lambda _u, _g: answer)


def test_a_run_stores_verified_claims_and_records_how_it_was_made(world: World) -> None:
    model = ok_model()
    summary = run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)

    assert (summary.pages_total, summary.pages_ok, summary.accepted, summary.proposals) == (
        1,
        1,
        1,
        1,
    )
    (row,) = world.store.claims(summary.run_id)
    assert OLD_TEXT[row.start_char : row.end_char] == row.quote == OLD_QUOTE
    run = world.store.conn.execute(
        "SELECT * FROM runs WHERE run_id = ?", (summary.run_id,)
    ).fetchone()
    assert (run["stage"], run["status"], run["model"], run["prompt_version"]) == (
        "extract", "complete", "fake-model", PROMPT_VERSION,
    )  # fmt: skip
    params = json.loads(run["params"])
    assert params["guard"] is True and params["shadow_agent"] is False
    assert "split" not in params  # pages are not split; evaluation items are
    assert world.store.check_integrity() == []


def test_the_model_sees_the_page_behind_the_guard(world: World) -> None:
    model = ok_model()
    run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    (call,) = model.calls
    assert call["guard"] is True and call["shadow_hint"] is None
    assert call["system"] == SYSTEM_PROMPT and call["schema"] is EXTRACTION_SCHEMA
    assert OLD_URL in call["user"] and OLD_TEXT in call["user"]


def test_the_shadow_agent_is_off_by_default_and_on_when_asked(world: World) -> None:
    # Off by default: a 3-page A/B on 2026-11-05 showed no visible benefit for 4x the latency.
    model = ok_model()
    summary = run_extraction(world.store, world.snapshot_id, model, shadow=True, sleep=no_sleep)
    assert model.calls[0]["shadow_hint"] == SHADOW_HINT
    run = world.store.conn.execute(
        "SELECT params FROM runs WHERE run_id = ?", (summary.run_id,)
    ).fetchone()
    assert json.loads(run["params"])["shadow_agent"] is True


def test_every_page_is_extracted_and_nothing_is_held_back_by_a_lock(two_pages: World) -> None:
    model = ok_model()
    summary = run_extraction(two_pages.store, two_pages.snapshot_id, model, sleep=no_sleep)
    assert summary.pages_total == 2
    sent = sorted(OLD_URL in c["user"] for c in model.calls)
    assert sent == [False, True] and any(NEW_URL in c["user"] for c in model.calls)


def test_invented_and_malformed_proposals_never_reach_the_store(world: World) -> None:
    claims = [
        good(),
        good(
            quote="New accounts get 99 free evaluations.",
            value_text="99 free evaluations",
            value_number=99,
        ),
        good(value_number=11),
        {"quote": OLD_QUOTE},
    ]
    summary = run_extraction(
        world.store, world.snapshot_id, FakeModel(lambda _u, _g: reply(claims)), sleep=no_sleep
    )
    assert (summary.proposals, summary.accepted) == (4, 1)
    assert summary.rejected_by_code == {
        "malformed": 1,
        "number_not_in_quote": 1,
        "quote_not_found": 1,
    }
    assert len(world.store.claims(summary.run_id)) == 1
    logged = [e for e in world.store.events() if e.kind == "claim_rejected"]
    assert len(logged) == 3 and all(json.loads(e.payload)["url"] == OLD_URL for e in logged)


def test_unusable_model_output_fails_the_page_and_leaves_the_run_open(world: World) -> None:
    for content in ("not json at all", '{"nope": 1}'):
        summary = run_extraction(
            world.store, world.snapshot_id, fixed_reply(content), sleep=no_sleep
        )
        assert summary.pages_failed == 1 and summary.failed_urls == [OLD_URL]
        assert world.store.claims(summary.run_id) == []
    statuses = {r["status"] for r in world.store.conn.execute("SELECT status FROM runs")}
    # A failed page leaves the run open: it can be resumed, and nothing downstream (relate,
    # ground) accepts a run that is not complete.
    assert statuses == {"running"}
    assert any(e.kind == "run_incomplete" for e in world.store.events())


def test_a_truncated_output_is_not_parsed(world: World) -> None:
    summary = run_extraction(
        world.store,
        world.snapshot_id,
        FakeModel(lambda _u, _g: reply('{"claims": [', finish="length")),
        sleep=no_sleep,
    )
    assert summary.pages_failed == 1
    assert any("truncated" in e.payload for e in world.store.events() if e.kind == "page_failed")


def test_a_guard_blocked_page_is_skipped_not_retried_unguarded_by_default(world: World) -> None:
    model = FakeModel(lambda _u, _g: reply("I can't share that.", finish="content_filter"))
    summary = run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    assert summary.pages_guard_blocked == 1 and summary.guard_blocked_urls == [OLD_URL]
    assert len(model.calls) == 1 and model.calls[0]["guard"] is True  # never sent without the guard
    assert summary.accepted == 0 and summary.pages_failed == 0
    assert any(e.kind == "page_guard_blocked" for e in world.store.events())


def test_an_unguarded_retry_happens_only_when_asked_and_is_recorded(world: World) -> None:
    def respond(_user: str, guard: bool) -> ModelReply:
        return reply("I can't share that.", "content_filter") if guard else reply([good()])

    model = FakeModel(respond)
    summary = run_extraction(
        world.store, world.snapshot_id, model, allow_unguarded_retry=True, sleep=no_sleep
    )
    assert [c["guard"] for c in model.calls] == [True, False]
    assert summary.accepted == 1 and summary.pages_guard_blocked == 0
    assert any(e.kind == "page_guard_bypassed" for e in world.store.events())


def test_a_transient_failure_is_retried_with_backoff(world: World) -> None:
    attempts = {"n": 0}
    waits: list[float] = []

    def respond(_user: str, _guard: bool) -> ModelReply:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ModelError("http 503", transient=True)
        return reply([good()])

    summary = run_extraction(world.store, world.snapshot_id, FakeModel(respond), sleep=waits.append)
    assert summary.accepted == 1 and attempts["n"] == 3 and waits == [2.0, 4.0]


def test_persistent_and_permanent_failures_end_the_page_after_the_right_number_of_calls(
    world: World,
) -> None:
    always = FakeModel(lambda _u, _g: (_ for _ in ()).throw(ModelError("http 503", transient=True)))
    summary = run_extraction(world.store, world.snapshot_id, always, retries=2, sleep=no_sleep)
    assert len(always.calls) == 3 and summary.pages_failed == 1

    permanent = FakeModel(
        lambda _u, _g: (_ for _ in ()).throw(ModelError("http 400", transient=False))
    )
    summary = run_extraction(world.store, world.snapshot_id, permanent, retries=2, sleep=no_sleep)
    assert len(permanent.calls) == 1 and summary.pages_failed == 1


def test_identical_pages_are_extracted_once(tmp_path: Path) -> None:
    urls = (f"{BASE}/a.md", f"{BASE}/b.md")
    corpus = Corpus("docs", True, (), (f"{BASE}/",), urls, 50)
    crawl(tmp_path, {u: (lambda: md(OLD_TEXT)) for u in urls}, corpora=[corpus])
    store = ClaimStore(":memory:")
    snapshot = store.ingest_snapshot(tmp_path / "2026-11-05")
    model = ok_model()
    summary = run_extraction(store, snapshot.snapshot_id, model, sleep=no_sleep)
    assert len(model.calls) == 1 and summary.pages_total == 1


def test_limit_caps_the_pages(two_pages: World) -> None:
    model = FakeModel(lambda _u, _g: reply([]))
    run_extraction(two_pages.store, two_pages.snapshot_id, model, limit=1, sleep=no_sleep)
    assert len(model.calls) == 1


def test_only_docs_restricts_the_pages_and_marks_the_run_partial(two_pages: World) -> None:
    pages = two_pages.store.pages(two_pages.snapshot_id)
    chosen = pages[1].doc_id
    model = FakeModel(lambda _u, _g: reply([]))
    summary = run_extraction(
        two_pages.store, two_pages.snapshot_id, model, only_docs=frozenset({chosen}),
        sleep=no_sleep,
    )  # fmt: skip
    assert len(model.calls) == 1 and summary.pages_total == 1
    params = two_pages.store.run_meta(summary.run_id).params
    assert params["limited"] is True and params["only_docs"] == [chosen]


def test_every_page_is_logged_with_the_raw_model_output_and_no_secret(
    world: World, tmp_path: Path
) -> None:
    summary = run_extraction(
        world.store, world.snapshot_id, ok_model(), results_dir=tmp_path / "out", sleep=no_sleep
    )
    assert summary.results_path is not None and f"run{summary.run_id}" in summary.results_path.name
    lines = summary.results_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["url"] == OLD_URL and row["outcome"] == "ok" and row["request_id"] == "req-1"
    assert json.loads(row["raw"])["claims"][0]["quote"] == OLD_QUOTE
    assert len(row["accepted"]) == 1 and row["rejected"] == []
    assert "authorization" not in lines[0].lower()


def test_cost_is_estimated_from_tokens(world: World) -> None:
    summary = run_extraction(
        world.store,
        world.snapshot_id,
        FakeModel(lambda _u, _g: reply([], pt=1_000_000, ct=1_000_000)),
        sleep=no_sleep,
    )
    assert (summary.prompt_tokens, summary.completion_tokens) == (1_000_000, 1_000_000)
    assert summary.estimated_cost_usd == pytest.approx(0.78)


# --- the command line ---------------------------------------------------------------------


def chat_response(claims: list[Any], finish: str = "stop") -> httpx.Response:
    content = json.dumps({"claims": claims})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        },
    )


def extract_argv(world: World, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "extract",
        "--snapshot", str(world.snapshot_dir),
        "--db", str(tmp_path / "data" / "currant.db"),
        "--results-dir", str(tmp_path / "res"),
        "--dotenv", str(tmp_path / "no.env"),
        *extra,
    ]  # fmt: skip


def test_the_extract_command_runs_end_to_end(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer placeholder-key-for-tests"
        seen.append(json.loads(request.content))
        return chat_response([good()])

    patch_network(monkeypatch, httpx.MockTransport(handler))
    assert cli.main(extract_argv(world, tmp_path)) == 0

    body = seen[0]
    assert [t["function"]["name"] for t in body["tools"]] == ["serv_prompt_guard"]
    printed = capsys.readouterr().out
    assert "1 stored of 1 proposed" in printed and "raw outputs:" in printed
    with ClaimStore(tmp_path / "data" / "currant.db") as store:
        (run_id,) = [r["run_id"] for r in store.conn.execute("SELECT run_id FROM runs")]
        assert [c.quote for c in store.claims(run_id)] == [OLD_QUOTE]
    assert "placeholder-key-for-tests" not in "".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "res").glob("*.jsonl")
    )


def test_the_shadow_flag_adds_the_shadow_tool(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return chat_response([])

    patch_network(monkeypatch, httpx.MockTransport(handler))
    assert cli.main(extract_argv(world, tmp_path, "--shadow")) == 0
    assert [t["function"]["name"] for t in seen[0]["tools"]] == [
        "serv_prompt_guard",
        "serv_shadow_agent",
    ]


def test_a_missing_key_stops_the_command_before_anything_is_sent(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("SERV_API_KEY", "OPENSERV_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request was sent without a key")

    patch_network(monkeypatch, httpx.MockTransport(handler))
    assert cli.main(extract_argv(world, tmp_path)) == 2
    assert "SERV_API_KEY is not set" in capsys.readouterr().err


def test_a_guard_blocked_page_makes_the_command_exit_nonzero(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    patch_network(
        monkeypatch,
        httpx.MockTransport(lambda _r: chat_response([], finish="content_filter")),
    )
    assert cli.main(extract_argv(world, tmp_path)) == 1
    assert f"guard blocked: {OLD_URL}" in capsys.readouterr().out


def test_the_extract_command_reads_the_whole_snapshot(
    two_pages: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    requests: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        requests.append(1)
        return chat_response([])

    patch_network(monkeypatch, httpx.MockTransport(handler))
    assert cli.main(extract_argv(two_pages, tmp_path)) == 0
    assert len(requests) == 2


def test_the_old_split_option_is_gone(world: World, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(extract_argv(world, tmp_path, "--split", "all"))
    assert raised.value.code == 2


def test_a_missing_snapshot_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    argv = ["extract", "--snapshot", str(tmp_path / "nope"), "--db", str(tmp_path / "d.db"),
            "--dotenv", str(tmp_path / "no.env")]  # fmt: skip
    assert cli.main(argv) == 2
    assert "error:" in capsys.readouterr().err


# --- checks that were too literal on real pages (found by the first live run) --------------


def test_a_number_the_page_spells_out_is_accepted() -> None:
    assert numbers_in("a configurable iteration limit, three by default") >= {3.0}
    assert numbers_in("adds at least one call") >= {1.0}
    text = "The loop runs a configurable iteration limit, three by default.\n"
    verdict = validate_proposal(
        text,
        good(
            quote="The loop runs a configurable iteration limit, three by default.",
            value_text="three by default",
            value_number=3,
            value_type="count",
            unit="iterations",
        ),
    )
    assert isinstance(verdict, Accepted)


def test_a_made_up_number_is_still_refused_when_the_page_spells_other_numbers() -> None:
    text = "The loop runs a configurable iteration limit, three by default.\n"
    verdict = validate_proposal(
        text,
        good(
            quote="The loop runs a configurable iteration limit, three by default.",
            value_text="three by default",
            value_number=7,
        ),
    )
    assert isinstance(verdict, Rejected) and verdict.code == "number_not_in_quote"


def test_markdown_emphasis_in_the_page_does_not_defeat_the_value_check() -> None:
    quote = "* Tokens can be held on **Base** or **Ethereum mainnet** - balances are separate"
    text = quote + "\n"
    verdict = validate_proposal(
        text,
        good(
            quote=quote,
            subject="tokens",
            attribute="supported networks",
            value_text="Base or Ethereum mainnet",
            value_type="enum",
            value_number=None,
            unit=None,
        ),
    )
    assert isinstance(verdict, Accepted)
    assert verdict.fields["quote"] == quote  # the page's own text, markdown and all


def test_backslash_escapes_in_the_page_do_not_defeat_the_value_check() -> None:
    quote = "| Initial Market Cap | \\$15,000 |"
    verdict = validate_proposal(
        quote + "\n",
        good(
            quote=quote,
            subject="pool",
            attribute="initial market cap",
            value_text="$15,000",
            value_type="money",
            value_number=15000,
            unit="$",
        ),
    )
    assert isinstance(verdict, Accepted)


def test_a_single_word_quote_that_occurs_twice_is_ambiguous() -> None:
    result = locate("Base is one network. Base is also the default.", "Base")
    assert isinstance(result, str) and result.startswith("quote_ambiguous")


# --- pages that need more room, and runs that were interrupted ---------------------------


def test_an_answer_that_runs_out_of_room_is_retried_with_a_much_larger_budget(
    world: World,
) -> None:
    replies = iter(
        [reply('{"claims": [', finish="length", pt=100, ct=16000), reply([good()], pt=100, ct=900)]
    )
    model = FakeModel(lambda _u, _g: next(replies))
    summary = run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)

    assert [c["max_tokens"] for c in model.calls] == [None, LARGE_OUTPUT_TOKENS]
    assert summary.accepted == 1 and summary.pages_failed == 0
    assert (summary.prompt_tokens, summary.completion_tokens) == (200, 16900)  # both attempts paid


def test_an_empty_answer_is_retried_the_same_way(world: World) -> None:
    replies = iter([reply("", finish="stop"), reply([good()])])
    model = FakeModel(lambda _u, _g: next(replies))
    summary = run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    assert [c["max_tokens"] for c in model.calls] == [None, LARGE_OUTPUT_TOKENS]
    assert summary.accepted == 1


def test_a_page_that_is_still_too_big_fails_after_one_larger_attempt(world: World) -> None:
    model = FakeModel(lambda _u, _g: reply('{"claims": [', finish="length"))
    summary = run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    assert len(model.calls) == 2 and summary.pages_failed == 1  # one retry, not a loop


def test_an_ordinary_page_is_never_retried_with_a_larger_budget(world: World) -> None:
    model = ok_model()
    run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    assert [c["max_tokens"] for c in model.calls] == [None]


def test_the_larger_retry_keeps_the_guard_on(world: World) -> None:
    replies = iter([reply("", finish="length"), reply([good()])])
    model = FakeModel(lambda _u, _g: next(replies))
    run_extraction(world.store, world.snapshot_id, model, sleep=no_sleep)
    assert [c["guard"] for c in model.calls] == [True, True]


def crashing_on_second_page() -> FakeModel:
    seen = {"n": 0}

    def respond(_user: str, _guard: bool) -> ModelReply:
        seen["n"] += 1
        if seen["n"] == 2:
            raise RuntimeError("the machine ran out of memory")
        return reply([good()])

    return FakeModel(respond)


def test_an_interrupted_run_stays_running_so_it_can_be_resumed(two_pages: World) -> None:
    with pytest.raises(RuntimeError, match="out of memory"):
        run_extraction(
            two_pages.store, two_pages.snapshot_id, crashing_on_second_page(), sleep=no_sleep
        )
    (run,) = two_pages.store.conn.execute("SELECT run_id, status FROM runs").fetchall()
    assert run["status"] == "running"  # not marked failed: it is resumable
    assert any(e.kind == "run_interrupted" for e in two_pages.store.events())
    assert len(two_pages.store.finished_documents(run["run_id"])) == 1


def test_resuming_skips_finished_pages_and_completes_the_same_run(two_pages: World) -> None:
    with pytest.raises(RuntimeError):
        run_extraction(
            two_pages.store, two_pages.snapshot_id, crashing_on_second_page(), sleep=no_sleep
        )
    run_id = two_pages.store.conn.execute("SELECT run_id FROM runs").fetchone()["run_id"]
    first_claims = len(two_pages.store.claims(run_id))

    model = FakeModel(lambda _u, _g: reply([]))
    summary = run_extraction(
        two_pages.store, two_pages.snapshot_id, model, resume_run_id=run_id, sleep=no_sleep
    )
    assert summary.run_id == run_id and summary.pages_total == 1 and len(model.calls) == 1
    assert len(two_pages.store.claims(run_id)) == first_claims  # nothing duplicated
    status = two_pages.store.conn.execute("SELECT status FROM runs").fetchone()["status"]
    assert status == "complete"
    assert any(e.kind == "run_resumed" for e in two_pages.store.events())


def test_a_page_that_failed_is_retried_on_resume(world: World) -> None:
    summary = run_extraction(
        world.store, world.snapshot_id, fixed_reply("not json"), sleep=no_sleep
    )
    assert summary.pages_failed == 1
    run_id = summary.run_id
    assert world.store.run_info(run_id).status == "running"  # open, so resumable
    model = ok_model()
    again = run_extraction(
        world.store, world.snapshot_id, model, resume_run_id=run_id, sleep=no_sleep
    )
    assert len(model.calls) == 1 and again.accepted == 1 and again.pages_failed == 0
    assert world.store.run_info(run_id).status == "complete"


def test_only_a_running_extract_run_over_the_same_snapshot_can_be_resumed(world: World) -> None:
    done = run_extraction(world.store, world.snapshot_id, ok_model(), sleep=no_sleep)
    with pytest.raises(StoreError, match="only a running extract run"):
        run_extraction(world.store, world.snapshot_id, ok_model(), resume_run_id=done.run_id)
    relate = world.store.start_run("relate", "m", "p", world.snapshot_id)
    with pytest.raises(StoreError, match="only a running extract run"):
        run_extraction(world.store, world.snapshot_id, ok_model(), resume_run_id=relate)
    with pytest.raises(StoreError, match="unknown run"):
        run_extraction(world.store, world.snapshot_id, ok_model(), resume_run_id=999)


def test_resuming_through_the_command_line(
    two_pages: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SERV_API_KEY", "placeholder-key-for-tests")
    sent: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        sent.append(1)
        return chat_response([])

    patch_network(monkeypatch, httpx.MockTransport(handler))
    argv = extract_argv(two_pages, tmp_path)
    assert cli.main(argv) == 0 and len(sent) == 2
    with ClaimStore(tmp_path / "data" / "currant.db") as store:
        run_id = store.conn.execute("SELECT run_id FROM runs").fetchone()["run_id"]
    assert cli.main([*argv, "--resume", str(run_id)]) == 2  # already complete: refused
    assert "only a running extract run" in capsys.readouterr().err


def test_a_markdown_escape_in_the_page_does_not_defeat_the_quote_match() -> None:
    page = "* [x] Shipped core protocol with live datanets, and \\$REPPO staking, and more\n"
    quote = "Shipped core protocol with live datanets, and $REPPO staking, and more"
    span = locate(page, quote)
    assert not isinstance(span, str)
    assert page[span.start : span.end] == (
        "Shipped core protocol with live datanets, and \\$REPPO staking, and more"
    )  # the stored text is the page's own, backslash included


def test_an_escape_tolerant_match_still_refuses_a_changed_word() -> None:
    page = "Holders receive \\$REPPO staking rewards.\n"
    assert locate(page, "Holders receive $REPPO voting rewards.") == "quote_not_found"
    assert locate(page, "Holders receive $reppo staking rewards.") == "quote_not_found"


def test_the_plain_form_also_matches_when_the_page_has_no_escape() -> None:
    page = "Holders receive $REPPO staking rewards.\n"
    assert not isinstance(locate(page, "Holders receive $REPPO staking rewards."), str)


def test_a_bare_token_inside_an_escaped_one_is_already_a_verbatim_substring() -> None:
    page = "The token is \\$REPPO and nothing else.\n"
    span = locate(page, "$REPPO")
    assert not isinstance(span, str) and span.exact  # found exactly, no flexing needed
    assert page[span.start : span.end] == "$REPPO"
