"""On-disk snapshot format and its verifier.

    snapshots/2026-11-05/
        manifest.json                 every page: url, status, sha256, fetched_at, ...
        crawl.log.jsonl               structured log of the run
        indexes/<corpus>-<n>.txt      raw index files
        pages/<corpus>/<slug>--<h8>.md  raw page bytes, exactly as received

`corpus_hash` is the one number every later output records: a SHA-256 over the sorted
(url, content_sha256) pairs of all fetched pages. If any page changes, it changes. It does
not say whether the corpus is complete; the manifest's `complete` flag and `verify` do.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = 1
MANIFEST_NAME = "manifest.json"
LOG_NAME = "crawl.log.jsonl"
LOCK_NAME = ".crawl.lock"

# A record in one of these states is something a human or a rerun still has to resolve.
UNRECONCILED_STATUSES = frozenset({"unknown", "failed", "blocked", "skipped_cap"})
# A record in one of these states owns a file on disk that must match its hash.
HELD_STATUSES = frozenset({"fetched", "removed"})

_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
# Fields older manifests carried that no longer exist. Pages used to be assigned dev/test by a
# URL hash; the split now lives on evaluation items (see currant.evalset), so it is ignored here.
_LEGACY_FIELDS = frozenset({"split"})


class SnapshotError(RuntimeError):
    """The snapshot directory cannot be used safely; nothing was changed."""


@dataclass
class Record:
    url: str
    corpus: str
    status: str
    kind: str = "page"  # "page" or "index"
    path: str | None = None
    content_sha256: str | None = None
    size: int | None = None
    http_status: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str | None = None
    attempts: int = 0
    error: str | None = None
    sources: list[str] = field(default_factory=list)
    # Set when a later fetch failed but the earlier good copy was kept: what happened.
    last_attempt: dict[str, Any] | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(kind: str, corpus: str, url: str, ordinal: int = 0) -> str:
    """Deterministic, traversal-safe file path (relative to the snapshot dir) for a URL."""
    if kind == "index":
        return f"indexes/{corpus}-{ordinal}.txt"
    stripped = re.sub(r"^https?://", "", url)
    slug = _SLUG_UNSAFE.sub("_", stripped).strip("._")[:80] or "page"
    return f"pages/{corpus}/{slug}--{sha256_hex(url.encode())[:8]}.md"


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, flushed to disk before the rename, so a
    crash leaves either the old file or the new one, never a half-written file under the
    final name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def corpus_hash(records: Iterable[Record]) -> str:
    lines = sorted(
        f"{r.url}\t{r.content_sha256}\n"
        for r in records
        if r.kind == "page" and r.status == "fetched" and r.content_sha256
    )
    return sha256_hex("".join(lines).encode())


def build_manifest(
    *,
    snapshot_date: str,
    crawler_version: str,
    config_sha256: str,
    started_at: str,
    finished_at: str | None,
    records: list[Record],
    truncated: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pages = sorted((r for r in records if r.kind == "page"), key=lambda r: r.url)
    indexes = sorted((r for r in records if r.kind == "index"), key=lambda r: (r.corpus, r.url))
    counts: dict[str, int] = {}
    for record in pages:
        counts[record.status] = counts.get(record.status, 0) + 1
    unreconciled = any(r.status in UNRECONCILED_STATUSES for r in records)
    return {
        "schema": MANIFEST_SCHEMA,
        "snapshot_date": snapshot_date,
        "crawler_version": crawler_version,
        "config_sha256": config_sha256,
        "started_at": started_at,
        "finished_at": finished_at,
        # `complete` is the honest summary: finished, nothing unresolved, nothing dropped by a cap.
        "complete": finished_at is not None and not unreconciled and not truncated,
        "corpus_hash": corpus_hash(pages),
        "counts": dict(sorted(counts.items())),
        "truncated_corpora": sorted(truncated),
        "truncated": {name: truncated[name] for name in sorted(truncated)},
        "indexes": [asdict(r) for r in indexes],
        "pages": [asdict(r) for r in pages],
    }


def write_manifest(snapshot_dir: Path, manifest: dict[str, Any]) -> None:
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    write_atomic(snapshot_dir / MANIFEST_NAME, text.encode("utf-8"))


def load_manifest(snapshot_dir: Path) -> dict[str, Any] | None:
    path = snapshot_dir / MANIFEST_NAME
    if not path.exists():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def records_from_manifest(manifest: dict[str, Any]) -> list[Record]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unsupported manifest schema {manifest.get('schema')!r}")
    return [
        Record(**{k: v for k, v in raw.items() if k not in _LEGACY_FIELDS})
        for raw in (*manifest["indexes"], *manifest["pages"])
    ]


def inside(snapshot_dir: Path, relative: str) -> Path | None:
    """Resolve `relative` under `snapshot_dir`, or None if it would leave the directory.

    Anything read from a manifest goes through this before it is opened, hashed or deleted.
    """
    root = snapshot_dir.resolve()
    target = (snapshot_dir / relative).resolve()
    return target if target.is_relative_to(root) else None


def verify_snapshot(snapshot_dir: Path, *, allow_unreconciled: bool = False) -> list[str]:
    """Return a list of problems (empty means the snapshot is consistent and complete).

    Checks: the manifest parses; the crawl that wrote it finished; every held file exists and
    matches its recorded size and SHA-256; no file on disk is missing from the manifest; the
    corpus hash recomputes; and
    nothing is left unresolved (unknown, failed, blocked, or dropped by the page cap) unless
    `allow_unreconciled` is set.
    """
    try:
        manifest = load_manifest(snapshot_dir)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest unreadable: {exc}"]
    if manifest is None:
        return [f"no {MANIFEST_NAME} in {snapshot_dir}"]
    try:
        records = records_from_manifest(manifest)
    except (TypeError, KeyError, ValueError) as exc:
        return [f"manifest malformed: {exc}"]

    problems: list[str] = []
    if manifest.get("finished_at") is None:
        problems.append("manifest not finished (finished_at is null): the crawl was interrupted")

    unresolved = [r for r in records if r.status in UNRECONCILED_STATUSES]
    if unresolved and not allow_unreconciled:
        tally: dict[str, int] = {}
        for record in unresolved:
            tally[record.status] = tally.get(record.status, 0) + 1
        problems.append(
            f"{len(unresolved)} unreconciled record(s) {dict(sorted(tally.items()))}: "
            "rerun the crawl, or pass --allow-unreconciled to accept them"
        )

    expected_files: set[Path] = set()
    for record in records:
        if record.status not in HELD_STATUSES:
            continue
        if record.status == "removed" and not record.path:
            continue  # was never fetched, so there is no file to hold
        if not record.path or not record.content_sha256:
            problems.append(f"{record.url}: {record.status} but path or hash missing")
            continue
        target = inside(snapshot_dir, record.path)
        if target is None:
            problems.append(f"{record.url}: path escapes the snapshot dir: {record.path}")
            continue
        expected_files.add(target)
        if not target.is_file():
            problems.append(f"{record.url}: file missing: {record.path}")
            continue
        data = target.read_bytes()
        if sha256_hex(data) != record.content_sha256:
            problems.append(f"{record.url}: content hash mismatch: {record.path}")
        if record.size != len(data):
            problems.append(f"{record.url}: size mismatch: {record.path}")

    for sub in ("pages", "indexes"):
        folder = snapshot_dir / sub
        if folder.is_dir():
            for found in folder.rglob("*"):
                if found.is_file() and found.resolve() not in expected_files:
                    problems.append(f"file not in manifest: {found.relative_to(snapshot_dir)}")

    pages = [r for r in records if r.kind == "page"]
    if corpus_hash(pages) != manifest.get("corpus_hash"):
        problems.append("corpus_hash does not match the pages in the manifest")
    return problems
