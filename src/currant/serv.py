"""SERV Reasoning chat client: the one module that knows SERV's wire format.

It never builds its own HTTP client (the guardrails allow that only in the CLI and `live_*`
scripts); the caller passes one in. It never logs or stores the API key, and its error messages
carry only the status and a short body excerpt.

Behaviour measured on 2026-11-05 (see docs/API_NOTES.md):

* a system prompt is required on every request;
* `gpt-6-luna` rejects `max_tokens`; the parameter is `max_completion_tokens`;
* a guard block is HTTP 200 with `finish_reason == "content_filter"` and zero tokens, so a 200
  is not an answer until `finish_reason` has been checked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from currant.config import Secret

SERV_BASE = "https://inference-api.openserv.ai/v1"
DEFAULT_MODEL = "gpt-6-luna"
PRICE_PER_M_INPUT = 0.13  # USD per million tokens, SERV models page, 2026-11-05
PRICE_PER_M_OUTPUT = 0.65
GUARD_TOOL = {"type": "function", "function": {"name": "serv_prompt_guard"}}
CONTENT_FILTER = "content_filter"


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
        not a 200; a 200 that the guard blocked is returned, not raised."""
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
