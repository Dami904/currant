from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from currant.config import Secret
from currant.serv import (
    GUARD_TOOL,
    ModelError,
    ServClient,
    estimated_cost,
    shadow_tool,
)

KEY = "placeholder-key-for-tests"
SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def ok_body(content: str = '{"claims": []}', finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


class Rig:
    def __init__(self, handler: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler or (
            lambda _r: httpx.Response(
                200, json=ok_body(), headers={"x-openserv-request-id": "req-1"}
            )
        )
        http = httpx.Client(transport=httpx.MockTransport(self._record))
        self.client = ServClient(http, Secret("SERV_API_KEY", KEY), model="gpt-6-luna")

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result: httpx.Response = self._handler(request)
        return result

    def body(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.requests[-1].content)
        return loaded

    def call(self, **kwargs: Any) -> Any:
        options: dict[str, Any] = {"schema": SCHEMA, "schema_name": "s", "guard": False}
        options.update(kwargs)
        return self.client.complete("system text", "user text", **options)


def test_the_request_uses_the_parameters_measured_to_work() -> None:
    rig = Rig()
    rig.call()
    body = rig.body()
    assert body["model"] == "gpt-6-luna"
    assert body["messages"][0] == {"role": "system", "content": "system text"}  # required by SERV
    assert body["messages"][1] == {"role": "user", "content": "user text"}
    assert "max_completion_tokens" in body and "max_tokens" not in body  # gpt-6-luna rejects it
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "s", "strict": True, "schema": SCHEMA},
    }
    assert rig.requests[-1].headers["authorization"] == f"Bearer {KEY}"


def test_tools_are_added_only_when_asked() -> None:
    rig = Rig()
    rig.call()
    assert "tools" not in rig.body()
    rig.call(guard=True)
    assert rig.body()["tools"] == [GUARD_TOOL]
    rig.call(shadow_hint="the quote must be exact")
    (tool,) = rig.body()["tools"]
    assert tool == shadow_tool("the quote must be exact")
    assert (
        tool["function"]["parameters"]["properties"]["hint"]["default"] == "the quote must be exact"
    )
    rig.call(guard=True, shadow_hint="h")
    assert [t["function"]["name"] for t in rig.body()["tools"]] == [
        "serv_prompt_guard",
        "serv_shadow_agent",
    ]


def test_a_reply_carries_content_tokens_and_the_request_id() -> None:
    reply = Rig().call()
    assert reply.content == '{"claims": []}'
    assert (reply.finish_reason, reply.prompt_tokens, reply.completion_tokens) == ("stop", 100, 20)
    assert reply.request_id == "req-1"
    assert reply.guard_blocked is False


def test_a_guard_block_is_a_reply_not_an_error() -> None:
    blocked = Rig(
        lambda _r: httpx.Response(200, json=ok_body("I can't share that.", "content_filter"))
    )
    reply = blocked.call(guard=True)
    assert reply.guard_blocked is True and reply.finish_reason == "content_filter"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_statuses_are_transient(status: int) -> None:
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(status)).call()
    assert raised.value.transient is True


def test_a_client_error_is_not_transient_and_keeps_a_body_excerpt() -> None:
    rig = Rig(lambda _r: httpx.Response(400, text="Unsupported parameter: max_tokens"))
    with pytest.raises(ModelError, match="Unsupported parameter") as raised:
        rig.call()
    assert raised.value.transient is False


def test_a_timeout_is_transient_because_the_call_may_have_arrived() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ModelError) as raised:
        Rig(slow).call()
    assert raised.value.transient is True and "ReadTimeout" in str(raised.value)


@pytest.mark.parametrize("content", [None, "", "   " + chr(10)])
def test_a_200_with_no_content_is_a_transient_fault_not_an_answer(content: str | None) -> None:
    # Measured 2026-11-06: gpt-6-luna sometimes answers 200 / finish "stop" with null content and
    # zero tokens. It is an upstream hiccup; the same request succeeds when repeated.
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(200, json=body)).call()
    assert raised.value.transient is True and "no content" in str(raised.value)


def test_empty_content_that_was_cut_off_or_blocked_is_still_returned_for_the_caller() -> None:
    for finish in ("length", "content_filter"):
        body = ok_body("", finish)
        reply = Rig(lambda _r, b=body: httpx.Response(200, json=b)).call()
        assert reply.finish_reason == finish and not reply.content


def test_an_unreadable_200_is_transient() -> None:
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(200, text="<html>gateway</html>")).call()
    assert raised.value.transient is True


def test_the_api_key_never_appears_in_an_error_even_if_the_server_echoes_it() -> None:
    echo = Rig(
        lambda r: httpx.Response(400, text=f"bad request, auth was {r.headers['authorization']}")
    )
    with pytest.raises(ModelError) as raised:
        echo.call()
    assert KEY not in str(raised.value)
    assert KEY not in repr(echo.client)


def test_estimated_cost_uses_the_models_page_prices() -> None:
    assert estimated_cost(1_000_000, 0) == pytest.approx(0.13)
    assert estimated_cost(0, 1_000_000) == pytest.approx(0.65)
    assert estimated_cost(None, None) == 0.0
