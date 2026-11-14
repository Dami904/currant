from __future__ import annotations

import sqlite3

import pytest

from currant.ground import Retrieved
from currant.retrieve import PageIndex, query_terms, retrieve
from currant.store import ClaimStore

PAGES = {
    "https://docs.example.com/limits.md": (
        "# Rate limits\n\nRate limits: each key may make 60 requests a minute. The limit resets.\n"
    ),
    "https://docs.example.com/billing.md": "# Billing\n\nInvoices are sent monthly.\n",
    "https://docs.example.com/uploads.md": "# Uploads\n\nUploads can be up to 25 MB.\n",
    "https://docs.example.com/faq.md": "# FAQ\n\nHow do rate limits work? See the limits page.\n",
}


def store_with(pages: dict[str, str], label: str = "t") -> tuple[ClaimStore, int]:
    store = ClaimStore(":memory:")
    return store, store.ingest_pages(label, list(pages.items())).snapshot_id


def urls(found: list[Retrieved]) -> list[str]:
    return [r.url for r in found]


def test_fts5_is_available_in_this_python() -> None:
    sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")


def test_the_most_relevant_page_comes_first() -> None:
    store, snap = store_with(PAGES)
    found = retrieve(store, snap, "what is the rate limit?", k=4)
    assert urls(found)[0] == "https://docs.example.com/limits.md"
    assert "https://docs.example.com/billing.md" not in urls(
        found
    )  # no matching terms: not returned


def test_k_limits_the_result_and_only_matching_pages_are_returned() -> None:
    store, snap = store_with(PAGES)
    assert len(retrieve(store, snap, "limits", k=1)) == 1
    assert urls(retrieve(store, snap, "invoices", k=10)) == ["https://docs.example.com/billing.md"]


def test_results_carry_the_stored_document_id_and_url() -> None:
    store, snap = store_with(PAGES)
    (found,) = retrieve(store, snap, "monthly invoices", k=3)
    assert store.document_text(found.doc_id).startswith("# Billing")
    assert store.has_page(snap, found.doc_id, found.url)


def test_an_empty_or_symbol_only_question_returns_nothing() -> None:
    store, snap = store_with(PAGES)
    for question in ("", "   ", "?!*()", "the and of"):
        assert retrieve(store, snap, question, k=5) == []


@pytest.mark.parametrize(
    "question",
    [
        'limits" OR "',
        "limits AND NOT uploads",
        "NEAR(limits uploads)",
        "limits*",
        "col:limits",
        "-limits",
        "(((",
        '"unterminated',
        "limits; DROP TABLE docs",
    ],
)
def test_search_syntax_in_a_question_is_treated_as_plain_words(question: str) -> None:
    store, snap = store_with(PAGES)
    retrieve(store, snap, question, k=5)  # must not raise


def test_operators_do_not_change_what_matches() -> None:
    store, snap = store_with(PAGES)
    # "NOT uploads" as text would exclude the uploads page if it were parsed as an operator.
    found = urls(retrieve(store, snap, "limits NOT uploads", k=5))
    assert "https://docs.example.com/uploads.md" in found


def test_ties_are_broken_by_url_so_the_order_is_deterministic() -> None:
    # Different pages (so not merged) with equal length and equal match quality: a true tie.
    words = {3: "ccc", 1: "aaa", 2: "bbb"}
    pages = {
        f"https://docs.example.com/p{i}.md": f"same words {w}" + chr(10) for i, w in words.items()
    }
    store, snap = store_with(pages)
    found = urls(retrieve(store, snap, "same words", k=3))
    assert found == [f"https://docs.example.com/p{i}.md" for i in (1, 2, 3)]


def test_only_the_requested_snapshot_is_searched() -> None:
    store, first = store_with({"https://docs.example.com/a.md": "alpha topic\n"}, "one")
    second = store.ingest_pages(
        "two", [("https://docs.example.com/b.md", "beta topic\n")]
    ).snapshot_id
    assert urls(retrieve(store, first, "topic", k=5)) == ["https://docs.example.com/a.md"]
    assert urls(retrieve(store, second, "topic", k=5)) == ["https://docs.example.com/b.md"]


def test_one_document_under_two_urls_is_returned_once() -> None:
    same = "shared text about widgets\n"
    store, snap = store_with(
        {"https://a.example.com/x.md": same, "https://b.example.com/x.md": same}
    )
    found = retrieve(store, snap, "widgets", k=5)
    assert len(found) == 1 and found[0].url == "https://a.example.com/x.md"


def test_stemming_matches_word_forms() -> None:
    store, snap = store_with(PAGES)
    assert "https://docs.example.com/uploads.md" in urls(
        retrieve(store, snap, "uploading files", k=3)
    )


def test_a_nonpositive_k_is_refused() -> None:
    store, snap = store_with(PAGES)
    with pytest.raises(ValueError, match="k"):
        retrieve(store, snap, "limits", k=0)


def test_query_terms_are_unique_lowercase_words_without_stopwords() -> None:
    assert query_terms("What is the Rate-Limit? Rate limit!") == ["rate", "limit"]
    assert query_terms("") == [] and query_terms("the of a") == []


def test_the_number_of_terms_is_capped() -> None:
    assert len(query_terms(" ".join(f"word{i}" for i in range(500)))) == 32


# --- the index is built once and reused ---------------------------------------------------------


def test_a_page_index_answers_many_questions_from_one_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, snap = store_with(PAGES)
    reads = {"n": 0}
    real = store.document_text

    def counting(doc_id: str) -> str:
        reads["n"] += 1
        return real(doc_id)

    monkeypatch.setattr(store, "document_text", counting)
    with PageIndex(store, snap) as index:
        built = reads["n"]
        assert built == len(PAGES)  # each page read once, at build time
        first = index.search("rate limit", k=3)
        second = index.search("invoices", k=3)
        assert reads["n"] == built  # searching never rereads the store
    assert urls(first)[0] == "https://docs.example.com/limits.md"
    assert urls(second) == ["https://docs.example.com/billing.md"]


def test_the_index_gives_the_same_answers_as_the_one_shot_function() -> None:
    store, snap = store_with(PAGES)
    with PageIndex(store, snap) as index:
        for question in ("rate limit", "uploads", "monthly invoices", "nothing matches xyzzy"):
            assert index.search(question, k=4) == retrieve(store, snap, question, k=4)


def test_a_closed_index_refuses_to_search() -> None:
    store, snap = store_with(PAGES)
    index = PageIndex(store, snap)
    index.close()
    with pytest.raises(ValueError, match="closed"):
        index.search("limits", k=1)
