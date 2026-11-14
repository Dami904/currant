from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant import cli
from currant.crawl.config import Corpus
from currant.evalset import EvalError, EvalStore, split_for_cluster
from currant.harness.synth import (
    CLEAN,
    SUPERSEDE_TEMPLATES,
    Target,
    build_item,
    eligible_controls,
    eligible_targets,
    format_like,
    generate,
    new_value,
)
from currant.store import ClaimStore
from tests.helpers import md
from tests.test_crawl import crawl

BASE = "https://docs.example.com"
GOOD_PAGES = 12


NAMES = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
]


def quote(i: int) -> str:
    # Words, not digits, for the name: the rewriter needs exactly one number per sentence.
    return f"The request limit for the {NAMES[i]} widget is {10 + i} requests per minute."


def page_text(i: int) -> str:
    return f"# Widget {NAMES[i]}\n\n{quote(i)}\n"


def route(text: str) -> Callable[[], httpx.Response]:
    return lambda: md(text)


class Built:
    def __init__(self, tmp_path: Path) -> None:
        urls = {f"{BASE}/w{i}.md": page_text(i) for i in range(GOOD_PAGES)}
        noise = {
            f"{BASE}/historical.md": "Widgets used to allow 50 requests per minute earlier.\n",
            f"{BASE}/text.md": "The default region for every widget is eu-west-1 for now.\n",
            f"{BASE}/two.md": "Between 5 and 10 requests per minute are allowed for each widget.\n",
            f"{BASE}/short.md": "Limit is 10 now.\n",
            # Two rewritable claims on one page, so cluster-per-page can be tested.
            f"{BASE}/multi.md": (
                "Each widget allows 7 retries per call.\nEach widget keeps 12 events per queue.\n"
            ),
            # A percentage, which must stay within 0 to 100 when rewritten.
            f"{BASE}/pct.md": (
                "The discount for annual plans is 40% of the list price for every widget.\n"
            ),
            # A claim whose quote spans two lines: fine to extract, not to use as a control.
            f"{BASE}/multiline.md": (
                "Widgets are limited to a fixed rate\nacross every region we operate.\n"
            ),
            f"{BASE}/mismatch.md": "The request limit for gadgets is 10 requests per minute.\n",
        }
        pages = {**urls, **noise}
        corpus = Corpus("docs", True, (), (f"{BASE}/",), tuple(pages), 500)
        crawl(tmp_path, {u: route(t) for u, t in pages.items()}, corpora=[corpus])
        self.store = ClaimStore(":memory:")
        snapshot = self.store.ingest_snapshot(tmp_path / "2026-11-05")
        self.run = self.store.start_run("extract", "fake", "extract-v1", snapshot.snapshot_id)
        self.pages = pages
        self.doc_by_url = {p.url: p.doc_id for p in self.store.pages(snapshot.snapshot_id)}
        for i in range(GOOD_PAGES):
            self.claim(f"{BASE}/w{i}.md", quote(i), "current", "count", 10 + i)
        self.claim(
            f"{BASE}/historical.md",
            "Widgets used to allow 50 requests per minute",
            "historical",
            "count",
            50,
        )
        self.claim(
            f"{BASE}/text.md",
            "The default region for every widget is eu-west-1",
            "current",
            "text",
            None,
        )
        self.claim(
            f"{BASE}/two.md",
            "Between 5 and 10 requests per minute are allowed for each widget.",
            "current",
            "count",
            10,
        )
        self.claim(f"{BASE}/short.md", "Limit is 10 now.", "current", "count", 10)
        self.claim(
            f"{BASE}/multi.md", "Each widget allows 7 retries per call.", "current", "count", 7
        )
        self.claim(
            f"{BASE}/multi.md", "Each widget keeps 12 events per queue.", "current", "count", 12
        )
        self.claim(
            f"{BASE}/pct.md",
            "The discount for annual plans is 40% of the list price for every widget.",
            "current",
            "number",
            40,
        )
        self.claim(
            f"{BASE}/multiline.md",
            "Widgets are limited to a fixed rate\nacross every region we operate.",
            "current",
            "text",
            None,
        )
        self.claim(
            f"{BASE}/mismatch.md",
            "The request limit for gadgets is 10 requests per minute.",
            "current",
            "count",
            11,
        )

    def claim(self, url: str, text: str, stance: str, vtype: str, number: float | None) -> None:
        page = self.pages[url]
        start = page.index(text)
        self.store.add_claim(
            self.run, doc_id=self.doc_by_url[url], start=start, end=start + len(text), quote=text,
            subject="widget", attribute="request limit", value_text=text[:40], value_type=vtype,
            value_number=float(number) if number is not None else None, stance=stance,
        )  # fmt: skip


