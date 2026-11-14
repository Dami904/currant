"""Orchestrate one crawl: discover pages from indexes, fetch them, write the snapshot.

Rules that keep a rerun from losing what an earlier run proved:

* Every run starts from the previous manifest, so a skipped corpus, a failed index, or a
  lowered page cap never makes a record disappear. A record changes only when this run has
  better information for that exact URL.
* A failed fetch (including a failed `--refresh`) never replaces a good, intact copy: the copy
  is kept and the failure is noted in `last_attempt`.
* A page that an index no longer lists is marked `removed`, not deleted. Its file stays.
* Pages already FETCHED and intact are not requested again unless `refresh` is set. UNKNOWN,
  FAILED and NOT_FOUND pages are retried. Indexes are always refetched.
* One crawl per snapshot date at a time (a lock file), and a crash leaves an unfinished
  manifest that `verify` rejects and the next run resumes from.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from currant import __version__
from currant.crawl.config import Corpus
from currant.crawl.fetch import Fetcher, FetchResult, Outcome
from currant.crawl.index import parse_index
from currant.crawl.snapshot import (
    LOCK_NAME,
    MANIFEST_NAME,
    Record,
    SnapshotError,
    build_manifest,
    inside,
    load_manifest,
    records_from_manifest,
    relative_path,
    sha256_hex,
    write_atomic,
    write_manifest,
)
from currant.crawl.urls import is_allowed
from currant.obs import JsonLogger, utc_now

CHECKPOINT_EVERY = 25
_BAD_STATUSES = frozenset({"unknown", "failed", "blocked"})

Key = tuple[str, str, str]  # (kind, corpus for indexes else "", url)


@dataclass(frozen=True)
class CrawlSummary:
    manifest: dict[str, Any]
    problems: int  # count of things a human must look at; the CLI exits non-zero if > 0


def _key(record: Record) -> Key:
    return (record.kind, record.corpus if record.kind == "index" else "", record.url)


def _record_from(
    result: FetchResult, *, corpus: str, kind: str, rel: str, sources: list[str]
) -> Record:
    held = result.outcome is Outcome.FETCHED and result.body is not None
    return Record(
        url=result.url,
        corpus=corpus,
        status=result.outcome.value,
        kind=kind,
        path=rel if held else None,
        content_sha256=sha256_hex(result.body) if held and result.body is not None else None,
        size=len(result.body) if held and result.body is not None else None,
        http_status=result.http_status,
        content_type=result.content_type,
        etag=result.etag,
        last_modified=result.last_modified,
        fetched_at=result.fetched_at,
        attempts=result.attempts,
        error=result.error,
        sources=sources,
    )


def _still_intact(snapshot_dir: Path, record: Record) -> bool:
    """True if `record` is a fetched copy whose file is on disk, inside the snapshot, and
    matches its hash. The path comes from a manifest, so it is never trusted blindly."""
    if record.status != "fetched" or not record.path or not record.content_sha256:
        return False
    target = inside(snapshot_dir, record.path)
    if target is None:
        return False
    try:
        return sha256_hex(target.read_bytes()) == record.content_sha256
    except OSError:
        return False


def _keep_with_attempt(old: Record, new: Record) -> Record:
    """Keep the good copy `old`, and note that a later attempt (`new`) failed."""
    return replace(
        old,
        last_attempt={
            "status": new.status,
            "error": new.error,
            "http_status": new.http_status,
            "at": new.fetched_at,
        },
    )


def _safe_fetch(
    fetcher: Fetcher, url: str, logger: JsonLogger, now: Callable[[], datetime]
) -> FetchResult:
    """Fetch, but turn any unexpected exception into a logged UNKNOWN so one bad URL cannot
    take the whole crawl (and its progress) down."""
    try:
        return fetcher.fetch(url)
    except Exception as exc:
        logger.error("fetch_crashed", url=url, error=repr(exc))
        return FetchResult(
            url, Outcome.UNKNOWN, 0, now().isoformat(), error=f"unexpected error: {exc!r}"
        )


@contextlib.contextmanager
def _locked(snapshot_dir: Path) -> Iterator[None]:
    lock = snapshot_dir / LOCK_NAME
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SnapshotError(
            f"lock file {lock} exists: another crawl is running on this date. "
            "If a crashed crawl left it behind, delete the file and rerun."
        ) from exc
    with os.fdopen(descriptor, "w") as handle:
        handle.write(str(os.getpid()))
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink(missing_ok=True)


def _sweep_tmp(snapshot_dir: Path) -> None:
    """Remove half-written temp files left by a crash; they would fail `verify` forever."""
    for stale in snapshot_dir.rglob("*.tmp"):
        with contextlib.suppress(OSError):
            stale.unlink()


def _load_previous(snapshot_dir: Path, logger: JsonLogger) -> list[Record]:
    try:
        manifest = load_manifest(snapshot_dir)
        return [] if manifest is None else records_from_manifest(manifest)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        path = snapshot_dir / MANIFEST_NAME
        logger.error("manifest_unreadable", path=str(path), error=repr(exc))
        raise SnapshotError(
            f"cannot read {path}: {exc}. It was not modified; fix or delete it and rerun."
        ) from exc


def _prune_unreferenced(snapshot_dir: Path, records: dict[Key, Record], logger: JsonLogger) -> None:
    """Delete files under pages/ and indexes/ that no record points at (for example the
    corrupt copy a fresh fetch replaced). Only ever walks inside the snapshot directory."""
    referenced = {
        target
        for record in records.values()
        if record.path and (target := inside(snapshot_dir, record.path)) is not None
    }
    for sub in ("pages", "indexes"):
        folder = snapshot_dir / sub
        if not folder.is_dir():
            continue
        for found in sorted(folder.rglob("*")):
            if found.is_file() and found.resolve() not in referenced:
                logger.warn("orphan_removed", path=str(found.relative_to(snapshot_dir)))
                with contextlib.suppress(OSError):
                    found.unlink()


class _Run:
    def __init__(
        self,
        corpora: list[Corpus],
        *,
        snapshot_dir: Path,
        snapshot_date: str,
        config_sha256: str,
        client: httpx.Client,
        logger: JsonLogger,
        refresh: bool,
        delay: float,
        max_attempts: int,
        allow_truncation: bool,
        sleep: Callable[[float], None],
        now: Callable[[], datetime],
    ) -> None:
        self.corpora = corpora
        self.dir = snapshot_dir
        self.date = snapshot_date
        self.config_sha256 = config_sha256
        self.client = client
        self.log = logger
        self.refresh = refresh
        self.delay = delay
        self.max_attempts = max_attempts
        self.allow_truncation = allow_truncation
        self.sleep = sleep
        self.now = now
        self.started_at = now().isoformat()
        self.prior: dict[Key, Record] = {}
        self.records: dict[Key, Record] = {}
        self.truncated: dict[str, dict[str, Any]] = {}
        self.claimed: dict[str, str] = {}
        self.problems = 0

    def execute(self) -> CrawlSummary:
        _sweep_tmp(self.dir)
        self.prior = {_key(r): r for r in _load_previous(self.dir, self.log)}
        # Seed from the past: nothing is lost unless this run replaces it with something better.
        self.records = dict(self.prior)
        try:
            for corpus in self.corpora:
                if corpus.enabled:
                    self._corpus(corpus)
        except BaseException:
            self._checkpoint_after_failure()
            raise
        manifest = self._checkpoint(finished=True)
        _prune_unreferenced(self.dir, self.records, self.log)
        return CrawlSummary(manifest=manifest, problems=self.problems)

    def _checkpoint(self, *, finished: bool) -> dict[str, Any]:
        manifest = build_manifest(
            snapshot_date=self.date,
            crawler_version=__version__,
            config_sha256=self.config_sha256,
            started_at=self.started_at,
            finished_at=self.now().isoformat() if finished else None,
            records=list(self.records.values()),
            truncated=self.truncated,
        )
        write_manifest(self.dir, manifest)
        return manifest

    def _checkpoint_after_failure(self) -> None:
        try:
            self._checkpoint(finished=False)
        except Exception as exc:
            self.log.error("checkpoint_failed", error=repr(exc))

    # --- one corpus ------------------------------------------------------------------

    def _corpus(self, corpus: Corpus) -> None:
        fetcher = Fetcher(
            self.client,
            corpus.allow,
            logger=self.log,
            max_attempts=self.max_attempts,
            sleep=self.sleep,
            now=self.now,
        )
        sources: dict[str, list[str]] = {}
        listing_complete = self._fetch_indexes(corpus, fetcher, sources)
        explicit = set(corpus.pages)
        for url in corpus.pages:
            sources.setdefault(url, []).append("config")
        listed = set(sources)  # everything this corpus names right now, before any cap

        urls = self._claim(corpus, list(sources))
        urls = self._apply_cap(corpus, urls, explicit, sources)
        self.log.info("corpus_start", corpus=corpus.name, pages=len(urls))
        fetched = self._fetch_pages(corpus, fetcher, urls, sources, explicit)
        if listing_complete:
            self._mark_removed(corpus, listed)
        self.log.info("corpus_done", corpus=corpus.name, fetched=fetched)

    def _fetch_indexes(
        self, corpus: Corpus, fetcher: Fetcher, sources: dict[str, list[str]]
    ) -> bool:
        """Fetch and parse the corpus indexes. Returns True if the page listing is complete,
        meaning every index was fetched (so a page missing from it really is gone)."""
        complete = True
        for ordinal, index_url in enumerate(corpus.indexes):
            result = _safe_fetch(fetcher, index_url, self.log, self.now)
            rel = relative_path("index", corpus.name, index_url, ordinal)
            record = _record_from(result, corpus=corpus.name, kind="index", rel=rel, sources=[])
            key = _key(record)
            if result.outcome is Outcome.FETCHED and result.body is not None:
                write_atomic(self.dir / rel, result.body)
                self.records[key] = record
                text = result.body.decode("utf-8", errors="replace")
                for url in parse_index(text, index_url):
                    if is_allowed(url, corpus.allow):
                        sources.setdefault(url, []).append(f"index:{index_url}")
            else:
                complete = False
                self.problems += 1
                self.log.error(
                    "index_not_fetched", corpus=corpus.name, url=index_url, status=record.status
                )
                old = self.prior.get(key)
                if old is not None and _still_intact(self.dir, old):
                    self.records[key] = _keep_with_attempt(old, record)
                else:
                    self.records[key] = record
            self.sleep(self.delay)
        return complete

    def _claim(self, corpus: Corpus, urls: list[str]) -> list[str]:
        """A URL belongs to the first corpus that names it; later corpora skip it."""
        mine: list[str] = []
        for url in urls:
            owner = self.claimed.setdefault(url, corpus.name)
            if owner == corpus.name:
                mine.append(url)
            else:
                self.log.warn("duplicate_url_skipped", url=url, corpus=corpus.name, owner=owner)
        return mine

    def _apply_cap(
        self, corpus: Corpus, urls: list[str], explicit: set[str], sources: dict[str, list[str]]
    ) -> list[str]:
        if len(urls) <= corpus.max_pages:
            return urls
        keep = [u for u in urls if u in explicit]
        rest = sorted(u for u in urls if u not in explicit)  # sorted: the same cut every run
        if len(keep) > corpus.max_pages:
            self.log.warn(
                "explicit_pages_exceed_cap",
                corpus=corpus.name,
                pages=len(keep),
                cap=corpus.max_pages,
            )
        room = max(corpus.max_pages - len(keep), 0)
        dropped = rest[room:]
        kept = keep + rest[:room]
        self.truncated[corpus.name] = {"found": len(urls), "kept": len(kept), "dropped": dropped}
        self.log.warn(
            "corpus_truncated",
            corpus=corpus.name,
            found=len(urls),
            kept=len(kept),
            dropped=len(dropped),
        )
        for url in dropped:
            key: Key = ("page", "", url)
            if key not in self.records:  # an earlier fetched copy, if any, is left alone
                self.records[key] = Record(
                    url=url,
                    corpus=corpus.name,
                    status="skipped_cap",
                    sources=sources[url],
                )
        if not self.allow_truncation:
            self.problems += 1
        return kept

    def _fetch_pages(
        self,
        corpus: Corpus,
        fetcher: Fetcher,
        urls: list[str],
        sources: dict[str, list[str]],
        explicit: set[str],
    ) -> int:
        fetched = 0
        for number, url in enumerate(urls, start=1):
            if number % CHECKPOINT_EVERY == 0:  # before the cache shortcut, so it always fires
                self._checkpoint(finished=False)
            key: Key = ("page", "", url)
            old = self.prior.get(key)
            if old is not None and not self.refresh and _still_intact(self.dir, old):
                self.records[key] = replace(old, sources=sources[url])
                continue

            result = _safe_fetch(fetcher, url, self.log, self.now)
            rel = relative_path("page", corpus.name, url)
            new = _record_from(
                result, corpus=corpus.name, kind="page", rel=rel, sources=sources[url]
            )
            if result.outcome is Outcome.FETCHED and result.body is not None:
                write_atomic(self.dir / rel, result.body)
                self.records[key] = new
                fetched += 1
            elif old is not None and _still_intact(self.dir, old):
                # A failed refresh must not destroy evidence we already hold.
                self.records[key] = _keep_with_attempt(replace(old, sources=sources[url]), new)
                self.problems += 1
            else:
                self.records[key] = new
                if new.status in _BAD_STATUSES or (new.status == "not_found" and url in explicit):
                    self.problems += 1
            self.sleep(self.delay)
        return fetched

    def _mark_removed(self, corpus: Corpus, listed: set[str]) -> None:
        """Pages this corpus used to name but no longer does (and only when the listing was
        read in full) are marked removed. Their files and hashes stay."""
        for key, record in self.prior.items():
            if record.kind != "page" or record.corpus != corpus.name:
                continue
            if record.url in listed or record.status == "removed":
                continue
            if self.claimed.get(record.url, corpus.name) != corpus.name:
                continue
            self.log.warn("page_removed", corpus=corpus.name, url=record.url)
            self.records[key] = replace(record, status="removed")


def run_crawl(
    corpora: list[Corpus],
    *,
    out_root: Path,
    snapshot_date: str,
    config_sha256: str,
    client: httpx.Client,
    logger: JsonLogger,
    refresh: bool = False,
    allow_truncation: bool = False,
    delay: float = 0.25,
    max_attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> CrawlSummary:
    snapshot_dir = out_root / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with _locked(snapshot_dir):
        return _Run(
            corpora,
            snapshot_dir=snapshot_dir,
            snapshot_date=snapshot_date,
            config_sha256=config_sha256,
            client=client,
            logger=logger,
            refresh=refresh,
            delay=delay,
            max_attempts=max_attempts,
            allow_truncation=allow_truncation,
            sleep=sleep,
            now=now,
        ).execute()
