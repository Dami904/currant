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


def refusal_body(prompt_tokens: int) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"content": None, "refusal": "I can't share that."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 0},
    }


def test_a_guard_block_reported_as_a_refusal_is_still_a_guard_block() -> None:
    # Measured 2026-11-18 (results/smoke/20261118T103312Z-serv-features.json): the guard now
    # answers finish "stop", content null, refusal "I can't share that.", zero tokens.
    rig = Rig(lambda _r: httpx.Response(200, json=refusal_body(0)))
    reply = rig.call(guard=True)
    assert reply.guard_blocked is True and reply.finish_reason == "content_filter"
    assert reply.content is None


def test_a_refusal_without_token_counts_is_a_transient_fault_not_a_guard_block() -> None:
    # A block is cached for good, so only a refusal that says it used no tokens counts as one.
    body = refusal_body(0)
    del body["usage"]
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(200, json=body)).call(guard=True)
    assert raised.value.transient is True


def test_a_model_refusal_is_final_not_a_transient_fault() -> None:
    with pytest.raises(ModelError) as raised:
        Rig(lambda _r: httpx.Response(200, json=refusal_body(120))).call()
    assert raised.value.transient is False and "refused" in str(raised.value)


GRAPH = "gr_0123456789abcdef"


def graph_rig(screen_blocks: bool = False) -> Rig:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == GRAPH:
            return httpx.Response(200, json=ok_body('{"relation": "unrelated"}'))
        if screen_blocks:
            return httpx.Response(200, json=refusal_body(0))
        return httpx.Response(200, json=ok_body("{}"))

    rig = Rig(handler)
    rig.client.model = GRAPH
    return rig


def test_a_graph_gets_its_input_as_the_first_system_message() -> None:
    # Measured 2026-11-18: a console graph (`gr_…` as the model) takes its input from the first
    # system message and keeps its own prompt; a user message alone is refused.
    rig = graph_rig()
    reply = rig.call()
    body = rig.body()
    assert body["model"] == GRAPH and body["messages"] == [
        {"role": "system", "content": "user text"}
    ]
    assert body["response_format"]["type"] == "json_schema" and "tools" not in body
    assert reply.content == '{"relation": "unrelated"}'


def test_a_graph_sees_crawled_text_only_after_the_guard_passed_it() -> None:
    # Measured 2026-11-18: serv_prompt_guard does not run inside a graph, so a separate guarded
    # call on the same text screens it first.
    rig = graph_rig()
    rig.call(guard=True)
    screen, graph = (json.loads(r.content) for r in rig.requests)
    assert screen["model"] != GRAPH and screen["tools"] == [GUARD_TOOL]
    assert screen["messages"][-1]["content"] == "user text"
    assert graph["model"] == GRAPH


def test_a_graph_never_sees_text_the_guard_blocked() -> None:
    rig = graph_rig(screen_blocks=True)
    reply = rig.call(guard=True)
    assert reply.guard_blocked is True
    assert [json.loads(r.content)["model"] for r in rig.requests] != [] and all(
        json.loads(r.content)["model"] != GRAPH for r in rig.requests
    )


def test_a_graph_reply_counts_the_screening_call_and_keeps_both_request_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        graph = json.loads(request.content)["model"] == GRAPH
        return httpx.Response(
            200,
            json=ok_body('{"relation": "unrelated"}' if graph else "ok"),
            headers={"x-openserv-request-id": "graph-id" if graph else "screen-id"},
        )

    rig = Rig(handler)
    rig.client.model = GRAPH
    reply = rig.call(guard=True)
    assert (reply.prompt_tokens, reply.completion_tokens) == (200, 40)  # 100/20 each, summed
    assert (reply.request_id, reply.screen_request_id) == ("graph-id", "screen-id")


def test_a_failed_screening_call_says_so_and_keeps_its_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"x-openserv-request-id": "screen-id"})

    rig = Rig(handler)
    rig.client.model = GRAPH
    with pytest.raises(ModelError) as raised:
        rig.call(guard=True)
    error = raised.value
    assert error.transient and error.request_id == "screen-id"
    assert str(error).startswith("screening call:")
    assert len(rig.requests) == 1  # the graph was never called


def test_a_graph_failure_after_a_passed_screen_names_the_screening_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == GRAPH:
            return httpx.Response(502, headers={"x-openserv-request-id": "graph-id"})
        return httpx.Response(200, json=ok_body("ok"), headers={"x-openserv-request-id": "s-id"})

    rig = Rig(handler)
    rig.client.model = GRAPH
    with pytest.raises(ModelError) as raised:
        rig.call(guard=True)
    assert raised.value.request_id == "graph-id" and "screen s-id passed" in str(raised.value)


@pytest.mark.parametrize(
    ("status", "transient"),
    [(502, True), (404, False)],  # measured: "Graph run failed. Please retry." / "Graph not found."
)
def test_a_graph_failure_is_retried_only_when_it_may_succeed(status: int, transient: bool) -> None:
    rig = Rig(lambda _r: httpx.Response(status, json={"error": {"message": "graph"}}))
    rig.client.model = GRAPH
    with pytest.raises(ModelError) as raised:
        rig.call()
    assert raised.value.transient is transient


def test_a_graph_client_refuses_a_prompt_other_than_the_one_it_started_with() -> None:
    # A graph holds its own prompt; sending another step's prompt would get relate-shaped JSON
    # back with no error, so the client refuses to mix prompts.
    rig = graph_rig()
    rig.call()
    with pytest.raises(ModelError, match="different prompt") as raised:
        rig.client.complete(
            "another prompt", "user text", schema=SCHEMA, schema_name="s", guard=False
        )
    assert raised.value.transient is False


def test_a_graph_cache_tag_names_the_screening_setup_and_a_plain_one_is_the_model() -> None:
    rig = graph_rig()
    assert rig.client.cache_tag.startswith(GRAPH + "|screen:") and rig.client.cache_tag != GRAPH
    assert Rig().client.cache_tag == "gpt-6-luna"


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