@pytest.fixture
def built(tmp_path: Path) -> Built:
    return Built(tmp_path)


def make(built: Built, seed: int = 1, supersede: int = 6, clean: int = 4) -> tuple[EvalStore, Any]:
    evals = EvalStore(":memory:")
    return evals, generate(
        built.store, built.run, evals, seed=seed, n_supersede=supersede, n_clean=clean
    )


# --- which claims can be rewritten ----------------------------------------------------------


def test_only_clean_current_numeric_single_number_sentences_are_eligible(built: Built) -> None:
    targets = eligible_targets(built.store, built.run)
    expected = {f"{BASE}/w{i}.md" for i in range(GOOD_PAGES)} | {
        f"{BASE}/multi.md",
        f"{BASE}/pct.md",
    }
    assert {t.url for t in targets} == expected
    for target in targets:
        assert (
            target.claim.quote[target.token_start : target.token_start + len(target.token)]
            == target.token
        )


def test_eligibility_order_is_reproducible(built: Built) -> None:
    first = [t.claim.claim_id for t in eligible_targets(built.store, built.run)]
    assert first == sorted(first) and first == [
        t.claim.claim_id for t in eligible_targets(built.store, built.run)
    ]


# --- inventing a new value ------------------------------------------------------------------


def test_a_new_value_is_different_positive_and_integral_when_the_old_one_was() -> None:
    rng = random.Random(0)
    for old in (1.0, 2.0, 7.0, 10.0, 25.0, 1000.0, 0.13, 3.5):
        for _ in range(30):
            value = new_value(old, percent=False, rng=rng)
            assert value > 0 and value != old
            if float(old).is_integer():
                assert float(value).is_integer()


def test_a_new_number_is_written_like_the_old_one() -> None:
    assert format_like("10", 50.0) == "50"
    assert format_like("1,000", 5000.0) == "5,000"
    assert format_like("0.13", 0.26) == "0.26"
    assert format_like("1,250.50", 2501.0) == "2,501.00"


# --- building items --------------------------------------------------------------------------


def distractor(built: Built) -> tuple[str, str]:
    return f"{BASE}/w5.md", built.pages[f"{BASE}/w5.md"]


def one_target(built: Built) -> Target:
    return next(t for t in eligible_targets(built.store, built.run) if t.url.endswith("w3.md"))


def test_the_spec_holds_only_pages_and_a_question(built: Built) -> None:
    for scenario in (*SUPERSEDE_TEMPLATES, CLEAN):
        spec, _label = build_item(one_target(built), scenario, random.Random(2), distractor(built))
        assert set(spec) == {"question", "pages"}
        assert all(set(p) == {"id", "url", "text"} for p in spec["pages"])
        assert {p["id"] for p in spec["pages"]} == {"a", "b"}
        blob = json.dumps(spec)
        for leaked in (*SUPERSEDE_TEMPLATES, "expected_state", "CANON", "CONTESTED", "scenario"):
            assert leaked not in blob


def stale_and_update(spec: dict[str, Any], label: dict[str, Any]) -> tuple[str, str]:
    by_id = {p["id"]: p["text"] for p in spec["pages"]}
    update = by_id[label["update_page_id"]] if label["update_page_id"] else ""
    return by_id[label["stale_page_id"]], update


@pytest.mark.parametrize("seed", range(3))
def test_the_label_points_at_the_stale_sentence_exactly(built: Built, seed: int) -> None:
    for scenario in (*SUPERSEDE_TEMPLATES, CLEAN):
        spec, label = build_item(
            one_target(built), scenario, random.Random(seed), distractor(built)
        )
        stale, _ = stale_and_update(spec, label)
        start, end = label["stale_span"]
        assert stale[start:end] == label["stale_quote"] == quote(3)


