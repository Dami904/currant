from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from currant.crawl import runner
from currant.crawl.config import Corpus
from currant.crawl.fetch import Fetcher, FetchResult
from currant.crawl.runner import CrawlSummary, run_crawl
from currant.crawl.snapshot import (
    MANIFEST_NAME,
    SnapshotError,
    sha256_hex,
    verify_snapshot,
    write_atomic,
    write_manifest,
)
from currant.obs import JsonLogger
from tests.helpers import fixed_now, make_client, md, quiet_logger

BASE = "https://docs.example.com"
INDEX = f"{BASE}/llms.txt"
INTRO = f"{BASE}/intro.md"
MODELS = f"{BASE}/models.md"
GONE = f"{BASE}/gone.md"
CHANGELOG = f"{BASE}/changelog.md"
DATE = "2026-11-05"

CORPUS = Corpus(
    name="docs",
    enabled=True,
    indexes=(INDEX,),
    allow=(f"{BASE}/",),
    pages=(CHANGELOG,),
    max_pages=50,
)

OTHER_PAGE = "https://other.example.com/p.md"
OTHER = Corpus("other", True, (), ("https://other.example.com/",), (OTHER_PAGE,), 50)

INDEX_TEXT = f"""# Docs
- [Intro]({INTRO}): start
- [Models](/models.md)
- [Gone](/gone.md)
- [Outside](https://evil.example.org/x.md)
- [Mail](mailto:a@b.c)
- [Top](#top)
"""

Routes = dict[str, Callable[[], httpx.Response]]


def site() -> Routes:
    return {
        INDEX: lambda: md(INDEX_TEXT),
        INTRO: lambda: md("# Intro\nv1\n"),
        MODELS: lambda: md("# Models\nfoo\n"),
        GONE: lambda: httpx.Response(404),
        CHANGELOG: lambda: md("# Changelog\n"),
        OTHER_PAGE: lambda: md("# Other\n"),
    }


