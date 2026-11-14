from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterable, Iterator

import httpx
import pytest

from currant.crawl.fetch import Fetcher, Outcome
from currant.obs import JsonLogger
from tests.helpers import Handler, fixed_now, make_client, md

ALLOW = ("https://docs.example.com/",)
PAGE = "https://docs.example.com/page.md"


class RawBody(httpx.SyncByteStream):
    """Bytes served exactly as given, with no decoding until the client reads them."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __iter__(self) -> Iterator[bytes]:
        yield self._data


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Rig:
    """A Fetcher wired to a scripted transport, recording requests, sleeps and log lines."""

    def __init__(
        self,
        handler: Handler,
        *,
        max_attempts: int = 4,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        deadline_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.requested: list[str] = []
        self.sleeps: list[float] = []
        self.log_out = io.StringIO()

        def recording(request: httpx.Request) -> httpx.Response:
            self.requested.append(str(request.url))
            return handler(request)

        self.fetcher = Fetcher(
            make_client(recording),
            ALLOW,
            logger=JsonLogger(run_id="t", stream=self.log_out, now=fixed_now),
            sleep=self.sleeps.append,
            now=fixed_now,
            max_attempts=max_attempts,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            deadline_seconds=deadline_seconds,
            clock=clock,
        )


def sequence(*responses: httpx.Response | Exception) -> Handler:
    """Answer successive requests from `responses`; the last one repeats forever."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def test_fetched_returns_bytes_and_headers() -> None:
    reply = httpx.Response(
        200,
        content=b"# Hello\n",
        headers={"content-type": "text/markdown; charset=utf-8", "etag": '"abc"'},
    )
    rig = Rig(sequence(reply))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert result.body == b"# Hello\n"
    assert result.attempts == 1
    assert result.http_status == 200
    assert result.etag == '"abc"'
    assert result.fetched_at == fixed_now().isoformat()
    assert rig.sleeps == []


def test_404_is_not_found_and_not_retried() -> None:
    rig = Rig(sequence(httpx.Response(404)))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.NOT_FOUND
    assert len(rig.requested) == 1


def test_other_4xx_is_failed_and_not_retried() -> None:
    rig = Rig(sequence(httpx.Response(403)))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FAILED
    assert result.error == "http_403"
    assert len(rig.requested) == 1