def test_explicit_supersession_says_it_replaces_the_old_value(built: Built) -> None:
    spec, label = build_item(one_target(built), "supersedes_explicit", random.Random(1), None)
    _, update = stale_and_update(spec, label)
    assert label["expected_state"] == "CANON" and label["ordering_basis"] == "explicit_text"
    assert "replaces the previous value of 13" in update
    assert label["current_value_number"] != 13 and label["update_quote"] in update
    assert str(int(label["current_value_number"])) in label["update_quote"]


def test_dated_supersession_has_a_later_date_on_the_update(built: Built) -> None:
    spec, label = build_item(one_target(built), "supersedes_dated", random.Random(1), None)
    stale, update = stale_and_update(spec, label)
    old = stale.split("Last updated: ")[1][:10]
    new = update.split("**")[1]
    assert label["expected_state"] == "CANON" and label["ordering_basis"] == "dated"
    assert new > old  # ISO dates compare as text
    assert label["current_value_number"] != 13


def test_an_implicit_restatement_has_no_date_and_the_right_answer_is_contested(
    built: Built,
) -> None:
    spec, label = build_item(one_target(built), "contested_implicit", random.Random(1), None)
    stale, update = stale_and_update(spec, label)
    assert label["expected_state"] == "CONTESTED" and label["current_value_number"] is None
    assert "replaces" not in update and "Last updated" not in stale and "Changelog" not in update


def test_a_clean_control_keeps_the_original_value_and_cuts_nothing(built: Built) -> None:
    spec, label = build_item(one_target(built), CLEAN, random.Random(1), distractor(built))
    _, other = stale_and_update(spec, label)
    assert label["expected_state"] == "CANON" and label["current_value_number"] == 13
    assert label["update_page_id"] is None and other == ""
    assert built.pages[f"{BASE}/w5.md"] in {p["text"] for p in spec["pages"]}


def test_the_stale_page_is_not_always_first(built: Built) -> None:
    orders = set()
    for seed in range(20):
        _spec, label = build_item(
            one_target(built), "supersedes_explicit", random.Random(seed), None
        )
        orders.add(label["stale_page_id"])
    assert orders == {"a", "b"}


# --- generating a set ------------------------------------------------------------------------


def test_generate_makes_the_requested_mix_and_seals_every_label(built: Built) -> None:
    evals, summary = make(built, supersede=6, clean=4)
    assert summary.items == 10 and len(evals.items()) == 10
    assert dict(summary.by_scenario) == {
        "supersedes_explicit": 2, "supersedes_dated": 2, "contested_implicit": 2, "clean": 4,
    }  # fmt: skip
    assert evals.check_integrity() == [] and summary.commit_root == evals.commit_root()


def test_items_are_split_by_their_source_page_with_the_committed_rule(built: Built) -> None:
    evals, _ = make(built, supersede=6, clean=4)
    for item in evals.items():
        assert item.kind == "synthetic" and item.split == split_for_cluster(item.cluster_id)
        assert item.cluster_id.startswith("syn-") and "supersedes" not in item.cluster_id


def item_ids(evals: EvalStore) -> list[str]:
    return sorted(i.item_id for i in evals.items())


def test_the_same_seed_gives_the_same_items_and_another_seed_does_not(built: Built) -> None:
    first, _ = make(built, seed=3)
    again, _ = make(built, seed=3)
    other, _ = make(built, seed=4)
    assert item_ids(first) == item_ids(again) and item_ids(first) != item_ids(other)


def test_asking_for_more_items_than_eligible_claims_is_an_error(built: Built) -> None:
    with pytest.raises(EvalError, match="only 15 rewritable claims"):
        generate(built.store, built.run, EvalStore(":memory:"), seed=1, n_supersede=16, n_clean=0)
    with pytest.raises(EvalError, match="eligible controls"):
        generate(built.store, built.run, EvalStore(":memory:"), seed=1, n_supersede=10, n_clean=10)


def test_controls_may_be_non_numeric_and_never_reuse_a_supersession_claim(built: Built) -> None:
    evals = EvalStore(":memory:")
    generate(built.store, built.run, evals, seed=2, n_supersede=12, n_clean=3)
    evals.freeze("inspect")
    stale_quotes: dict[bool, set[str]] = {}
    for item in evals.items():
        label = evals.label(item.item_id)
        stale_quotes.setdefault(label["scenario"] == CLEAN, set()).add(label["stale_quote"])
    assert not stale_quotes[True] & stale_quotes[False]  # no claim is both injected and a control
    assert any("eu-west-1" in q for q in stale_quotes[True]) or len(stale_quotes[True]) == 3


