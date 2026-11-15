"""The proxy's own gate: an optional access token and a per-client rate limit on chat calls.
Each test fails if its guard is removed."""

from __future__ import annotations

import json

import pytest

from currant.config import PROXY_TOKEN_NAME, proxy_token
from currant.proxy import Reply
from currant.proxy_http import RateLimiter, admit

TOKEN = "t0ken-for-tests"


def status(reply: Reply | None) -> int | None:
    return None if reply is None else reply.status


def test_with_no_token_configured_everything_is_admitted() -> None:
    limiter = RateLimiter(per_minute=100)
    for path in ("/receipts", "/receipts/abc", "/v1/chat/completions", "/"):
        assert admit("GET", path, None, "1.2.3.4", token=None, limiter=limiter, now=0.0) is None


@pytest.mark.parametrize("path", ["/receipts", "/receipts/abc/context", "/v1/chat/completions"])
@pytest.mark.parametrize("given", [None, "", "wrong", TOKEN + "x", TOKEN[:-1]])
def test_with_a_token_configured_data_routes_deny_by_default(path: str, given: str | None) -> None:
    method = "POST" if path.startswith("/v1") else "GET"
    reply = admit(method, path, given, "1.2.3.4", token=TOKEN, limiter=None, now=0.0)
    assert status(reply) == 401
    assert reply is not None and TOKEN not in reply.body.decode("utf-8")


def test_the_right_token_is_admitted_and_static_files_and_health_stay_open() -> None:
    assert admit("GET", "/receipts", TOKEN, "c", token=TOKEN, limiter=None, now=0.0) is None
    for path in ("/healthz", "/", "/viewer.js", "/viewer.css"):
        assert admit("GET", path, None, "c", token=TOKEN, limiter=None, now=0.0) is None


def test_chat_calls_are_rate_limited_per_client_and_the_window_refills() -> None:
    limiter = RateLimiter(per_minute=3)
    chat = "/v1/chat/completions"
    for _ in range(3):
        assert admit("POST", chat, None, "a", token=None, limiter=limiter, now=10.0) is None
    refused = admit("POST", chat, None, "a", token=None, limiter=limiter, now=10.0)
    assert status(refused) == 429 and refused is not None
    assert refused.headers.get("Retry-After") == "60"
    assert json.loads(refused.body)["error"]["type"] == "rate_limited"
    # Another client has its own budget; reads are never limited.
    assert admit("POST", chat, None, "b", token=None, limiter=limiter, now=10.0) is None
    assert admit("GET", "/receipts", None, "a", token=None, limiter=limiter, now=10.0) is None
    # A minute later the budget is back.
    assert admit("POST", chat, None, "a", token=None, limiter=limiter, now=70.5) is None


def test_a_refused_token_does_not_spend_the_rate_budget() -> None:
    limiter = RateLimiter(per_minute=1)
    chat = "/v1/chat/completions"
    assert status(admit("POST", chat, "bad", "a", token=TOKEN, limiter=limiter, now=0.0)) == 401
    assert admit("POST", chat, TOKEN, "a", token=TOKEN, limiter=limiter, now=0.0) is None


def test_a_server_on_a_non_loopback_host_refuses_to_start_without_a_token() -> None:
    from typing import cast

    from currant.proxy import GroundingProxy
    from currant.proxy_http import make_server

    never_used = cast(GroundingProxy, object())  # the check runs before the proxy is touched
    with pytest.raises(ValueError, match="needs a proxy token"):
        make_server(never_used, "0.0.0.0", 0)


def test_the_token_comes_only_from_its_environment_variable() -> None:
    assert proxy_token(env={}, dotenv_path=None) is None
    assert proxy_token(env={PROXY_TOKEN_NAME: ""}, dotenv_path=None) is None
    secret = proxy_token(env={PROXY_TOKEN_NAME: TOKEN}, dotenv_path=None)
    assert secret is not None and secret.reveal() == TOKEN and TOKEN not in repr(secret)
