from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from currant.ground import MODES, Grounded, Retrieved, ground
from currant.receipt import RECEIPT_VERSION, ReplayResult, build_receipt, receipt_id, replay
from currant.store import ClaimStore
from tests.test_ground import S10, S50, U1, U2, World, chain, contested, simple

Receipt = dict[str, Any]


def make(world: World, mode: str = "redact_pull", urls: list[str] | None = None) -> Receipt:
    grounded: Grounded = world.ground(mode, urls or [U1])
    return build_receipt(
        world.store, grounded, question="how many free evaluations?",
        extract_run_id=world.extract, relate_run_id=world.relate,
    )  # fmt: skip


def reseal(receipt: Receipt) -> Receipt:
    """What a forger does: change something, then recompute the id so it looks self-consistent."""
    body = {k: v for k, v in receipt.items() if k != "receipt_id"}
    return {**body, "receipt_id": receipt_id(body)}


def check(world: World, receipt: Receipt) -> ReplayResult:
    return replay(world.store, receipt)


@pytest.mark.parametrize("mode", MODES)
def test_an_honest_receipt_replays_in_every_mode(mode: str) -> None:
    world = simple()
    result = check(world, make(world, mode))
    assert result.ok and result.problems == []


def test_a_receipt_survives_a_json_round_trip() -> None:
    world = simple()
    receipt = json.loads(json.dumps(make(world), ensure_ascii=False))
    assert check(world, receipt).ok


def test_replay_works_on_a_chain_and_on_a_contested_receipt() -> None:
    for world, urls in ((chain(), [U1]), (contested(), [U1, U2])):
        assert check(world, make(world, "redact_pull", urls)).ok


def test_the_receipt_records_what_was_cut_and_why() -> None:
    world = simple()
    receipt = make(world, "redact")
    assert receipt["receipt_version"] == RECEIPT_VERSION and receipt["mode"] == "redact"
    (action,) = receipt["actions"]
    assert action["kind"] == "redact" and action["target"]["quote"] == S10
    assert action["source"]["quote"] == S50
    assert {e["role"] for e in action["evidence"]} >= {"ordering"}
    assert receipt["runs"]["extract"]["model"] == "fake"
    assert len(receipt["corpus"]["corpus_hash"]) == 64
    assert receipt["context_sha256"] == world.ground("redact", [U1]).context_sha256


def test_the_same_inputs_give_the_same_receipt_byte_for_byte() -> None:
    world = simple()
    assert make(world) == make(world)
    assert json.dumps(make(world), sort_keys=True) == json.dumps(make(world), sort_keys=True)


def test_a_receipt_carries_no_clock_time() -> None:
    text = json.dumps(make(simple()))
    assert "created" not in text and "timestamp" not in text
    assert not any(ch.isdigit() and text[i : i + 4] == "2026" for i, ch in enumerate(text))


# --- tampering: every change must be caught, with or without a recomputed id ------------------

MUTATIONS = {
    "question": lambda r: r.update(question="something else"),
    "mode": lambda r: r.update(mode="baseline"),
    "context hash": lambda r: r.update(context_sha256="0" * 64),
    "context size": lambda r: r.update(context_chars=r["context_chars"] + 1),
    "drop an action": lambda r: r["actions"].pop(),
    "add an action": lambda r: r["actions"].append(copy.deepcopy(r["actions"][0])),
    "edit a cut quote": lambda r: r["actions"][0]["target"].update(quote="Something else."),
    "move a cut span": lambda r: r["actions"][0]["target"].update(start=0, end=5),
    "swap the winner": lambda r: r["actions"][0]["source"].update(quote="New accounts get 999."),
    "forge evidence": lambda r: r["actions"][0]["evidence"][0].update(quote="Made up."),
    "change the url": lambda r: r["documents"][0].update(url="https://evil.example/x.md"),
    "change the doc": lambda r: r["documents"][0].update(doc_id="1" * 64),
    "drop a document": lambda r: r["documents"].clear(),
    "other relation": lambda r: r["actions"][0].update(relation_id="f" * 64),
    "model name": lambda r: r["runs"]["relate"].update(model="a-different-model"),
    "prompt version": lambda r: r["runs"]["extract"].update(prompt_version="extract-v9"),
    "corpus hash": lambda r: r["corpus"].update(corpus_hash="2" * 64),
    "unknown run": lambda r: r["runs"]["relate"].update(run_id=999),
}


# Everything the store can re-derive is protected against a forger who recomputes the id. The
# question is not: nothing in the store determines it, so only receipt_id (which anyone can
# recompute) binds it. That is a documented limit (docs/THREAT_MODEL.md): to bind the question
# against a forger the receipt id must be signed or published somewhere the forger cannot edit.
NOT_DERIVABLE_FROM_THE_STORE = {"question"}


