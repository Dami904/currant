"""Load and validate `corpora.toml`."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from currant.crawl.urls import canonicalize, is_allowed

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Corpus:
    name: str
    enabled: bool
    indexes: tuple[str, ...]
    allow: tuple[str, ...]
    pages: tuple[str, ...]
    max_pages: int


def _urls(raw: object, field: str, corpus: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"corpus {corpus!r}: {field} must be a list of strings")
    try:
        return tuple(canonicalize(item) for item in raw)
    except ValueError as exc:
        raise ConfigError(f"corpus {corpus!r}: {field}: {exc}") from exc


def parse_config(text: str) -> list[Corpus]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    raw_corpora = data.get("corpus")
    if not isinstance(raw_corpora, list) or not raw_corpora:
        raise ConfigError("no [[corpus]] tables found")

    corpora: list[Corpus] = []
    seen: set[str] = set()
    for raw in raw_corpora:
        name = raw.get("name")
        # The name becomes a directory name, so it must not be able to traverse paths.
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ConfigError(f"corpus name {name!r} must match {_NAME.pattern}")
        if name in seen:
            raise ConfigError(f"duplicate corpus name {name!r}")
        seen.add(name)

        indexes = _urls(raw.get("indexes", []), "indexes", name)
        allow = _urls(raw.get("allow", []), "allow", name)
        pages = _urls(raw.get("pages", []), "pages", name)
        if not allow:
            raise ConfigError(f"corpus {name!r}: allow must not be empty")
        for url in (*indexes, *pages):
            if not is_allowed(url, allow):
                raise ConfigError(f"corpus {name!r}: {url} is outside its allow list")
        max_pages = raw.get("max_pages", 500)
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
            raise ConfigError(f"corpus {name!r}: max_pages must be a positive integer")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"corpus {name!r}: enabled must be true or false")
        corpora.append(Corpus(name, enabled, indexes, allow, pages, max_pages))
    return corpora


def load_config(path: Path) -> list[Corpus]:
    return parse_config(path.read_text(encoding="utf-8"))
