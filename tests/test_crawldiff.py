from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from currant.crawldiff import PROMPT_VERSION, as_of, changed_pages, run_crawl_diff
from currant.store import ClaimStore, StoreError

URL = "https://docs.example.com/limits.md"
OTHER = "https://docs.example.com/faq.md"

OLD_LIMITS = "# Limits\n\nThe API allows 60 requests per minute.\nUploads can be up to 10 MB.\n"
NEW_LIMITS = "# Limits\n\nThe API allows 120 requests per minute.\nUploads can be up to 10 MB.\n"
FAQ = "# FAQ\n\nAccounts start with 5 projects.\n"


def _doc(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _claim(store: ClaimStore, run: int, text: str, quote: str, value: str, number: float,
           unit: str, attribute: str = "rate limit") -> str:  # fmt: skip
    start = text.index(quote)
    return store.add_claim(
        run, doc_id=_doc(text), start=start, end=start + len(quote), quote=quote,
        subject="API", attribute=attribute, value_text=value, value_type="count",
        stance="current", value_number=number, unit=unit,
    )  # fmt: skip


def world(tmp_path: Path, new_limits: str = NEW_LIMITS) -> tuple[ClaimStore, int, int]:
    store = ClaimStore(tmp_path / "c.db")
    old = store.ingest_pages("2026-11-05", [(URL, OLD_LIMITS), (OTHER, FAQ)]).snapshot_id
    new = store.ingest_pages("2026-11-11", [(URL, new_limits), (OTHER, FAQ)]).snapshot_id
    old_run = store.start_run("extract", "fake", "extract-v1", old)
    _claim(store, old_run, OLD_LIMITS, "The API allows 60 requests per minute.",
           "60 requests per minute", 60, "requests")  # fmt: skip
    _claim(store, old_run, OLD_LIMITS, "Uploads can be up to 10 MB.", "10 MB", 10, "MB",
           attribute="upload size")  # fmt: skip
    store.finish_run(old_run)
    new_run = store.start_run("extract", "fake", "extract-v1", new)
    _claim(store, new_run, new_limits, new_limits.splitlines()[2],
           "120 requests per minute" if "120" in new_limits else "60 requests per minute",
           120 if "120" in new_limits else 60, "requests")  # fmt: skip
    _claim(store, new_run, new_limits, "Uploads can be up to 10 MB.", "10 MB", 10, "MB",
           attribute="upload size")  # fmt: skip
    store.finish_run(new_run)
    return store, old_run, new_run


def test_only_urls_whose_content_changed_are_compared(tmp_path: Path) -> None:
    store, old_run, new_run = world(tmp_path)
    old_snap, new_snap = store.run_meta(old_run).snapshot_id, store.run_meta(new_run).snapshot_id
    (page,) = changed_pages(store, old_snap, new_snap)
    assert page.url == URL and page.old_doc == _doc(OLD_LIMITS) and page.new_doc == _doc(NEW_LIMITS)


def test_an_edited_value_becomes_a_verified_crawl_diff_supersession(tmp_path: Path) -> None:
    store, old_run, new_run = world(tmp_path)
    summary = run_crawl_diff(store, old_run, new_run)
    assert summary.changed_pages == 1 and summary.verified == 1 and summary.refused == 0
    (pair,) = summary.pairs
    assert pair.older.value_number == 60 and pair.newer.value_number == 120
    meta = store.run_meta(summary.run_id)
    assert (meta.stage, meta.model, meta.prompt_version) == ("relate", "none", PROMPT_VERSION)
    (relation,) = store.verified_relations(summary.run_id, "supersedes")
    assert relation.ordering_basis == "crawl_diff"
    assert (relation.claim_a, relation.claim_b) == (pair.newer.claim_id, pair.older.claim_id)
    roles = {e.role for e in store.relation_evidence(relation.relation_id) if e.verified}
    assert roles == {"older", "newer"}


def test_an_unchanged_statement_on_a_changed_page_is_not_paired(tmp_path: Path) -> None:
    store, old_run, new_run = world(tmp_path)
    summary = run_crawl_diff(store, old_run, new_run)
    assert all("Uploads" not in p.older.quote for p in summary.pairs)


def test_a_statement_still_on_the_new_page_is_not_an_edit(tmp_path: Path) -> None:
    # The new page keeps the old sentence and adds a new one: both values stand, so nothing was
    # superseded by an edit (the text detector, not crawl-diff, must judge that).
    both = NEW_LIMITS.replace(
        "The API allows 120 requests per minute.\n",
        "The API allows 120 requests per minute.\nThe API allows 60 requests per minute.\n",
    )
    store, old_run, new_run = world(tmp_path, both)
    assert run_crawl_diff(store, old_run, new_run).pairs == []


def test_as_of_reports_the_version_seen_and_the_change_window(tmp_path: Path) -> None:
    store, old_run, new_run = world(tmp_path)
    run_crawl_diff(store, old_run, new_run)
    before = as_of(store, URL, "2026-11-07")
    assert before.version_date == "2026-11-05" and before.doc_id == _doc(OLD_LIMITS)
    after = as_of(store, URL, "2026-11-30")
    assert after.version_date == "2026-11-11" and after.doc_id == _doc(NEW_LIMITS)
    (change,) = after.changes
    assert (change.seen_old, change.seen_new) == ("2026-11-05", "2026-11-11")
    assert "60" in change.older_quote and "120" in change.newer_quote
    assert as_of(store, URL, "2026-01-01").version_date is None
    assert as_of(store, OTHER, "2026-11-30").changes == []


def test_runs_must_be_complete_extract_runs_in_time_order(tmp_path: Path) -> None:
    store, old_run, new_run = world(tmp_path)
    with pytest.raises(StoreError, match="earlier"):
        run_crawl_diff(store, new_run, old_run)
    with pytest.raises(StoreError, match="complete extract"):
        run_crawl_diff(store, old_run, run_crawl_diff(store, old_run, new_run).run_id)
