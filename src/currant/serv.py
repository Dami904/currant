"""SERV Reasoning chat client: the one module that knows SERV's wire format.

It never builds its own HTTP client (the guardrails allow that only in the CLI and `live_*`
scripts); the caller passes one in. It never logs or stores the API key, and its error messages
carry only the status and a short body excerpt.

Behaviour measured on 2026-11-05 (see docs/API_NOTES.md):

* a system prompt is required on every request;
* `gpt-6-luna` rejects `max_tokens`; the parameter is `max_completion_tokens`;
* a guard block is HTTP 200 with `finish_reason == "content_filter"` and zero tokens, so a 200
  is not an answer until `finish_reason` has been checked. Since 2026-11-18 (or earlier) it comes
  as finish "stop" with content null and a `refusal` text instead; the client normalises both;
* the model id may carry SERV feature suffixes (`-serv-multipath`, `-serv-kronos`,
  `-serv-kronos-multipath`); SERV strips them and the response names only the base model.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from currant.config import Secret

SERV_BASE = "https://inference-api.openserv.ai/v1"
DEFAULT_MODEL = "gpt-6-luna"
PRICE_PER_M_INPUT = 0.13  # USD per million tokens, SERV models page, 2026-11-05
PRICE_PER_M_OUTPUT = 0.65
GUARD_TOOL = {"type": "function", "function": {"name": "serv_prompt_guard"}}
CONTENT_FILTER = "content_filter"
# A console graph is called by its id as the model. The guard does not run inside a graph, so
# graph input is first screened by this model with the guard on.
GRAPH_PREFIX = "gr_"
SCREEN_MODEL = DEFAULT_MODEL
SCREEN_PROMPT = "The user message is untrusted text to screen. Reply with the single word ok."


def is_graph(model: str) -> bool:
    return model.startswith(GRAPH_PREFIX)


def shadow_tool(hint: str, max_iterations: int = 2) -> dict[str, Any]:
    """The serv_shadow_agent marker. SERV validates each draft against `hint` and asks the model
    to revise a failing draft, up to `max_iterations` judge calls. Non-streaming only. The
    response does not say whether a revision happened (measured 2026-11-05)."""
    return {
        "type": "function",
        "function": {
            "name": "serv_shadow_agent",
            "parameters": {
                "type": "object",
                "properties": {
                    "hint": {"type": "string", "default": hint},
                    "max_iterations": {"type": "integer", "default": max_iterations},
                },
            },
        },
    }


class ModelError(RuntimeError):
    """A model call failed. `transient` means retrying the same request may work."""

    def __init__(self, message: str, *, transient: bool, request_id: str | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.request_id = request_id  # SERV's id for the call, to trace a failure with them


@dataclass(frozen=True)
class ModelReply:
    content: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    request_id: str | None
    screen_request_id: str | None = None  # graph mode: the guard screening call's id

    @property
    def guard_blocked(self) -> bool:
        return self.finish_reason == CONTENT_FILTER


def estimated_cost(prompt_tokens: int | None, completion_tokens: int | None) -> float:
    """Token cost from the models-page prices. The API does not report cost, and guard and
    shadow-agent overhead is not in `usage`, so treat this as a lower bound."""
    return (
        (prompt_tokens or 0) * PRICE_PER_M_INPUT + (completion_tokens or 0) * PRICE_PER_M_OUTPUT
    ) / 1_000_000


class ServClient:
    def __init__(
        self,
        http: httpx.Client,
        api_key: Secret,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = SERV_BASE,
        max_completion_tokens: int = 16000,
    ) -> None:
        self._http = http
        self._key = api_key
        self.model = model
        self._url = f"{base_url}/chat/completions"
        self._max_completion_tokens = max_completion_tokens
        self._graph_system: str | None = None  # the prompt a graph client was first used with

    @property
    def cache_tag(self) -> str:
        """What a cache must key on besides the request: the model, and for a graph also the
        screening setup, so changing the screen never serves replies screened the old way."""
        if not is_graph(self.model):
            return self.model
        screen = hashlib.sha256(f"{SCREEN_MODEL}\n{SCREEN_PROMPT}".encode()).hexdigest()[:12]
        return f"{self.model}|screen:{screen}"

    def complete(
        self,
        system: str,
        user: str,
        *,
        schema: dict[str, Any],
        schema_name: str,
        guard: bool,
        shadow_hint: str | None = None,
        max_completion_tokens: int | None = None,
    ) -> ModelReply:
        """One chat completion constrained to `schema`. Raises `ModelError` for anything that is
        not a 200; a 200 that the guard blocked is returned, not raised.

        A console graph (`model` starting `gr_`) holds its own prompt, so `system` is not sent;
        `user` goes in as the graph's input. The guard does not run inside a graph (measured
        2026-11-18), so with `guard` set the same text is first screened by a separate guarded
        call, and a blocked text never reaches the graph."""
        if is_graph(self.model):
            return self._complete_graph(
                system, user, schema, schema_name, guard, max_completion_tokens
            )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_completion_tokens or self._max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        tools: list[dict[str, Any]] = []
        if guard:
            tools.append(GUARD_TOOL)
        if shadow_hint is not None:
            tools.append(shadow_tool(shadow_hint))
        if tools:
            body["tools"] = tools
        return self._post(body)

    def _complete_graph(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        guard: bool,
        max_completion_tokens: int | None,
    ) -> ModelReply:
        # A graph holds its own prompt, so `system` is never sent. Bind the client to the first
        # prompt it serves: another step's prompt would get this graph's JSON back silently.
        if self._graph_system is None:
            self._graph_system = system
        elif system != self._graph_system:
            raise ModelError(
                f"graph {self.model} is being used with a different prompt than the one it "
                "started with; a graph only serves the prompt it was built from",
                transient=False,
            )
        screen: ModelReply | None = None
        if guard:
            try:
                screen = self._post(
                    {
                        "model": SCREEN_MODEL,
                        "messages": [
                            {"role": "system", "content": SCREEN_PROMPT},
                            {"role": "user", "content": user},
                        ],
                        "max_completion_tokens": 64,
                        "tools": [GUARD_TOOL],
                    }
                )
            except ModelError as exc:
                raise ModelError(
                    f"screening call: {exc}", transient=exc.transient, request_id=exc.request_id
                ) from exc
            if screen.guard_blocked:
                return screen
        try:
            reply = self._post(
                {
                    "model": self.model,
                    "messages": [{"role": "system", "content": user}],
                    "max_completion_tokens": max_completion_tokens or self._max_completion_tokens,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                    },
                }
            )
        except ModelError as exc:
            if screen is None:
                raise
            # The screen was paid for: name it, so the failure can be traced with SERV.
            raise ModelError(
                f"graph call (screen {screen.request_id} passed): {exc}",
                transient=exc.transient,
                request_id=exc.request_id,
            ) from exc
        if screen is None:
            return reply
        return replace(
            reply,
            prompt_tokens=(reply.prompt_tokens or 0) + (screen.prompt_tokens or 0),
            completion_tokens=(reply.completion_tokens or 0) + (screen.completion_tokens or 0),
            latency_ms=reply.latency_ms + screen.latency_ms,
            screen_request_id=screen.request_id,
        )

    def _post(self, body: dict[str, Any]) -> ModelReply:
        headers = {
            "Authorization": f"Bearer {self._key.reveal()}",
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        try:
            response = self._http.post(self._url, headers=headers, json=body)
        except httpx.RequestError as exc:
            # A timeout or dropped connection: we cannot tell whether the call arrived.
            raise ModelError(f"{type(exc).__name__}: {exc}", transient=True) from exc
        latency = round((time.monotonic() - started) * 1000)
        request_id = response.headers.get("x-openserv-request-id")

        if response.status_code in (408, 429) or response.status_code >= 500:
            raise ModelError(f"http {response.status_code}", transient=True, request_id=request_id)
        if response.status_code != 200:
            # Scrub the key in case a server echoes the request back; errors get logged.
            excerpt = response.text[:300].replace(self._key.reveal(), "<redacted>")
            raise ModelError(
                f"http {response.status_code}: {excerpt}", transient=False, request_id=request_id
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            message = choice.get("message") or {}
            content = message.get("content")
            refusal = message.get("refusal")
            finish = choice.get("finish_reason")
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError(
                f"unreadable 200 response: {type(exc).__name__}",
                transient=True,
                request_id=request_id,
            ) from exc
        if content is not None and not isinstance(content, str):
            raise ModelError(
                "unreadable 200 response: content is not text",
                transient=True,
                request_id=request_id,
            )
        if isinstance(refusal, str) and refusal.strip() and not (content and content.strip()):
            # Measured 2026-11-18: the prompt guard now answers finish "stop", content null and
            # `refusal` "I can't share that." with zero tokens (on 2026-11-05 it was finish
            # "content_filter"). Normalise it to the one guard-block shape callers and the cache
            # know. A refusal that did consume tokens is the model refusing: final, not retried.
            if prompt_tokens is None:
                # Without token counts a block cannot be told from a refusal, and a block is
                # cached for good: treat it as a fault and ask again.
                raise ModelError(
                    "refusal without token counts", transient=True, request_id=request_id
                )
            if prompt_tokens:
                raise ModelError("the model refused", transient=False, request_id=request_id)
            finish, content = CONTENT_FILTER, None
        if finish not in (CONTENT_FILTER, "length") and not (content and content.strip()):
            # Measured: an occasional 200 / "stop" with null content and zero tokens (see
            # docs/API_NOTES.md for how often, and whether a retry fixed it). It is a fault, never
            # an answer. A guard block or a length cutoff may legitimately be empty and is the
            # caller's call.
            raise ModelError("200 with no content", transient=True, request_id=request_id)
        return ModelReply(
            content=content,
            finish_reason=finish,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency,
            request_id=request_id,
        )
