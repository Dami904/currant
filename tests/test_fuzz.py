"""Property tests: the guards hold for generated inputs, not only for the examples we thought of.

Each property states a guarantee the pipeline relies on:

* `locate` never returns a span outside the page, a verbatim hit is the exact text, and a loose hit
  differs from the copy only in whitespace runs and markdown backslash escapes;
* `defang` leaves no marker syntax in page text and is idempotent;
* `_apply` merges overlapping edits into one region, and a redacted region's text is gone;
* `verify_contested` keeps only numbers written in the CONTESTED notice.
"""

from __future__ import annotations

import re
import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from currant.extract import Span, locate, numbers_in
from currant.ground import REMOVED, Action, Ref, _apply, defang
from currant.harness.answer import Answer, ContestedValue, verify_contested

FUZZ = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# Text that looks like markdown docs: words, whitespace, punctuation, escapes and markers.
DOC_CHARS = st.sampled_from(
    list("abcxyz019 \n\t") + list("\\$*_[]()<>.,:;!?-#`") + ["<<<", ">>>", "[SUPERSEDED", "é"]
)
doc_text = st.lists(DOC_CHARS, max_size=60).map("".join)

_ESCAPE = re.compile(r"\\(?=[" + re.escape(string.punctuation) + r"])")


def _norm(text: str) -> str:
    """Drop backslashes that escape punctuation, and collapse whitespace runs."""
    return " ".join(_ESCAPE.sub("", text).split())


# --- locate ---------------------------------------------------------------------------------


@FUZZ
@given(text=doc_text, quote=doc_text)
def test_locate_never_raises_and_never_points_outside_the_page(text: str, quote: str) -> None:
    found = locate(text, quote)
    if isinstance(found, Span):
        assert 0 <= found.start < found.end <= len(text)
        if found.exact:
            assert text[found.start : found.end] == quote.strip()
    else:
        assert found.split(":")[0] in {"quote_empty", "quote_ambiguous", "quote_not_found"}


@FUZZ
@given(text=doc_text, data=st.data())
def test_a_unique_verbatim_substring_is_found_exactly(text: str, data: st.DataObject) -> None:
    i = data.draw(st.integers(0, len(text)))
    j = data.draw(st.integers(i, len(text)))
    needle = text[i:j].strip()
    if not needle or text.count(needle) != 1:
        return
    found = locate(text, needle)
    assert isinstance(found, Span) and found.exact
    assert text[found.start : found.end] == needle


@FUZZ
@given(text=doc_text, quote=doc_text)
def test_a_loose_hit_differs_only_in_whitespace_and_escapes(text: str, quote: str) -> None:
    found = locate(text, quote)
    if isinstance(found, Span) and not found.exact:
        assert _norm(text[found.start : found.end]) == _norm(quote)


WORDS = st.lists(st.sampled_from(["rate", "$10", "per", "min", "a_b", "*x*", "v1.2", "uploads"]),
                 min_size=1, max_size=6)  # fmt: skip
GAPS = st.sampled_from([" ", "  ", "\n", " \t "])


@FUZZ
@given(words=WORDS, data=st.data())
def test_a_model_copy_with_normalised_spacing_and_no_escapes_is_found_and_flagged(
    words: list[str], data: st.DataObject
) -> None:
    # The page escapes some punctuation and spaces words oddly; the model's copy does neither.
    escaped = [re.sub(r"([$*_])", r"\\\1", w) if data.draw(st.booleans()) else w for w in words]
    page_body = "".join(w + data.draw(GAPS) for w in escaped).rstrip()
    text = f"Intro.\n{page_body}\nEnd."
    copy = " ".join(words)
    found = locate(text, copy)
    assert isinstance(found, Span), found
    assert _norm(text[found.start : found.end]) == _norm(copy)
    assert found.exact == (copy in text)


# --- defang ---------------------------------------------------------------------------------

_NOTE_OPENER = re.compile(r"\[\s*(?:SUPERSEDED|REMOVED)", re.IGNORECASE)


