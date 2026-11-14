"""Real evaluation items: candidate pairs from the real corpus, labelled BY A PERSON.

The plan's headline result needs items about REAL documentation, each hand-checked against its two
sources. The synthetic items cannot supply that (their "updates" are templated), and nothing may
decide the truth of a real item except a person, or the evaluation would grade the detector with its
own answers.

    1. `make_worksheet`  proposes candidate pairs: two claims on different pages that look like the
                         same fact with different numbers. It uses only the detector's CANDIDATE
                         stage (text similarity), never its verdict, so what the detector says about
                         a pair is not shown to the person who labels it.
    2. a person          fills in `verdict` (and any quotes it needs) for each pair they can judge.
    3. `import_worksheet` turns the filled worksheet into sealed items. Every quote is re-checked
                         verbatim against the stored page and every date comparison is made by our
                         code, so a typo cannot become a wrong label.

Items are `heldout` unless the person marks them `seen` (studied before labelling, for example the
two pairs from the plan), in which case they are `dev`. Importing is refused after the freeze.

The worksheet holds candidate sponsor-documentation conflicts, so the command writes it under
`docs/private/` (git-ignored): nothing here is published until two sources confirm it and the
maintainers have been told.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from currant.detect import candidate_pairs, enclosing_line, first_iso_date, same_kind
from currant.evalset import EvalError, EvalStore
from currant.extract import Span, locate
from currant.store import ClaimRow, ClaimStore

VERDICTS = (
    "a_newer_explicit",  # page A replaced B, and a sentence on A says so (give `ordering_quote`)
    "b_newer_explicit",
    "a_newer_dated",  # both pages carry dates and A is later (give both date quotes)
    "b_newer_dated",
    "contested",  # they disagree and nothing in the TEXT says which is current
    "not_a_conflict",  # different facts after all: no item is made
)
INSTRUCTIONS = [
    "Judge ONLY from the two quotes and the page texts they come from, not from today's live site.",
    "Fill `verdict` with one of: " + ", ".join(VERDICTS) + ". Leave it empty to skip a pair.",
    "a_newer_explicit / b_newer_explicit: copy into `ordering_quote` the sentence, from the NEWER "
    "page, that says it replaces the old value. It must appear word for word on that page.",
    "a_newer_dated / b_newer_dated: copy into `date_quote_newer` and `date_quote_older` a line "
    "from each page that carries its date (an ISO date such as 2026-03-14). We compare them.",
    "contested: use it when the text gives no way to order the pages, even if you happen to know "
    "which is right from outside. That is what a text-only system should say.",
    "Set `seen` to true for any pair you had studied before labelling it (it then goes to dev).",
    "You may edit `question` (it should have exactly one numeric answer) and `cluster` (items "
    "about the same underlying fact must share a cluster).",
]


@dataclass
class ImportReport:
    added: int = 0
    skipped: list[str] = field(default_factory=list)  # ids with no verdict or not a conflict
    problems: list[str] = field(default_factory=list)  # ids refused, with the reason


def _side(store: ClaimStore, snapshot_id: int, claim: ClaimRow) -> dict[str, Any]:
    text = store.document_text(claim.doc_id)
    return {
        "url": store.url_of(snapshot_id, claim.doc_id),
        "quote": claim.quote,
        "value": claim.value_text,
        "number": claim.value_number,
        "page_date": first_iso_date(text[:600]),
    }


def make_worksheet(
    store: ClaimStore, extract_run_id: int, *, max_items: int = 60
) -> dict[str, Any]:
    """Candidate pairs, most alike first, for a person to label. Numeric claims of the same kind
    only, so every item has a typed answer."""
    snapshot_id = store.run_meta(extract_run_id).snapshot_id
    numeric = [c for c in store.claims(extract_run_id) if c.value_number is not None]
    texts = {doc: store.document_text(doc) for doc in {c.doc_id for c in numeric}}
    lines = {c.claim_id: enclosing_line(texts[c.doc_id], c.start_char, c.end_char) for c in numeric}
    # The same pairing and the same kind-of-value rule as the detector, so a pair it could find
    # is a pair a person is asked about.
    pairs = [
        c
        for c in candidate_pairs(numeric, max_pairs=max_items * 3, lines=lines)
        if same_kind(c.a, c.b)
    ][:max_items]
    items = []
    for number, pair in enumerate(pairs, start=1):
        cluster = hashlib.sha256("|".join(sorted((pair.a.doc_id, pair.b.doc_id))).encode())
        items.append(
            {
                "id": f"w{number:03d}",
                "question": f"What is the {pair.a.attribute} for {pair.a.subject}?",
                "cluster": f"real-{cluster.hexdigest()[:12]}",
                "seen": False,
                "a": _side(store, snapshot_id, pair.a),
                "b": _side(store, snapshot_id, pair.b),
                "verdict": "",
                "ordering_quote": "",
                "date_quote_newer": "",
                "date_quote_older": "",
                "note": "",
                "_claims": [pair.a.claim_id, pair.b.claim_id],  # for the importer; do not edit
            }
        )
    return {"instructions": INSTRUCTIONS, "extract_run": extract_run_id, "items": items}


def _verbatim(text: str, quote: str) -> Span | None:
    found = locate(text, quote)
    return found if isinstance(found, Span) else None


def _label(
    item: dict[str, Any], a: ClaimRow, b: ClaimRow, text_a: str, text_b: str
) -> dict[str, Any] | str:
    """The label for one filled-in item, or the reason it cannot be made."""
    verdict = item["verdict"]
    texts = {"a": text_a, "b": text_b}
    claims = {"a": a, "b": b}
    if verdict == "contested":
        stale, update = "a", "b"
        scenario, basis, state = "contested_implicit", "none", "CONTESTED"
        evidence: str | None = None
    else:
        newer = verdict[0]
        stale, update = ("b", "a") if newer == "a" else ("a", "b")
        if verdict.endswith("_explicit"):
            scenario, basis, state = "supersedes_explicit", "explicit_text", "CANON"
            quote = str(item.get("ordering_quote") or "")
            if not quote.strip() or _verbatim(texts[newer], quote) is None:
                return "ordering_quote is empty or is not word for word on the newer page"
            evidence = quote
        else:
            scenario, basis, state = "supersedes_dated", "dated", "CANON"
            newer_q = str(item.get("date_quote_newer") or "")
            older_q = str(item.get("date_quote_older") or "")
            if _verbatim(texts[newer], newer_q) is None or _verbatim(texts[stale], older_q) is None:
                return "a date quote is empty or is not word for word on its page"
            date_new, date_old = first_iso_date(newer_q), first_iso_date(older_q)
            if date_new is None or date_old is None:
                return "a date quote has no ISO date (like 2026-03-14)"
            if date_new <= date_old:
                return f"the 'newer' page is dated {date_new}, not after {date_old}"
            evidence = newer_q
    older_claim, newer_claim = claims[stale], claims[update]
    return {
        "scenario": scenario,
        "stale_value_number": older_claim.value_number,
        "expected_state": state,
        "current_value_number": newer_claim.value_number if state == "CANON" else None,
        "current_value_text": newer_claim.value_text if state == "CANON" else None,
        "update_quote": newer_claim.quote,
        "ordering_basis": basis,
        "ordering_evidence": evidence,
        "stale_page_id": stale,
        "update_page_id": update,
        "stale_quote": older_claim.quote,
        "stale_span": [older_claim.start_char, older_claim.end_char],
        "source": "real",
        "note": str(item.get("note") or ""),
    }


def import_worksheet(
    store: ClaimStore, extract_run_id: int, evals: EvalStore, worksheet: dict[str, Any]
) -> ImportReport:
    """Seal every filled-in item. A problem with one item is reported and does not stop the rest."""
    report = ImportReport()
    claims = {c.claim_id: c for c in store.claims(extract_run_id)}
    snapshot_id = store.run_meta(extract_run_id).snapshot_id
    for item in worksheet.get("items", []):
        item_id = str(item.get("id", "?"))
        verdict = str(item.get("verdict") or "").strip()
        if verdict in ("", "not_a_conflict"):
            report.skipped.append(item_id)
            continue
        if verdict not in VERDICTS:
            report.problems.append(f"{item_id}: unknown verdict {verdict!r}")
            continue
        try:
            a, b = (claims[cid] for cid in item["_claims"])
        except (KeyError, ValueError, TypeError):
            report.problems.append(f"{item_id}: its claims are not in extract run {extract_run_id}")
            continue
        item = {**item, "verdict": verdict}
        text_a, text_b = store.document_text(a.doc_id), store.document_text(b.doc_id)
        label = _label(item, a, b, text_a, text_b)
        if isinstance(label, str):
            report.problems.append(f"{item_id}: {label}")
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            report.problems.append(f"{item_id}: the question is empty")
            continue
        spec = {
            "question": question,
            "pages": [
                {"id": "a", "url": store.url_of(snapshot_id, a.doc_id), "text": text_a},
                {"id": "b", "url": store.url_of(snapshot_id, b.doc_id), "text": text_b},
            ],
        }
        try:
            evals.add_item(
                "real", str(item.get("cluster") or f"real-{item_id}"), spec, label,
                seen=bool(item.get("seen")),
            )  # fmt: skip
        except EvalError as exc:
            report.problems.append(f"{item_id}: {exc}")
            continue
        report.added += 1
    return report


# --- labelling at the terminal ---------------------------------------------------------

WINDOW = 160
CHOICES = {
    "a": "a_newer_explicit",
    "b": "b_newer_explicit",
    "da": "a_newer_dated",
    "db": "b_newer_dated",
    "c": "contested",
    "n": "not_a_conflict",
}
MENU = (
    "  a / b   A (or B) is the NEWER page and a sentence on it says it replaces the old value\n"
    "  da / db A (or B) is newer and both pages show a date\n"
    "  c       they disagree and the TEXT gives no way to order them\n"
    "  n       not a conflict (different facts)\n"
    "  s       skip for now        q   save and quit\n"
)


def _context(text: str, claim: ClaimRow) -> str:
    before = text[max(0, claim.start_char - WINDOW) : claim.start_char]
    after = text[claim.end_char : claim.end_char + WINDOW]
    return f"{before}[[ {claim.quote} ]]{after}".replace("\n", " ")


def validate_item(
    store: ClaimStore, extract_run_id: int, item: dict[str, Any], verdict: str
) -> str | None:
    """None if a label can be made from this item with this verdict, else the reason."""
    if verdict == "not_a_conflict":
        return None  # no item is made, so there is nothing to check
    claims = {c.claim_id: c for c in store.claims(extract_run_id)}
    try:
        a, b = (claims[cid] for cid in item["_claims"])
    except (KeyError, ValueError, TypeError):
        return "its claims are not in this extract run"
    label = _label(
        {**item, "verdict": verdict}, a, b, *(store.document_text(c.doc_id) for c in (a, b))
    )
    return label if isinstance(label, str) else None


def label_session(
    store: ClaimStore,
    extract_run_id: int,
    worksheet: dict[str, Any],
    ask: Callable[[str], str],
    show: Callable[[str], None],
    save: Callable[[dict[str, Any]], None],
) -> dict[str, int]:
    """Walk the unlabelled pairs, one answer each. Quotes a person pastes are checked at once and
    asked again if they are not on the page; the worksheet is saved after every answer."""
    claims = {c.claim_id: c for c in store.claims(extract_run_id)}
    todo = [it for it in worksheet["items"] if not str(it.get("verdict") or "").strip()]
    counts = {"labelled": 0, "skipped": 0, "left": 0}
    for number, item in enumerate(todo, start=1):
        try:
            a, b = (claims[cid] for cid in item["_claims"])
        except (KeyError, ValueError, TypeError):
            show(
                f"\n=== {item.get('id', '?')}: its claims are not in run {extract_run_id}; skipped"
            )
            counts["skipped"] += 1
            continue
        show(f"\n=== {item['id']}  ({number} of {len(todo)})   question: {item['question']}")
        for name, claim in (("A", a), ("B", b)):
            context = _context(store.document_text(claim.doc_id), claim)
            show(f"{name}  {item[name.lower()]['url']}\n   {context}")
        show(MENU)
        while True:
            choice = ask("verdict> ").strip().lower()
            if choice == "q":
                counts["left"] = len(todo) - number + 1
                return counts
            if choice == "s":
                counts["skipped"] += 1
                break
            verdict = CHOICES.get(choice)
            if verdict is None:
                show("  choose a, b, da, db, c, n, s or q")
                continue
            fields: dict[str, str] = {}
            if verdict.endswith("_explicit"):
                fields["ordering_quote"] = ask("paste the sentence from the NEWER page> ").strip()
            elif verdict.endswith("_dated"):
                fields["date_quote_newer"] = ask("paste a dated line from the NEWER page> ").strip()
                fields["date_quote_older"] = ask("paste a dated line from the OLDER page> ").strip()
            problem = validate_item(store, extract_run_id, {**item, **fields}, verdict)
            if problem:
                show(f"  not accepted: {problem}. Try again, or choose s to skip.")
                continue
            item.update(verdict=verdict, **fields)
            if verdict != "not_a_conflict":
                item["seen"] = bool(item.get("seen"))
            save(worksheet)
            counts["labelled"] += 1
            break
    return counts
