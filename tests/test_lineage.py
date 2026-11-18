from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from currant.lineage import LineageError, Source, apply_reviews, export
from tests.test_ground import R10, R50, S10, S50, S70, T10, T50, T70, U1, U2, U3, World


def exported(world: World) -> dict[str, Any]:
    world.finish()
    return export(world.store, Source("test", world.relate))


def test_a_chain_is_exported_oldest_first_with_every_quote_verbatim() -> None:
    world = World(
        (U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"), (U3, T70, S70, 70, "current")
    )
    world.supersede(U2, U1, R10)
    world.supersede(U3, U2, R50)
    data = exported(world)
    ids = {world.claims[u].claim_id: u for u in (U1, U2, U3)}
    (chain,) = data["chains"]
    assert [ids[c] for c in chain["claims"]] == [U1, U2, U3] and not chain["branched"]
    for rel in data["supersedes"]:
        for side in (rel["older"], rel["newer"]):
            assert world.texts[side["url"]][side["start"] : side["end"]] == side["quote"]
        assert any(e["role"] == "ordering" for e in rel["evidence"])


def test_a_claim_replaced_twice_is_shown_as_a_branch_with_no_single_winner() -> None:
    # Two pages each say they replace the value 10: a real branch, two latest values.
    also_replaces_10 = f"# Another notice\n\n{S70}\n\n{R10}\n"
    world = World(
        (U1, T10, S10, 10, "current"),
        (U2, T50, S50, 50, "current"),
        (U3, also_replaces_10, S70, 70, "current"),
    )
    world.supersede(U2, U1, R10)
    world.supersede(U3, U1, R10)
    chains = exported(world)["chains"]
    assert len(chains) == 2 and all(c["branched"] for c in chains)


def test_contradictions_are_exported_with_both_sides() -> None:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    world.contradict(U1, U2)
    data = exported(world)
    assert data["supersedes"] == [] and len(data["contested"]) == 1
    pair = data["contested"][0]
    assert {pair["a"]["quote"], pair["b"]["quote"]} == {S10, S50}


def test_a_relation_that_was_only_proposed_is_never_exported() -> None:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    a, b = world.claims[U2].claim_id, world.claims[U1].claim_id
    world.store.propose_relation(world.relate, "supersedes", a, b, "explicit_text")
    assert exported(world)["supersedes"] == []


def test_a_quote_that_is_no_longer_verbatim_stops_the_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The store is append-only, so drift is simulated: the stored text no longer holds the quote.
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    world.supersede(U2, U1, R10)
    world.finish()
    monkeypatch.setattr(world.store, "document_text", lambda _doc: "the page changed")
    with pytest.raises(LineageError, match="not verbatim"):
        export(world.store, Source("test", world.relate))


def test_only_a_complete_relate_run_is_exported() -> None:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    with pytest.raises(LineageError, match="not a complete relate run"):
        export(world.store, Source("test", world.relate))  # still running
    with pytest.raises(LineageError, match="not a complete relate run"):
        export(world.store, Source("test", world.extract))


ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "site" / "src" / "lineage" / "lineage.json"


def load_builder() -> ModuleType:
    path = ROOT / "scripts" / "build_lineage.py"
    spec = importlib.util.spec_from_file_location("build_lineage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def two_contested() -> dict[str, Any]:
    world = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    world.supersede(U2, U1, R10)
    return exported(world)


def test_a_relation_with_no_review_stops_the_build() -> None:
    corpus = two_contested()
    with pytest.raises(LineageError, match="no review"):
        apply_reviews(corpus, {}, frozenset())


def test_a_held_relation_is_left_out_and_its_chain_with_it() -> None:
    corpus = two_contested()
    rid = corpus["supersedes"][0]["relation_id"]
    kept = apply_reviews(corpus, {}, frozenset({rid}))
    assert kept["supersedes"] == [] and kept["chains"] == []


def test_a_review_needs_a_known_verdict_and_a_note() -> None:
    corpus = two_contested()
    rid = corpus["supersedes"][0]["relation_id"]
    for bad in ({"verdict": "probably", "note": "x"}, {"verdict": "genuine", "note": ""}):
        with pytest.raises(LineageError, match="known verdict"):
            apply_reviews(corpus, {rid: bad}, frozenset())
    kept = apply_reviews(corpus, {rid: {"verdict": "genuine", "note": "read"}}, frozenset())
    assert kept["supersedes"][0]["review"]["verdict"] == "genuine"


def test_every_drift_finding_the_page_cites_still_exists() -> None:
    builder = load_builder()
    reviews = builder.reviews()  # raises if docs/drift dropped a finding
    assert set(builder.FROM_DRIFT) <= set(reviews)
    assert not set(builder.HELD) & set(reviews)


def test_the_committed_page_shows_only_reviewed_relations_and_nothing_held() -> None:
    builder = load_builder()
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    shown = [r for c in data["corpora"] for r in [*c["supersedes"], *c["contested"]]]
    assert shown and all(r["review"]["verdict"] and r["review"]["note"] for r in shown)
    ids = {r["relation_id"] for r in shown}
    assert ids <= set(builder.FROM_DRIFT) | set(builder.STRIPE)
    assert not ids & builder.HELD


def snapshot_text(date: str, url: str) -> str | None:
    manifest = ROOT / "snapshots" / date / "manifest.json"
    if not manifest.exists():
        return None
    for page in json.loads(manifest.read_text(encoding="utf-8"))["pages"]:
        if page["url"] == url and page.get("path"):
            return (manifest.parent / str(page["path"])).read_bytes().decode("utf-8")
    return None


def test_committed_openserv_and_reppo_quotes_match_the_committed_snapshots() -> None:
    """The page's claim that every quote is verbatim, checked offline in CI."""
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    checked = 0
    for corpus in data["corpora"]:
        if not corpus["corpus"].startswith("OpenServ"):
            continue  # Stripe pages are not committed
        for rel in corpus["contested"] + corpus["supersedes"]:
            claims = [rel.get(k) for k in ("a", "b", "newer", "older") if rel.get(k)]
            # Evidence carries no crawl date: it must be verbatim in a crawl of one of the claims
            # (a crawl-diff relation pairs an earlier crawl with a later one).
            dates = sorted({c["crawled"] for c in claims})
            for side in claims + rel["evidence"]:
                found = [
                    text[side["start"] : side["end"]] == side["quote"]
                    for d in ([side["crawled"]] if "crawled" in side else dates)
                    if (text := snapshot_text(d, side["url"])) is not None
                ]
                assert any(found), f"{side['url']}: {side['quote']!r} not in snapshots {dates}"
                checked += 1
    assert checked >= 12