def test_the_question_is_bound_only_by_the_receipt_id_and_that_is_stated() -> None:
    world = simple()
    forged = copy.deepcopy(make(world))
    MUTATIONS["question"](forged)
    assert check(world, reseal(forged)).ok is True  # a resealed question edit is NOT detectable


@pytest.mark.parametrize("name", sorted(set(MUTATIONS) - NOT_DERIVABLE_FROM_THE_STORE))
def test_a_changed_receipt_is_caught_even_when_the_forger_recomputes_the_id(name: str) -> None:
    world = simple()
    forged = copy.deepcopy(make(world))
    MUTATIONS[name](forged)
    assert check(world, reseal(forged)).ok is False, name  # id is consistent; the store disagrees


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_changed_receipt_is_caught_by_its_id_when_the_forger_forgets_to_reseal(name: str) -> None:
    world = simple()
    forged = copy.deepcopy(make(world))
    MUTATIONS[name](forged)
    result = check(world, forged)
    assert result.ok is False and any("receipt_id" in p for p in result.problems), name


def test_an_action_the_store_never_verified_cannot_be_smuggled_in() -> None:
    # A receipt for a pair that was only PROPOSED, built by hand with a resealed id.
    world = World((U1, simple().texts[U1], S10, 10, "current"),
                  (U2, simple().texts[U2], S50, 50, "current"))  # fmt: skip
    honest = make(simple())
    forged = copy.deepcopy(honest)
    forged["runs"]["extract"]["run_id"] = world.extract
    forged["runs"]["relate"]["run_id"] = world.relate
    forged["documents"] = [{"doc_id": world.claims[U1].doc_id, "url": U1}]
    assert check(world, reseal(forged)).ok is False


def test_replay_on_a_store_without_the_documents_fails_closed() -> None:
    other = simple()
    receipt = make(other)
    empty = ClaimStore(":memory:")
    assert replay(empty, receipt).ok is False


# --- malformed input never crashes replay and never passes ----------------------------------


@pytest.mark.parametrize(
    "junk",
    [None, 5, "text", [], {}, {"receipt_version": 1}, {"receipt_version": 99}],
)
def test_malformed_receipts_fail_with_a_reason_not_an_exception(junk: Any) -> None:
    result = replay(simple().store, junk)
    assert result.ok is False and result.problems


@pytest.mark.parametrize("key", ["documents", "actions", "runs", "corpus", "mode", "receipt_id"])
def test_a_missing_field_fails_closed(key: str) -> None:
    world = simple()
    receipt = copy.deepcopy(make(world))
    del receipt[key]
    assert check(world, receipt).ok is False


@pytest.mark.parametrize(
    ("key", "value"),
    [("documents", "x"), ("actions", {}), ("runs", []), ("mode", 3), ("documents", [5])],
)
def test_a_field_of_the_wrong_type_fails_closed(key: str, value: Any) -> None:
    world = simple()
    receipt = copy.deepcopy(make(world))
    receipt[key] = value
    assert check(world, reseal(receipt)).ok is False


def test_a_stored_document_that_does_not_hash_to_its_id_is_reported() -> None:
    world = simple()
    world.finish()
    fake_id = "a" * 64
    world.store.conn.execute("INSERT INTO documents (doc_id, text, n_chars) VALUES (?, ?, 5)",
                             (fake_id, "hello"))  # fmt: skip
    world.store.conn.execute(
        "INSERT INTO snapshot_pages (snapshot_id, url, corpus, doc_id, fetched_at)"
        " VALUES (?, 'https://docs.example.com/x.md', 't', ?, 'now')",
        (world.snapshot_id, fake_id),
    )
    world.store.conn.commit()
    grounded = ground(
        world.store, [Retrieved(fake_id, "https://docs.example.com/x.md")], mode="baseline",
        extract_run_id=world.extract, relate_run_id=world.relate,
    )  # fmt: skip
    receipt = build_receipt(world.store, grounded, question="q", extract_run_id=world.extract,
                            relate_run_id=world.relate)  # fmt: skip
    result = replay(world.store, receipt)
    assert result.ok is False and any("does not hash" in p for p in result.problems)


def test_a_run_of_the_wrong_stage_is_named_in_the_problems() -> None:
    world = simple()
    receipt = copy.deepcopy(make(world))
    wrong = world.store.start_run("relate", "fake", "extract-v1", world.snapshot_id)
    receipt["runs"]["extract"] = {"run_id": wrong, "model": "fake", "prompt_version": "extract-v1"}
    result = check(world, reseal(receipt))
    assert result.ok is False and any("not extract" in p for p in result.problems)


def test_an_unsupported_version_is_refused_even_if_everything_else_is_consistent() -> None:
    world = simple()
    receipt = copy.deepcopy(make(world))
    receipt["receipt_version"] = RECEIPT_VERSION + 1
    result = check(world, reseal(receipt))
    assert result.ok is False and any("unsupported" in p for p in result.problems)