def test_generating_changes_nothing_in_the_claim_store(built: Built) -> None:
    before = built.store.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    make(built)
    assert built.store.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == before
    assert built.store.check_integrity() == []


def test_a_clean_control_always_uses_a_different_page_as_its_second(built: Built) -> None:
    evals, _ = make(built, supersede=0, clean=6)
    evals.freeze("inspect")
    for item in evals.items():
        label = evals.label(item.item_id)
        assert label["scenario"] == CLEAN
        texts = [p["text"] for p in item.spec["pages"]]
        assert texts[0] != texts[1]


# --- the command line ----------------------------------------------------------------------


def test_make_synthetic_prints_counts_and_a_root_but_never_a_label(
    built: Built, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "currant.db"
    # Persist the fixture store to a file so the command can open it.
    target = sqlite3.connect(db)
    built.store.conn.backup(target)
    target.close()

    evalset = tmp_path / "evalset.db"
    argv = ["make-synthetic", "--db", str(db), "--evalset", str(evalset), "--run", str(built.run)]
    assert cli.main([*argv, "--supersede", "6", "--clean", "4"]) == 0
    out = capsys.readouterr().out
    assert "items added:  10" in out and "commit root:" in out and "Publish the commit root" in out
    for secret in ("expected_state", "current_value", "stale_quote", "CONTESTED", "CANON"):
        assert secret not in out
    with EvalStore(evalset) as evals:
        assert len(evals.items()) == 10 and evals.check_integrity() == []


def test_make_synthetic_with_too_few_claims_is_a_clean_error(
    built: Built, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "currant.db"
    target = sqlite3.connect(db)
    built.store.conn.backup(target)
    target.close()
    argv = ["make-synthetic", "--db", str(db), "--evalset", str(tmp_path / "e.db")]
    assert cli.main([*argv, "--run", str(built.run), "--supersede", "50", "--clean", "50"]) == 2
    assert "rewritable claims" in capsys.readouterr().err


def test_a_clean_controls_second_page_keeps_its_own_real_url(built: Built) -> None:
    spec, _ = build_item(one_target(built), CLEAN, random.Random(1), distractor(built))
    assert f"{BASE}/w5.md" in {p["url"] for p in spec["pages"]}
    assert not any("synthetic.invalid" in p["url"] for p in spec["pages"])


# --- gaps found by deleting each generator guard in turn -----------------------------------


def target_for(built: Built, url_suffix: str) -> Target:
    return next(t for t in eligible_targets(built.store, built.run) if t.url.endswith(url_suffix))


def test_items_built_from_one_page_share_a_cluster_and_therefore_a_split(built: Built) -> None:
    evals = EvalStore(":memory:")
    generate(built.store, built.run, evals, seed=1, n_supersede=15, n_clean=0)
    multi = [
        i for i in evals.items() if any(p["url"].endswith("/multi.md") for p in i.spec["pages"])
    ]
    assert len(multi) == 2  # two rewritable claims on that page
    assert multi[0].cluster_id == multi[1].cluster_id and multi[0].split == multi[1].split
    assert len({i.cluster_id for i in evals.items()}) == 14  # 15 items from 14 source pages


@pytest.mark.parametrize("seed", range(10))
def test_a_rewritten_percentage_stays_within_zero_to_one_hundred(built: Built, seed: int) -> None:
    target = target_for(built, "pct.md")
    for scenario in ("supersedes_explicit", "supersedes_dated"):
        _spec, label = build_item(target, scenario, random.Random(seed), None)
        assert 0 < label["current_value_number"] <= 100
        assert label["current_value_number"] != 40
        assert "%" in label["update_quote"]  # the percent sign survives the rewrite


def test_controls_never_use_a_quote_that_spans_lines(built: Built) -> None:
    quotes = [t.claim.quote for t in eligible_controls(built.store, built.run)]
    assert quotes and all("\n" not in q for q in quotes)
    assert not any("fixed rate" in q for q in quotes)
