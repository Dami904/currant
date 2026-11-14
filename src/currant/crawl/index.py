"""Extract page URLs from an llms.txt-style index.

The index is untrusted text: we only pull URLs out of it. Nothing in it is ever treated as an
instruction, and the caller filters every URL through the allow-list.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from currant.crawl.urls import canonicalize

_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_BARE_URL_LINE = re.compile(r"^\s*(?:[-*]\s+)?(https?://\S+)\s*$")


def parse_index(text: str, base_url: str) -> list[str]:
    """Return canonical absolute URLs in order of first appearance, de-duplicated."""
    candidates: list[str] = []
    for line in text.splitlines():
        candidates.extend(_MD_LINK.findall(line))
        bare = _BARE_URL_LINE.match(line)
        if bare:
            candidates.append(bare.group(1))

    seen: set[str] = set()
    urls: list[str] = []
    for candidate in candidates:
        if candidate.startswith("#"):
            continue  # an in-page anchor would otherwise resolve to the index itself
        try:
            url = canonicalize(urljoin(base_url, candidate))
        except ValueError:
            continue  # mailto:, javascript:, bare fragments, and similar
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