def test_5xx_then_success_retries_with_backoff() -> None:
    rig = Rig(sequence(httpx.Response(500), md("ok")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert result.attempts == 2
    assert rig.sleeps == [1.0]


def test_persistent_5xx_is_unknown_not_failed() -> None:
    rig = Rig(sequence(httpx.Response(503)), max_attempts=4)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.UNKNOWN
    assert result.attempts == 4
    assert len(rig.requested) == 4
    assert rig.sleeps == [1.0, 2.0, 4.0]  # exponential, and no sleep after the last attempt
    assert "fetch_unknown" in rig.log_out.getvalue()


def test_429_honours_retry_after() -> None:
    rig = Rig(sequence(httpx.Response(429, headers={"retry-after": "7"}), md("ok")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert rig.sleeps == [7.0]


def test_retry_after_is_capped() -> None:
    rig = Rig(sequence(httpx.Response(429, headers={"retry-after": "86400"}), md("ok")))
    rig.fetcher.fetch(PAGE)
    assert rig.sleeps == [60.0]


def test_timeouts_end_unknown_and_record_the_error() -> None:
    request = httpx.Request("GET", PAGE)
    rig = Rig(sequence(httpx.ConnectTimeout("slow", request=request)), max_attempts=3)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.UNKNOWN
    assert result.attempts == 3
    assert result.error is not None and "ConnectTimeout" in result.error
    assert rig.log_out.getvalue().count("fetch_transport_error") == 3


def test_transport_error_then_success() -> None:
    request = httpx.Request("GET", PAGE)
    rig = Rig(sequence(httpx.ConnectError("reset", request=request), md("ok")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert result.attempts == 2


def test_redirect_inside_allow_list_is_followed() -> None:
    target = "https://docs.example.com/new.md"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == PAGE:
            return httpx.Response(301, headers={"location": "/new.md"})
        return md("moved")

    rig = Rig(handler)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert result.final_url == target
    assert result.body == b"moved"


def test_redirect_outside_allow_list_is_blocked_and_never_requested() -> None:
    evil = "https://evil.example.org/steal.md"
    rig = Rig(sequence(httpx.Response(302, headers={"location": evil}), md("should not happen")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.BLOCKED
    assert rig.requested == [PAGE]  # the guard: the off-list hop is never sent
    assert "fetch_blocked" in rig.log_out.getvalue()


def test_redirect_loop_fails() -> None:
    rig = Rig(sequence(httpx.Response(302, headers={"location": PAGE})), max_redirects=3)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FAILED
    assert result.error is not None and "redirects" in result.error


def test_redirect_without_location_fails() -> None:
    rig = Rig(sequence(httpx.Response(302)))
    assert rig.fetcher.fetch(PAGE).outcome is Outcome.FAILED


def test_url_outside_allow_list_is_blocked_without_a_request() -> None:
    rig = Rig(sequence(md("nope")))
    assert rig.fetcher.fetch("https://evil.example.org/x.md").outcome is Outcome.BLOCKED
    assert rig.fetcher.fetch("mailto:a@b.c").outcome is Outcome.BLOCKED
    assert rig.requested == []


@pytest.mark.parametrize(
    "content_type", ["text/html", "text/html; charset=utf-8", "application/json"]
)
def test_non_markdown_content_types_fail(content_type: str) -> None:
    reply = httpx.Response(200, content=b"<html>", headers={"content-type": content_type})
    result = Rig(sequence(reply)).fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FAILED
    assert result.body is None
    assert result.error is not None and "content-type" in result.error


@pytest.mark.parametrize("content_type", ["text/plain", "text/markdown", "application/markdown"])
def test_text_content_types_are_accepted(content_type: str) -> None:
    reply = httpx.Response(200, content=b"x", headers={"content-type": content_type})
    assert Rig(sequence(reply)).fetcher.fetch(PAGE).outcome is Outcome.FETCHED


def test_missing_content_type_is_accepted() -> None:
    reply = httpx.Response(200, content=b"x")
    reply.headers.pop("content-type", None)
    assert Rig(sequence(reply)).fetcher.fetch(PAGE).outcome is Outcome.FETCHED


def test_oversize_by_declared_length_fails() -> None:
    big = httpx.Response(200, content=b"x" * 2000, headers={"content-type": "text/plain"})
    result = Rig(sequence(big), max_bytes=1000).fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FAILED
    assert result.error is not None and "too large" in result.error


def test_oversize_while_streaming_fails() -> None:
    def chunks() -> Iterable[bytes]:
        for _ in range(5):
            yield b"x" * 600

    big = httpx.Response(200, content=chunks(), headers={"content-type": "text/plain"})
    assert "content-length" not in big.headers  # forces the streaming cap, not the header check
    result = Rig(sequence(big), max_bytes=1000).fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FAILED
    assert result.error is not None and "over 1000 bytes" in result.error


def test_408_is_retried_like_a_timeout() -> None:
    rig = Rig(sequence(httpx.Response(408), md("ok")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.FETCHED
    assert result.attempts == 2


def test_redirect_to_a_non_http_target_is_blocked_and_never_followed() -> None:
    rig = Rig(sequence(httpx.Response(302, headers={"location": "ftp://x/y"}), md("no")))
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.BLOCKED
    assert rig.requested == [PAGE]


def test_xhtml_is_rejected_like_html() -> None:
    reply = httpx.Response(
        200, content=b"<html/>", headers={"content-type": "application/xhtml+xml"}
    )
    assert Rig(sequence(reply)).fetcher.fetch(PAGE).outcome is Outcome.FAILED


def test_corrupt_content_encoding_is_unknown_not_a_crash() -> None:
    # A CDN truncating or corrupting a gzip body is transient: record UNKNOWN and keep going.
    # Built from a raw stream: `content=` would decode (and fail) while constructing the response.
    def corrupt(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=RawBody(b"definitely not gzip"),
            headers={"content-encoding": "gzip", "content-type": "text/markdown"},
        )

    rig = Rig(corrupt, max_attempts=2)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.UNKNOWN
    assert result.error is not None and "DecodingError" in result.error
    assert len(rig.requested) == 2
    assert "fetch_transport_error" in rig.log_out.getvalue()


def test_a_slow_body_hits_the_total_deadline() -> None:
    clock = Clock()

    def drip() -> Iterable[bytes]:
        for _ in range(5):
            clock.now += 50  # each chunk arrives inside the per-read timeout
            yield b"x" * 10

    slow = httpx.Response(200, content=drip(), headers={"content-type": "text/plain"})
    rig = Rig(sequence(slow), clock=clock, deadline_seconds=120)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.UNKNOWN
    assert result.error is not None and "deadline exceeded" in result.error
    assert len(rig.requested) == 1  # no retry once the budget is gone
    assert rig.sleeps == []
    assert "fetch_deadline" in rig.log_out.getvalue()


def test_the_deadline_is_also_checked_before_sleeping_for_a_retry() -> None:
    clock = Clock()

    def slow_503(_request: httpx.Request) -> httpx.Response:
        clock.now += 500
        return httpx.Response(503)

    rig = Rig(slow_503, clock=clock, deadline_seconds=120)
    result = rig.fetcher.fetch(PAGE)
    assert result.outcome is Outcome.UNKNOWN
    assert result.attempts == 1
    assert result.error is not None and "deadline exceeded" in result.error
    assert rig.sleeps == []


def test_zero_attempts_is_rejected_up_front() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        Rig(sequence(md("x")), max_attempts=0)
