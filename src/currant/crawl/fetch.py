"""HTTP fetching with explicit outcomes.

Every fetch ends in exactly one `Outcome`:

* FETCHED    positive proof: we hold the bytes of a 200 response.
* NOT_FOUND  positive proof the page is gone (404 / 410). Dead links are data, not noise.
* FAILED     positive proof the page is unusable (other 4xx, HTML instead of markdown, too big).
* BLOCKED    refused by the allow-list (the request was never sent, or a redirect left the list).
* UNKNOWN    timeouts, dropped connections and 5xx/429 that survived every retry. Not the same
             as FAILED: it is recorded and retried on the next run, never silently discarded.

Retries are safe here because every request is a read-only GET.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urljoin

import httpx

from currant.crawl.urls import canonicalize, is_allowed
from currant.obs import JsonLogger, utc_now

_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUS = frozenset({408, 429})
_MARKDOWN_TYPES = frozenset({"application/markdown", "application/x-markdown"})
MAX_BACKOFF_SECONDS = 60.0
DEFAULT_DEADLINE_SECONDS = 120.0


class Outcome(StrEnum):
    FETCHED = "fetched"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FetchResult:
    url: str
    outcome: Outcome
    attempts: int
    fetched_at: str
    final_url: str | None = None
    http_status: int | None = None
    body: bytes | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


class _Terminal(Exception):
    """Internal control flow: this request has a final, non-retryable answer."""

    def __init__(self, outcome: Outcome, error: str, status: int | None = None) -> None:
        super().__init__(error)
        self.outcome = outcome
        self.error = error
        self.status = status


class _DeadlineExceeded(Exception):
    """Internal control flow: the total time budget for this URL is spent."""


@dataclass(frozen=True)
class _Reply:
    status: int
    final_url: str
    headers: httpx.Headers
    body: bytes


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if raw is None or not raw.strip().isdigit():
        return None  # HTTP-date form is ignored; we fall back to exponential backoff
    return min(float(raw.strip()), MAX_BACKOFF_SECONDS)


class Fetcher:
    def __init__(
        self,
        client: httpx.Client,
        allow: Iterable[str],
        *,
        logger: JsonLogger,
        max_bytes: int = 2_000_000,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        max_redirects: int = 5,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        self.client = client
        self.allow = tuple(allow)
        self.log = logger
        self.max_bytes = max_bytes
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.max_redirects = max_redirects
        self.deadline_seconds = deadline_seconds
        self._clock = clock
        self._sleep = sleep
        self._now = now

    def fetch(self, url: str) -> FetchResult:
        started = self._now().isoformat()
        try:
            target = canonicalize(url)
        except ValueError as exc:
            self.log.error("fetch_blocked", url=url, error=str(exc))
            return FetchResult(url, Outcome.BLOCKED, 0, started, error=str(exc))
        if not is_allowed(target, self.allow):
            self.log.error("fetch_blocked", url=target, error="outside allow list")
            return FetchResult(target, Outcome.BLOCKED, 0, started, error="outside allow list")

        # The per-read timeout does not bound a slow drip of bytes, so one URL also gets a
        # total budget across every attempt, redirect and backoff.
        deadline = self._clock() + self.deadline_seconds
        last_error = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            retry_after: float | None = None
            try:
                reply = self._get(target, deadline)
            except _Terminal as done:
                return self._terminal(target, done, attempt)
            except _DeadlineExceeded:
                return self._out_of_time(target, attempt)
            # RequestError covers timeouts, connection resets, DecodingError (a corrupt or
            # truncated gzip body) and TooManyRedirects: all transient, so UNKNOWN, not a crash.
            except (httpx.RequestError, httpx.InvalidURL) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.log.warn(
                    "fetch_transport_error", url=target, attempt=attempt, error=last_error
                )
            else:
                result = self._classify(target, reply, attempt)
                if result is not None:
                    return result
                last_error = f"http_{reply.status}"
                retry_after = _retry_after_seconds(reply.headers)
                self.log.warn(
                    "fetch_retryable_status",
                    url=target,
                    attempt=attempt,
                    status=reply.status,
                    retry_after=retry_after,
                )
            if attempt < self.max_attempts:
                wait = self._backoff(attempt, retry_after)
                if self._clock() + wait > deadline:
                    return self._out_of_time(target, attempt)
                self._sleep(wait)

        self.log.error("fetch_unknown", url=target, attempts=self.max_attempts, error=last_error)
        return FetchResult(
            target,
            Outcome.UNKNOWN,
            self.max_attempts,
            self._now().isoformat(),
            error=f"gave up after {self.max_attempts} attempts: {last_error}",
        )

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        return min(self.backoff_base * 2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)

    def _out_of_time(self, url: str, attempt: int) -> FetchResult:
        error = f"deadline exceeded ({self.deadline_seconds:g}s total for this URL)"
        self.log.error("fetch_deadline", url=url, attempt=attempt, error=error)
        return FetchResult(url, Outcome.UNKNOWN, attempt, self._now().isoformat(), error=error)

    def _get(self, url: str, deadline: float) -> _Reply:
        """GET `url`, following redirects by hand so every hop is checked against the
        allow-list. Raises `_Terminal` for answers that must not be retried."""
        current = url
        for _ in range(self.max_redirects + 1):
            if self._clock() > deadline:
                raise _DeadlineExceeded
            with self.client.stream("GET", current, follow_redirects=False) as response:
                status = response.status_code
                if status in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise _Terminal(Outcome.FAILED, "redirect without Location", status)
                    try:
                        hop = canonicalize(urljoin(current, location))
                    except ValueError as exc:
                        raise _Terminal(Outcome.BLOCKED, f"bad redirect target: {exc}") from exc
                    if not is_allowed(hop, self.allow):
                        raise _Terminal(Outcome.BLOCKED, f"redirect outside allow list: {hop}")
                    current = hop
                    continue
                body = self._read_capped(response, deadline) if status == 200 else b""
                return _Reply(status, current, response.headers, body)
        raise _Terminal(Outcome.FAILED, f"more than {self.max_redirects} redirects")

    def _read_capped(self, response: httpx.Response, deadline: float) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            raise _Terminal(Outcome.FAILED, f"response too large ({declared} bytes)", 200)
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise _Terminal(Outcome.FAILED, f"response over {self.max_bytes} bytes", 200)
            if self._clock() > deadline:
                raise _DeadlineExceeded
            chunks.append(chunk)
        return b"".join(chunks)

    def _classify(self, url: str, reply: _Reply, attempt: int) -> FetchResult | None:
        """Turn a reply into a final result, or None if the status is worth retrying."""
        status = reply.status
        when = self._now().isoformat()
        if status == 200:
            content_type = reply.headers.get("content-type", "")
            reason = _content_type_problem(content_type)
            if reason is not None:
                self.log.error("fetch_failed", url=url, status=status, error=reason)
                return FetchResult(
                    url, Outcome.FAILED, attempt, when, reply.final_url, status,
                    content_type=content_type, error=reason,
                )  # fmt: skip
            return FetchResult(
                url, Outcome.FETCHED, attempt, when, reply.final_url, status, reply.body,
                content_type or None, reply.headers.get("etag"), reply.headers.get("last-modified"),
            )  # fmt: skip
        if status in (404, 410):
            self.log.warn("fetch_not_found", url=url, status=status)
            return FetchResult(
                url, Outcome.NOT_FOUND, attempt, when, reply.final_url, status,
                error=f"http_{status}",
            )  # fmt: skip
        if status >= 500 or status in _RETRYABLE_STATUS:
            return None
        self.log.error("fetch_failed", url=url, status=status, error=f"http_{status}")
        return FetchResult(
            url, Outcome.FAILED, attempt, when, reply.final_url, status, error=f"http_{status}"
        )

    def _terminal(self, url: str, done: _Terminal, attempt: int) -> FetchResult:
        self.log.error("fetch_" + done.outcome.value, url=url, status=done.status, error=done.error)
        return FetchResult(
            url, done.outcome, attempt, self._now().isoformat(),
            http_status=done.status, error=done.error,
        )  # fmt: skip


def _content_type_problem(content_type: str) -> str | None:
    """Docs must come back as markdown/plain text; an HTML shell would pollute the corpus."""
    main = content_type.split(";")[0].strip().lower()
    if not main:
        return None  # some servers omit it; the bytes are still hashed and stored as received
    if main in _MARKDOWN_TYPES:
        return None
    if main.startswith("text/") and main != "text/html":
        return None
    return f"unsupported content-type {main!r} (expected markdown or plain text)"