def crawl(
    tmp_path: Path,
    routes: Routes,
    *,
    corpora: list[Corpus] | None = None,
    refresh: bool = False,
    allow_truncation: bool = False,
    logger: JsonLogger | None = None,
) -> tuple[CrawlSummary, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        route = routes.get(str(request.url))
        return route() if route else httpx.Response(404)

    summary = run_crawl(
        corpora or [CORPUS],
        out_root=tmp_path,
        snapshot_date=DATE,
        config_sha256="cfg",
        client=make_client(handler),
        logger=logger or quiet_logger(),
        refresh=refresh,
        allow_truncation=allow_truncation,
        delay=0,
        max_attempts=2,
        sleep=lambda _s: None,
        now=fixed_now,
    )
    return summary, requested


def snap(tmp_path: Path) -> Path:
    return tmp_path / DATE


def by_url(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["url"]: p for p in manifest["pages"]}


def edit_manifest(tmp_path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    path = snap(tmp_path) / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def problems_text(tmp_path: Path) -> str:
    return "\n".join(verify_snapshot(snap(tmp_path)))


# --- the happy path ----------------------------------------------------------------------


def test_first_crawl_writes_a_verifiable_snapshot(tmp_path: Path) -> None:
    summary, requested = crawl(tmp_path, site())
    manifest = summary.manifest

    assert summary.problems == 0
    assert manifest["counts"] == {"fetched": 3, "not_found": 1}
    assert manifest["finished_at"] is not None
    assert manifest["complete"] is True
    assert manifest["truncated_corpora"] == []
    assert set(by_url(manifest)) == {INTRO, MODELS, GONE, CHANGELOG}
    # Off-list and non-http links are never requested, and the index never lists itself.
    assert sorted(requested) == sorted([INDEX, INTRO, MODELS, GONE, CHANGELOG])
    assert verify_snapshot(snap(tmp_path)) == []


def test_manifest_records_hash_split_and_provenance(tmp_path: Path) -> None:
    manifest = crawl(tmp_path, site())[0].manifest
    intro = by_url(manifest)[INTRO]
    assert intro["status"] == "fetched"
    assert "split" not in intro  # pages carry no dev/test label; items do (currant.evalset)
    assert intro["sources"] == [f"index:{INDEX}"]
    assert intro["size"] == len(b"# Intro\nv1\n")
    assert len(intro["content_sha256"]) == 64
    assert (snap(tmp_path) / intro["path"]).read_bytes() == b"# Intro\nv1\n"
    assert by_url(manifest)[CHANGELOG]["sources"] == ["config"]
    assert by_url(manifest)[GONE]["path"] is None


def test_rerun_is_incremental_and_corpus_hash_is_stable(tmp_path: Path) -> None:
    first = crawl(tmp_path, site())[0].manifest
    second, requested = crawl(tmp_path, site())
    # Fetched pages are skipped. The index is refetched to discover new pages, and the dead
    # link is retried because a missing page may be published later.
    assert requested == [INDEX, GONE]
    assert second.manifest["corpus_hash"] == first["corpus_hash"]
    assert second.manifest["counts"] == first["counts"]


def test_refresh_picks_up_changed_content(tmp_path: Path) -> None:
    first = crawl(tmp_path, site())[0].manifest
    routes = site()
    routes[INTRO] = lambda: md("# Intro\nv2 - the limit changed\n")
    second, requested = crawl(tmp_path, routes, refresh=True)
    assert INTRO in requested
    assert second.manifest["corpus_hash"] != first["corpus_hash"]
    assert verify_snapshot(snap(tmp_path)) == []


def test_unknown_is_recorded_then_reconciled_on_rerun(tmp_path: Path) -> None:
    routes = site()
    routes[MODELS] = lambda: httpx.Response(503)
    first, _ = crawl(tmp_path, routes)
    record = by_url(first.manifest)[MODELS]
    assert record["status"] == "unknown"  # a 5xx is not FAILED
    assert record["path"] is None
    assert record["attempts"] == 2
    assert first.problems == 1
    assert first.manifest["complete"] is False

    second, requested = crawl(tmp_path, site())  # the site recovers
    assert MODELS in requested
    assert INTRO not in requested  # already fetched and intact
    assert by_url(second.manifest)[MODELS]["status"] == "fetched"
    assert second.problems == 0
    assert second.manifest["complete"] is True


def test_explicit_page_that_is_missing_is_a_problem_but_a_dead_link_is_not(
    tmp_path: Path,
) -> None:
    routes = site()
    routes[CHANGELOG] = lambda: httpx.Response(404)
    summary, _ = crawl(tmp_path, routes)
    assert by_url(summary.manifest)[GONE]["status"] == "not_found"  # dead link: data
    assert summary.problems == 1  # only the explicitly configured page counts


def test_index_failure_on_a_first_run_is_a_problem_but_explicit_pages_still_fetch(
    tmp_path: Path,
) -> None:
    routes = site()
    routes[INDEX] = lambda: httpx.Response(500)
    summary, _ = crawl(tmp_path, routes)
    assert summary.problems == 1
    assert summary.manifest["indexes"][0]["status"] == "unknown"
    assert by_url(summary.manifest)[CHANGELOG]["status"] == "fetched"


def test_disabled_corpus_makes_no_requests(tmp_path: Path) -> None:
    summary, requested = crawl(tmp_path, site(), corpora=[replace(CORPUS, enabled=False)])
    assert requested == []
    assert summary.manifest["pages"] == []


def test_tampered_file_is_refetched_on_rerun(tmp_path: Path) -> None:
    manifest = crawl(tmp_path, site())[0].manifest
    (snap(tmp_path) / by_url(manifest)[INTRO]["path"]).write_bytes(b"corrupted")
    _, requested = crawl(tmp_path, site())
    assert INTRO in requested
    assert verify_snapshot(snap(tmp_path)) == []


# --- reruns must never lose what an earlier run proved -----------------------------------


def test_a_corrupt_file_replaced_by_a_failed_fetch_is_pruned_not_left_as_an_orphan(
    tmp_path: Path,
) -> None:
    manifest = crawl(tmp_path, site())[0].manifest
    corrupt = snap(tmp_path) / by_url(manifest)[INTRO]["path"]
    corrupt.write_bytes(b"corrupted")  # no longer a copy worth keeping
    routes = site()
    routes[INTRO] = lambda: httpx.Response(503)
    second, _ = crawl(tmp_path, routes)

    assert by_url(second.manifest)[INTRO]["status"] == "unknown"
    assert not corrupt.exists()
    assert verify_snapshot(snap(tmp_path), allow_unreconciled=True) == []


def test_index_outage_on_a_rerun_keeps_every_record(tmp_path: Path) -> None:
    first = crawl(tmp_path, site())[0].manifest
    routes = site()
    routes[INDEX] = lambda: httpx.Response(503)
    second, _ = crawl(tmp_path, routes)

    assert set(by_url(second.manifest)) == set(by_url(first))
    assert second.manifest["corpus_hash"] == first["corpus_hash"]
    index = second.manifest["indexes"][0]
    assert index["status"] == "fetched"  # the earlier good copy is kept
    assert index["last_attempt"]["status"] == "unknown"  # and the outage is on record
    assert second.problems == 1
    assert verify_snapshot(snap(tmp_path)) == []


def test_unknown_page_survives_an_index_outage(tmp_path: Path) -> None:
    routes = site()
    routes[MODELS] = lambda: httpx.Response(503)
    crawl(tmp_path, routes)

    routes[INDEX] = lambda: httpx.Response(503)
    second, _ = crawl(tmp_path, routes)
    assert by_url(second.manifest)[MODELS]["status"] == "unknown"  # still on the books
    assert second.manifest["finished_at"] is not None


def test_subset_rerun_keeps_the_other_corpora(tmp_path: Path) -> None:
    first = crawl(tmp_path, site(), corpora=[CORPUS, OTHER])[0].manifest
    assert OTHER_PAGE in by_url(first)

    second, requested = crawl(tmp_path, site(), corpora=[CORPUS, replace(OTHER, enabled=False)])
    assert OTHER_PAGE not in requested
    assert by_url(second.manifest)[OTHER_PAGE]["status"] == "fetched"
    assert second.manifest["corpus_hash"] == first["corpus_hash"]
    assert verify_snapshot(snap(tmp_path)) == []


def test_page_dropped_from_the_index_is_marked_removed_not_lost(tmp_path: Path) -> None:
    first = crawl(tmp_path, site())[0].manifest
    routes = site()
    routes[INDEX] = lambda: md(INDEX_TEXT.replace("- [Models](/models.md)\n", ""))
    second, _ = crawl(tmp_path, routes)

    record = by_url(second.manifest)[MODELS]
    assert record["status"] == "removed"
    assert record["content_sha256"] == by_url(first)[MODELS]["content_sha256"]
    assert (snap(tmp_path) / record["path"]).exists()  # the evidence stays
    assert second.manifest["corpus_hash"] != first["corpus_hash"]  # but it is no longer corpus
    assert verify_snapshot(snap(tmp_path)) == []


@pytest.mark.parametrize("status", [503, 404])
def test_failed_refresh_keeps_the_good_evidence(tmp_path: Path, status: int) -> None:
    first = crawl(tmp_path, site())[0].manifest
    routes = site()
    routes[INTRO] = lambda: httpx.Response(status)
    second, _ = crawl(tmp_path, routes, refresh=True)

    record = by_url(second.manifest)[INTRO]
    assert record["status"] == "fetched"
    assert record["content_sha256"] == by_url(first)[INTRO]["content_sha256"]
    assert record["last_attempt"]["status"] in ("unknown", "not_found")
    assert (snap(tmp_path) / record["path"]).read_bytes() == b"# Intro\nv1\n"
    assert second.manifest["corpus_hash"] == first["corpus_hash"]
    assert second.problems >= 1
    assert verify_snapshot(snap(tmp_path)) == []


def test_lowering_the_cap_on_a_rerun_does_not_drop_earlier_pages(tmp_path: Path) -> None:
    first = crawl(tmp_path, site())[0].manifest
    second, _ = crawl(tmp_path, site(), corpora=[replace(CORPUS, max_pages=2)])
    assert set(by_url(second.manifest)) == set(by_url(first))
    assert second.manifest["corpus_hash"] == first["corpus_hash"]
    assert verify_snapshot(snap(tmp_path)) == []


# --- crashes must be logged and leave something resumable --------------------------------


def test_an_unexpected_exception_in_fetch_becomes_unknown_and_the_crawl_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Fetcher.fetch

    def flaky(self: Fetcher, url: str) -> FetchResult:
        if url == MODELS:
            raise RuntimeError("boom")
        return original(self, url)

    monkeypatch.setattr(Fetcher, "fetch", flaky)
    out = io.StringIO()
    summary, _ = crawl(tmp_path, site(), logger=JsonLogger(run_id="t", stream=out, now=fixed_now))

    record = by_url(summary.manifest)[MODELS]
    assert record["status"] == "unknown"
    assert "RuntimeError" in record["error"]
    assert by_url(summary.manifest)[INTRO]["status"] == "fetched"  # the crawl went on
    assert summary.problems == 1
    assert "fetch_crashed" in out.getvalue()


def test_a_crash_midway_leaves_an_unfinished_but_resumable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_write(path: Path, data: bytes) -> None:
        if "pages" in path.parts:
            raise OSError("disk full")
        write_atomic(path, data)

    monkeypatch.setattr(runner, "write_atomic", failing_write)
    with pytest.raises(OSError, match="disk full"):
        crawl(tmp_path, site())

    manifest = json.loads((snap(tmp_path) / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["finished_at"] is None
    assert manifest["indexes"][0]["status"] == "fetched"
    assert "not finished" in problems_text(tmp_path)
    assert not (snap(tmp_path) / ".crawl.lock").exists()  # the lock is released on a crash

    monkeypatch.setattr(runner, "write_atomic", write_atomic)  # the disk recovers
    resumed, _ = crawl(tmp_path, site())
    assert resumed.manifest["finished_at"] is not None
    assert verify_snapshot(snap(tmp_path)) == []


def test_a_corrupt_manifest_stops_the_crawl_and_is_never_overwritten(tmp_path: Path) -> None:
    snap(tmp_path).mkdir(parents=True)
    path = snap(tmp_path) / MANIFEST_NAME
    path.write_text("{not json", encoding="utf-8")
    out = io.StringIO()
    with pytest.raises(SnapshotError, match="not modified"):
        crawl(tmp_path, site(), logger=JsonLogger(run_id="t", stream=out, now=fixed_now))
    assert path.read_text(encoding="utf-8") == "{not json"
    assert "manifest_unreadable" in out.getvalue()
    assert not (snap(tmp_path) / ".crawl.lock").exists()


def test_a_second_crawl_on_the_same_date_is_refused_and_does_not_steal_the_lock(
    tmp_path: Path,
) -> None:
    snap(tmp_path).mkdir(parents=True)
    lock = snap(tmp_path) / ".crawl.lock"
    lock.write_text("someone else", encoding="utf-8")
    with pytest.raises(SnapshotError, match="lock"):
        crawl(tmp_path, site())
    assert lock.read_text(encoding="utf-8") == "someone else"


def test_the_lock_is_released_after_a_normal_run(tmp_path: Path) -> None:
    crawl(tmp_path, site())
    assert not (snap(tmp_path) / ".crawl.lock").exists()


def test_stale_tmp_files_from_a_crash_are_swept(tmp_path: Path) -> None:
    crawl(tmp_path, site())
    stale = [snap(tmp_path) / "pages" / "docs" / "x.md.tmp", snap(tmp_path) / "indexes" / "y.tmp"]
    for path in stale:
        path.write_bytes(b"half written")
    assert "file not in manifest" in problems_text(tmp_path)
    crawl(tmp_path, site())
    assert not any(path.exists() for path in stale)
    assert verify_snapshot(snap(tmp_path)) == []


def test_a_tampered_manifest_path_outside_the_snapshot_is_not_trusted_or_deleted(
    tmp_path: Path,
) -> None:
    crawl(tmp_path, site())
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"x")

    def point_outside(data: dict[str, Any]) -> None:
        record = next(p for p in data["pages"] if p["url"] == INTRO)
        record.update(path="../outside.txt", content_sha256=sha256_hex(b"x"), size=1)

    edit_manifest(tmp_path, point_outside)
    _, requested = crawl(tmp_path, site())
    assert INTRO in requested  # the escaping record was not accepted as a cache hit
    assert outside.read_bytes() == b"x"  # and nothing outside the snapshot was touched
    assert verify_snapshot(snap(tmp_path)) == []


def test_a_url_listed_by_two_corpora_has_one_owner_and_one_file(tmp_path: Path) -> None:
    summary, requested = crawl(tmp_path, site(), corpora=[CORPUS, replace(CORPUS, name="dup")])
    assert {p["corpus"] for p in summary.manifest["pages"]} == {"docs"}
    assert requested.count(INTRO) == 1
    assert verify_snapshot(snap(tmp_path)) == []


def test_checkpoints_also_fire_on_mostly_cached_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crawl(tmp_path, site())
    writes: list[str] = []

    def counting(directory: Path, manifest: dict[str, Any]) -> None:
        writes.append(str(manifest["finished_at"]))
        write_manifest(directory, manifest)

    monkeypatch.setattr(runner, "CHECKPOINT_EVERY", 2)
    monkeypatch.setattr(runner, "write_manifest", counting)
    crawl(tmp_path, site())  # 4 pages, every fetched one is a cache hit
    # Two mid-run checkpoints (unfinished) plus the final write.
    assert writes.count("None") == 2 and len(writes) == 3


# --- the page cap ------------------------------------------------------------------------


def test_page_cap_is_deterministic_and_records_every_dropped_url(tmp_path: Path) -> None:
    summary, requested = crawl(tmp_path, site(), corpora=[replace(CORPUS, max_pages=3)])
    manifest = summary.manifest

    assert manifest["truncated"]["docs"] == {"found": 4, "kept": 3, "dropped": [MODELS]}
    assert manifest["truncated_corpora"] == ["docs"]
    assert CHANGELOG in requested  # configured pages are never dropped by the cap
    assert MODELS not in requested
    assert by_url(manifest)[MODELS]["status"] == "skipped_cap"
    assert manifest["complete"] is False
    assert summary.problems == 1  # truncation needs a human unless explicitly allowed


def test_allow_truncation_silences_the_exit_code_but_not_the_manifest(tmp_path: Path) -> None:
    summary, _ = crawl(
        tmp_path, site(), corpora=[replace(CORPUS, max_pages=3)], allow_truncation=True
    )
    assert summary.problems == 0
    assert summary.manifest["complete"] is False
    assert "skipped_cap" in problems_text(tmp_path)


# --- verify_snapshot: every way a snapshot can be wrong must be caught -------------------


def test_verify_detects_modified_file(tmp_path: Path) -> None:
    manifest = crawl(tmp_path, site())[0].manifest
    (snap(tmp_path) / by_url(manifest)[INTRO]["path"]).write_bytes(b"# Intro\nv9\n")
    assert "content hash mismatch" in problems_text(tmp_path)


def test_verify_detects_missing_file(tmp_path: Path) -> None:
    manifest = crawl(tmp_path, site())[0].manifest
    (snap(tmp_path) / by_url(manifest)[INTRO]["path"]).unlink()
    assert "file missing" in problems_text(tmp_path)


def test_verify_detects_file_not_in_manifest(tmp_path: Path) -> None:
    crawl(tmp_path, site())
    (snap(tmp_path) / "pages" / "docs" / "smuggled.md").write_text("x", encoding="utf-8")
    assert "file not in manifest" in problems_text(tmp_path)


def test_verify_detects_wrong_corpus_hash(tmp_path: Path) -> None:
    crawl(tmp_path, site())
    edit_manifest(tmp_path, lambda d: d.update(corpus_hash="0" * 64))
    assert "corpus_hash does not match" in problems_text(tmp_path)


def test_verify_detects_path_escaping_the_snapshot_dir(tmp_path: Path) -> None:
    def escape(data: dict[str, Any]) -> None:
        data["pages"][0]["path"] = "../../outside.md"
        data["pages"][0]["status"] = "fetched"
        data["pages"][0]["content_sha256"] = "0" * 64

    crawl(tmp_path, site())
    edit_manifest(tmp_path, escape)
    assert "escapes the snapshot dir" in problems_text(tmp_path)


def test_verify_reports_missing_or_broken_manifest(tmp_path: Path) -> None:
    snap(tmp_path).mkdir(parents=True)
    assert "no manifest.json" in problems_text(tmp_path)
    (snap(tmp_path) / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    assert "manifest unreadable" in problems_text(tmp_path)
    (snap(tmp_path) / MANIFEST_NAME).write_text('{"schema": 99}', encoding="utf-8")
    assert "manifest malformed" in problems_text(tmp_path)


def test_verify_fails_on_an_unfinished_manifest(tmp_path: Path) -> None:
    crawl(tmp_path, site())
    edit_manifest(tmp_path, lambda d: d.update(finished_at=None))
    assert "not finished" in problems_text(tmp_path)


def test_verify_fails_on_unreconciled_records_unless_allowed(tmp_path: Path) -> None:
    routes = site()
    routes[MODELS] = lambda: httpx.Response(503)
    crawl(tmp_path, routes)
    assert "unreconciled" in problems_text(tmp_path)
    assert verify_snapshot(snap(tmp_path), allow_unreconciled=True) == []


def test_a_manifest_written_before_the_split_moved_to_items_still_loads(tmp_path: Path) -> None:
    crawl(tmp_path, site())

    def add_legacy_split(data: dict[str, Any]) -> None:
        for page in data["pages"]:
            page["split"] = "dev"
        data["split_rule"] = {"version": "url-sha256-v1", "dev_percent": 60}

    edit_manifest(tmp_path, add_legacy_split)
    assert verify_snapshot(snap(tmp_path)) == []  # the old field is ignored, not an error
    again, _ = crawl(tmp_path, site())  # and the next crawl writes the new format
    assert all("split" not in page for page in again.manifest["pages"])
