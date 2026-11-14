from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from currant.llmcache import CachingModel, cache_key
from currant.serv import ModelError, ModelReply

SCHEMA: dict[str, Any] = {"type": "object"}


class Counting:
    model = "inner-model"

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

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
        self.calls += 1
        if self.fail:
            raise ModelError("http 503", transient=True)
        return ModelReply(f"answer {self.calls}", "stop", 10, 5, 7, f"req-{self.calls}")


def ask(model: CachingModel, **overrides: Any) -> ModelReply:
    args: dict[str, Any] = {
        "system": "sys", "user": "usr", "schema": SCHEMA, "schema_name": "s",
        "guard": True, "shadow_hint": None, "max_completion_tokens": None,
    }  # fmt: skip
    args.update(overrides)
    return model.complete(args.pop("system"), args.pop("user"), **args)


def test_a_repeated_request_is_served_from_the_cache(tmp_path: Path) -> None:
    inner = Counting()
    with CachingModel(inner, tmp_path / "c.db") as model:
        first, second = ask(model), ask(model)
        assert first == second and first.content == "answer 1"
        assert (inner.calls, model.hits, model.misses) == (1, 1, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"system": "other system"},
        {"user": "other user"},
        {"schema": {"type": "array"}},
        {"schema_name": "other"},
        {"guard": False},
        {"shadow_hint": "hint"},
        {"max_completion_tokens": 48000},
    ],
)
def test_anything_that_can_change_the_answer_changes_the_key(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    inner = Counting()
    with CachingModel(inner, tmp_path / "c.db") as model:
        ask(model)
        ask(model, **change)
        assert inner.calls == 2  # a changed prompt never gets a stale answer


def test_the_model_name_is_part_of_the_key() -> None:
    base = ("sys", "usr", SCHEMA, "s", True, None, None)
    assert cache_key("model-a", *base) != cache_key("model-b", *base)
    assert cache_key("model-a", *base) == cache_key("model-a", *base)


def test_the_cache_persists_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    with CachingModel(Counting(), path) as model:
        ask(model)
    inner = Counting()
    with CachingModel(inner, path) as again:
        reply = ask(again)
    assert reply.content == "answer 1" and inner.calls == 0  # served from disk, no new call


def test_an_error_is_never_cached(tmp_path: Path) -> None:
    inner = Counting()
    inner.fail = True
    with CachingModel(inner, tmp_path / "c.db") as model:
        with pytest.raises(ModelError):
            ask(model)
        inner.fail = False
        assert ask(model).content == "answer 2"  # the failure left nothing behind
        assert inner.calls == 2


def test_a_guard_block_is_cached_like_any_other_reply(tmp_path: Path) -> None:
    class Blocking(Counting):
        def complete(self, *args: Any, **kwargs: Any) -> ModelReply:
            self.calls += 1
            return ModelReply("I can't share that.", "content_filter", 0, 0, 3, "r")

    inner = Blocking()
    with CachingModel(inner, tmp_path / "c.db") as model:
        assert ask(model).guard_blocked and ask(model).guard_blocked
        assert inner.calls == 1  # not retried against the live guard


def test_the_cache_never_stores_a_secret(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    with CachingModel(Counting(), path) as model:
        ask(model)
    data = path.read_bytes().lower()
    assert b"authorization" not in data and b"bearer" not in data
