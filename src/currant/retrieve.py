"""Retrieval: which pages of a snapshot to show a model for a question.

BM25 ranking over whole pages, using SQLite's built-in FTS5 (no new dependency). This is the
"baseline" of the plan (BM25 top 10) and the input to Ground, which then cuts, annotates or pulls.

The question is untrusted text. It is reduced to plain lowercase word tokens and each is quoted, so
FTS5 operators (`AND`, `NOT`, `NEAR`, `*`, `col:`, quotes) in a question are just words and
can never
change the search or raise a syntax error. A page that does not contain any question term is not
returned. Ties are broken by URL, so the same question always gives the same pages in the same
order. The index is rebuilt in memory per call: the corpus is a few hundred pages.
"""

from __future__ import annotations

import re
import sqlite3

from currant.ground import Retrieved
from currant.store import ClaimStore

MAX_TERMS = 32
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    ]
)
_WORD = re.compile(r"\w+", re.UNICODE)


def query_terms(question: str) -> list[str]:
    """Unique lowercase word tokens of a question, in order, without stopwords, capped."""
    seen: dict[str, None] = {}
    for word in _WORD.findall(question.lower()):
        if word not in STOPWORDS:
            seen[word] = None  # a dict: repeats collapse, order is kept
        if len(seen) == MAX_TERMS:
            break
    return list(seen)


class PageIndex:
    """A BM25 index over the pages of one snapshot, built once and searched many times."""

    def __init__(self, store: ClaimStore, snapshot_id: int) -> None:
        # One row per distinct document (a document served under two URLs is one page), with the
        # smallest URL as its name so the result does not depend on insertion order.
        self._pages = store.conn.execute(
            "SELECT doc_id, MIN(url) AS url FROM snapshot_pages WHERE snapshot_id = ?"
            " GROUP BY doc_id ORDER BY doc_id",
            (snapshot_id,),
        ).fetchall()
        self._index: sqlite3.Connection | None = sqlite3.connect(":memory:")
        self._index.execute(
            "CREATE VIRTUAL TABLE docs USING fts5(text, tokenize = 'porter unicode61')"
        )
        self._index.executemany(
            "INSERT INTO docs (rowid, text) VALUES (?, ?)",
            [(i, store.document_text(page["doc_id"])) for i, page in enumerate(self._pages)],
        )

    def search(self, question: str, *, k: int = 10) -> list[Retrieved]:
        """The `k` best-matching pages for `question`, best first. A page with none of the
        question's terms is not returned."""
        if self._index is None:
            raise ValueError("this index is closed")
        if k < 1:
            raise ValueError("k must be at least 1")
        terms = query_terms(question)
        if not terms:
            return []
        # Quoting is defence in depth: the tokenizer already keeps only lowercase word characters,
        # and no Unicode word character was found to break a bare token (probed 2026-11-09), so no
        # test can tell quoted from unquoted. It stays because it costs nothing.
        match = " OR ".join(f'"{term}"' for term in terms)
        ranked = self._index.execute(
            "SELECT rowid, bm25(docs) FROM docs WHERE docs MATCH ?", (match,)
        ).fetchall()
        # bm25() is lower for better matches. Sort here (not in SQL) so ties break by URL.
        ordered = sorted(ranked, key=lambda row: (row[1], self._pages[row[0]]["url"]))
        return [
            Retrieved(self._pages[row[0]]["doc_id"], self._pages[row[0]]["url"])
            for row in ordered[:k]
        ]

    def close(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None

    def __enter__(self) -> PageIndex:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def retrieve(store: ClaimStore, snapshot_id: int, question: str, *, k: int = 10) -> list[Retrieved]:
    """The `k` best-matching pages of one snapshot for `question`, best first. Builds an index
    for this one call; use `PageIndex` to ask many questions."""
    with PageIndex(store, snapshot_id) as index:
        return index.search(question, k=k)