@FUZZ
@given(text=doc_text)
def test_defang_leaves_no_marker_syntax_and_is_idempotent(text: str) -> None:
    out = defang(text)
    assert "<<<" not in out and ">>>" not in out
    assert not _NOTE_OPENER.search(out)
    assert defang(out) == out


@FUZZ
@given(text=st.text(alphabet="abc xyz.,\n019"))
def test_defang_does_not_touch_ordinary_text(text: str) -> None:
    assert defang(text) == text


# --- _apply: overlapping edits --------------------------------------------------------------

PLAIN = st.text(alphabet="abcd \n", min_size=1, max_size=40)


def _action(kind: str, start: int, end: int, n: int, text: str) -> Action:
    target = Ref("d", "https://x/a", start, end, text[start:end])
    source = Ref("e", "https://x/b", 0, 1, "N")
    return Action(kind, f"r{n:03d}", target, source, ())


@st.composite
def page_and_edits(draw: st.DrawFn, kinds: tuple[str, ...]) -> tuple[str, list[Action]]:
    text = draw(PLAIN)
    edits = []
    for n in range(draw(st.integers(0, 5))):
        start = draw(st.integers(0, len(text) - 1))
        end = draw(st.integers(start + 1, len(text)))
        edits.append(_action(draw(st.sampled_from(kinds)), start, end, n, text))
    return text, edits


def _merged(edits: list[Action]) -> list[tuple[int, int]]:
    """Independent statement of the merge rule: a span that starts before the previous region
    ends joins it; a span that starts exactly where it ends does not."""
    regions: list[tuple[int, int]] = []
    for a in sorted(edits, key=lambda a: (a.target.start, a.target.end)):
        if regions and a.target.start < regions[-1][1]:
            regions[-1] = (regions[-1][0], max(regions[-1][1], a.target.end))
        else:
            regions.append((a.target.start, a.target.end))
    return regions


@FUZZ
@given(case=page_and_edits(("redact",)))
def test_redactions_merge_and_remove_exactly_their_regions(case: tuple[str, list[Action]]) -> None:
    text, edits = case
    expected, position = [], 0
    for start, end in _merged(edits):
        expected += [text[position:start], REMOVED]
        position = end
    expected.append(text[position:])
    assert _apply(text, edits) == "".join(expected)


@FUZZ
@given(case=page_and_edits(("redact", "annotate")))
def test_mixed_edits_never_raise_and_keep_text_outside_every_region(
    case: tuple[str, list[Action]],
) -> None:
    text, edits = case
    out = _apply(text, edits)
    regions = _merged(edits)
    if regions:
        assert out.startswith(text[: regions[0][0]])
        assert out.endswith(text[regions[-1][1] :])
    else:
        assert out == text


# --- verify_contested -----------------------------------------------------------------------


@FUZZ
@given(
    quoted=st.lists(st.integers(0, 500), min_size=1, max_size=3),
    proposed=st.lists(st.integers(0, 500), max_size=5),
)
def test_only_numbers_the_notice_quotes_survive(quoted: list[int], proposed: list[int]) -> None:
    lines = "\n".join(f'- https://x/{n}a: "Limit is {q} MB."' for n, q in enumerate(quoted))
    notice = f"<<<NOTICE: CONTESTED>>>\nThese sources disagree.\n{lines}\n<<<END NOTICE>>>\n"
    # Every proposed number also appears in a document outside the notice: it must not count.
    others = " ".join(str(p) for p in proposed)
    context = notice + f"<<<DOCUMENT 1: https://x/d>>>\nOther figures: {others}.\n"
    values = tuple(ContestedValue(p, "MB", None) for p in proposed)
    kept = verify_contested(Answer("contested", None, None, None, values), context).contested
    allowed = numbers_in(notice)
    assert all(v.value in allowed for v in kept)
    assert [v.value for v in kept] == [float(p) for p in proposed if float(p) in allowed]
