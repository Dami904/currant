"""URL canonicalisation and the crawl allow-list.

Crawled indexes are untrusted input, so every URL, including every redirect target, must
pass `is_allowed` before it is fetched.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit


def canonicalize(url: str) -> str:
    """Return a stable form of `url`: lowercase scheme and host, default port and fragment
    dropped, userinfo dropped. Raises ValueError for anything that is not http(s)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        raise ValueError(f"not an http(s) URL: {url!r}")
    port = parts.port
    default = 443 if scheme == "https" else 80
    netloc = host if port is None or port == default else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def is_allowed(url: str, allow_prefixes: Iterable[str]) -> bool:
    """True if canonical `url` is covered by one of the (canonicalised) allow entries.

    An entry ending in "/" is a directory prefix. Any other entry names exactly one URL, so
    `https://host/agents.md` does not also allow `agents.md.evil` or `agents.md?x=1`.
    """
    try:
        canonical = canonicalize(url)
    except ValueError:
        return False
    for entry in allow_prefixes:
        prefix = canonicalize(entry)
        if prefix.endswith("/"):
            if canonical.startswith(prefix):
                return True
        elif canonical == prefix:
            return True
    return False
