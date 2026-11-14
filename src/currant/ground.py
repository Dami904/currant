"""Ground: turn retrieved pages plus verified relations into the context a model will see.

Modes (all act on SPANS, never on whole pages):

* `baseline`     the pages exactly as retrieved
* `redact`       a stale sentence is replaced by a short marker
* `annotate`     a stale sentence stays and is followed by the quote that replaced it
* `pull`         the newer evidence is added when only the stale page was retrieved
* `redact_pull`  both
* every mode but `baseline` adds a CONTESTED notice, with both quotes, where two sources
  disagree and nothing verified says which is current. Nothing is cut for a contested pair.

Default-deny: an action happens only if ALL of these hold, otherwise nothing is done.

* the relation is `verified` in the store (the database refused it otherwise) and belongs to the
  relate run we were asked to use;
* every quote involved (the stale span, the winning span, each piece of evidence) is re-checked
  verbatim against the stored document text now, not trusted from when it was recorded;
* the stale side is a `current` claim. A sentence already reported as historical ("previously X,
  now Y") is never cut;
* for annotate and pull, the winner is the END of the replacement chain. A chain that branches or
  loops has no single winner, so it gets no annotation and no pull (never an intermediate value).

`render` is a pure function of (pages, texts, actions). The receipt stores the actions and `replay`
runs `ground` again from the store, so the context hash is recomputed, not trusted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from currant.store import ClaimRow, ClaimStore, RelationRow

MODES = ("baseline", "redact", "annotate", "pull", "redact_pull")
REMOVED = "[REMOVED: superseded by newer documentation]"
MAX_CHAIN = 16
_KIND_ORDER = {"contested": 0, "redact": 1, "annotate": 2, "pull": 3}


@dataclass(frozen=True)
class Retrieved:
    doc_id: str
    url: str


@dataclass(frozen=True)
class Ref:
    """A verbatim span of one stored document."""

    doc_id: str
    url: str
    start: int
    end: int
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "url": self.url,
            "start": self.start,
            "end": self.end,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class Action:
    kind: str  # contested | redact | annotate | pull
    relation_id: str
    target: Ref  # the stale span (contested: the first side)
    source: Ref  # the winning span (contested: the second side)
    evidence: tuple[tuple[str, Ref], ...]  # (role, span) of the relation's verified evidence
    chain: tuple[str, ...] = ()  # relation ids followed from the direct winner to the latest

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "relation_id": self.relation_id,
            "target": self.target.to_dict(),
            "source": self.source.to_dict(),
            "evidence": [{"role": role, **ref.to_dict()} for role, ref in self.evidence],
            "chain": list(self.chain),
        }


@dataclass(frozen=True)
class Grounded:
    mode: str
    documents: tuple[Retrieved, ...]
    actions: list[Action]
    context: str

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(self.context.encode("utf-8")).hexdigest()


# --- rendering (pure) -------------------------------------------------------------------------


_ANGLES = re.compile(r"<{3,}|>{3,}")
_NOTE_OPENERS = re.compile(r"\[(?=\s*(?:SUPERSEDED|REMOVED))", re.IGNORECASE)


def defang(text: str) -> str:
    """Page text with anything that imitates our own context markers made inert.

    The context is built from page text and from markers only our code writes: `<<<DOCUMENT n>>>`
    blocks, a CONTESTED notice, PULLED EVIDENCE, `[SUPERSEDED: ...]` and `[REMOVED: ...]`. A
    page that contains those strings could close its own block and open a fake one of evidence the
    answering prompt tells the model to trust. A run of three or more angle brackets is spread
    out, and a `[` that opens a SUPERSEDED or REMOVED note becomes `(`. Text without those is
    returned unchanged, so real pages (none contains either) are not altered, and the function is
    idempotent. A page can still use plain words like "SUPERSEDED"; only the marker syntax is
    ours. Lowering those words in page text was tried and measured on 2026-11-11: it made no
    difference (a fake note still worked 9 of 10 times), so it was not kept (docs/THREAT_MODEL.md).
    """
    text = _ANGLES.sub(lambda m: " ".join(m.group()), text)
    return _NOTE_OPENERS.sub("(", text)


def _note(action: Action) -> str:
    source = action.source
    quote, url = defang(source.quote), defang(source.url)
    return f' [SUPERSEDED: the current documentation says: "{quote}" ({url})]'


def _apply(text: str, edits: list[Action]) -> str:
    """Apply span edits to one page. Overlapping spans are merged into one region."""
    regions: list[tuple[int, int, list[Action]]] = []
    for action in sorted(edits, key=lambda a: (a.target.start, a.target.end, a.relation_id)):
        start, end = action.target.start, action.target.end
        if regions and start < regions[-1][1]:
            first, last, members = regions[-1]
            regions[-1] = (first, max(last, end), [*members, action])
        else:
            regions.append((start, end, [action]))
    out: list[str] = []
    position = 0
    for start, end, members in regions:
        out.append(defang(text[position:start]))
        if any(m.kind == "redact" for m in members):
            out.append(REMOVED)
        else:
            out.append(defang(text[start:end]))
            notes: list[str] = []
            for member in members:
                if _note(member) not in notes:
                    notes.append(_note(member))
            out.extend(notes)
        position = end
    out.append(defang(text[position:]))
    return "".join(out)


def render(docs: tuple[Retrieved, ...], texts: dict[str, str], actions: list[Action]) -> str:
    parts: list[str] = []
    contested = [a for a in actions if a.kind == "contested"]
    if contested:
        lines: list[str] = []
        for action in contested:
            for ref in (action.target, action.source):
                line = f'- {defang(ref.url)}: "{defang(ref.quote)}"'
                if line not in lines:
                    lines.append(line)
        parts.append(
            "<<<NOTICE: CONTESTED>>>\n"
            "These sources disagree and nothing in them shows which is current. "
            "Do not pick a winner; report both.\n" + "\n".join(lines) + "\n<<<END NOTICE>>>"
        )
    for number, doc in enumerate(docs, start=1):
        edits = [
            a for a in actions if a.kind in ("redact", "annotate") and a.target.doc_id == doc.doc_id
        ]
        body = _apply(texts[doc.doc_id], edits)
        parts.append(
            f"<<<DOCUMENT {number}: {defang(doc.url)}>>>\n{body}\n<<<END DOCUMENT {number}>>>"
        )
    pulled: list[str] = []
    for action in actions:
        if action.kind == "pull":
            line = f'- {defang(action.source.url)}: "{defang(action.source.quote)}"'
            if line not in pulled:
                pulled.append(line)
    if pulled:
        parts.append("<<<PULLED EVIDENCE>>>\n" + "\n".join(pulled) + "\n<<<END PULLED EVIDENCE>>>")
    return "\n".join(parts) + "\n"


# --- planning ---------------------------------------------------------------------------------


class _Planner:
    def __init__(self, store: ClaimStore, extract_run_id: int, relate_run_id: int) -> None:
        self.store = store
        self.snapshot_id = store.run_meta(extract_run_id).snapshot_id
        self.claims = {c.claim_id: c for c in store.claims(extract_run_id)}
        self.relate_run_id = relate_run_id
        self._texts: dict[str, str] = {}

    def text(self, doc_id: str) -> str:
        if doc_id not in self._texts:
            self._texts[doc_id] = self.store.document_text(doc_id)
        return self._texts[doc_id]

    def ref(self, claim: ClaimRow) -> Ref | None:
        """The claim's span, only if its quote is verbatim in the stored text right now."""
        text = self.text(claim.doc_id)
        if not (0 <= claim.start_char < claim.end_char <= len(text)):
            return None
        if text[claim.start_char : claim.end_char] != claim.quote:
            return None
        url = self.store.url_of(self.snapshot_id, claim.doc_id)
        return Ref(claim.doc_id, url, claim.start_char, claim.end_char, claim.quote)

    def evidence(self, relation: RelationRow) -> tuple[tuple[str, Ref], ...] | None:
        """The relation's verified evidence, each quote re-checked. None if any fails."""
        out: list[tuple[str, Ref]] = []
        for row in self.store.relation_evidence(relation.relation_id):
            if not row.verified:
                continue  # recorded for precision statistics, can never support anything
            text = self.text(row.doc_id)
            if text[row.start_char : row.end_char] != row.quote:
                return None
            url = self.store.url_of(self.snapshot_id, row.doc_id)
            out.append((row.role, Ref(row.doc_id, url, row.start_char, row.end_char, row.quote)))
        return tuple(out) if out else None


def _latest(
    start: ClaimRow,
    successors: dict[str, list[RelationRow]],
    claims: dict[str, ClaimRow],
) -> tuple[ClaimRow, tuple[str, ...]] | None:
    """Follow replacements from `start` to the end of the chain. None if the chain branches or
    loops: with no single winner we say nothing rather than name an intermediate value."""
    current = start
    path: list[str] = []
    for _ in range(MAX_CHAIN):  # also what stops a loop: it never reaches an end
        following = successors.get(current.claim_id, [])
        if not following:
            return current, tuple(path)
        if len(following) > 1:
            return None
        relation = following[0]
        nxt = claims.get(relation.claim_a)
        if nxt is None:
            return None
        path.append(relation.relation_id)
        current = nxt
    return None


def _loops_back(
    older: ClaimRow,
    newer: ClaimRow,
    successors: dict[str, list[RelationRow]],
    claims: dict[str, ClaimRow],
) -> bool:
    """True if following replacements from `newer` leads back to `older`: the sources replace
    each other, so neither is the winner and nothing may be cut on either side."""
    frontier, seen = [newer], {newer.claim_id}
    for _ in range(MAX_CHAIN):
        following: list[ClaimRow] = []
        for claim in frontier:
            for relation in successors.get(claim.claim_id, []):
                target = claims.get(relation.claim_a)
                if target is None:
                    continue
                if target.claim_id == older.claim_id:
                    return True
                if target.claim_id not in seen:
                    seen.add(target.claim_id)
                    following.append(target)
        if not following:
            return False
        frontier = following
    return False


def _inside(claim: ClaimRow, spans: list[tuple[str, int, int]]) -> bool:
    return any(
        doc == claim.doc_id and min(end, claim.end_char) > max(start, claim.start_char)
        for doc, start, end in spans
    )


def _plan(
    store: ClaimStore,
    docs: tuple[Retrieved, ...],
    mode: str,
    extract_run_id: int,
    relate_run_id: int,
) -> list[Action]:
    planner = _Planner(store, extract_run_id, relate_run_id)
    retrieved = {d.doc_id for d in docs}
    want_redact = mode in ("redact", "redact_pull")
    want_annotate = mode == "annotate"
    want_pull = mode in ("pull", "redact_pull")

    supersessions = store.verified_relations(relate_run_id, "supersedes")
    successors: dict[str, list[RelationRow]] = {}
    for relation in supersessions:
        successors.setdefault(relation.claim_b, []).append(relation)
    actions: list[Action] = []
    # Sentences a verified, unlooped supersession has put in order: (document, start, end).
    ordered: list[tuple[str, int, int]] = []

    for relation in supersessions:
        older, newer = planner.claims.get(relation.claim_b), planner.claims.get(relation.claim_a)
        if older is None or newer is None or older.stance != "current":
            continue  # already reported as past: "previously X, now Y" must survive
        if _loops_back(older, newer, successors, planner.claims):
            continue  # the pages replace each other: no winner, so no cut
        ordered.append((older.doc_id, older.start_char, older.end_char))
        if older.doc_id not in retrieved:
            continue
        target, direct = planner.ref(older), planner.ref(newer)
        evidence = planner.evidence(relation)
        if target is None or direct is None or evidence is None:
            continue
        if want_redact:
            actions.append(Action("redact", relation.relation_id, target, direct, evidence))
        if want_annotate or want_pull:
            resolved = _latest(newer, successors, planner.claims)
            if resolved is None:
                continue
            latest, path = resolved
            winner = planner.ref(latest)
            if winner is None:
                continue
            chain = (relation.relation_id, *path)
            if want_annotate:
                actions.append(
                    Action("annotate", relation.relation_id, target, winner, evidence, chain)
                )
            if want_pull and latest.doc_id not in retrieved:
                actions.append(
                    Action("pull", relation.relation_id, target, winner, evidence, chain)
                )

    superseded = {relation.claim_b for relation in supersessions}
    for relation in store.verified_relations(relate_run_id, "contradicts"):
        a, b = planner.claims.get(relation.claim_a), planner.claims.get(relation.claim_b)
        if a is None or b is None or superseded & {a.claim_id, b.claim_id}:
            continue  # an order exists for one of them, so it is not contested
        if a.stance != "current" or b.stance != "current":
            continue
        if any(_inside(claim, ordered) for claim in (a, b)):
            # Another claim of the same sentence has a verified order: that sentence is already
            # handled. A notice saying it is contested would contradict our own verified evidence
            # and make the model abstain (seen on dev: one sentence held three claims).
            continue
        if not ({a.doc_id, b.doc_id} & retrieved):
            continue
        ref_a, ref_b, evidence = planner.ref(a), planner.ref(b), planner.evidence(relation)
        if ref_a is None or ref_b is None or evidence is None:
            continue
        actions.append(Action("contested", relation.relation_id, ref_a, ref_b, evidence))

    actions.sort(
        key=lambda x: (_KIND_ORDER[x.kind], x.relation_id, x.target.doc_id, x.target.start)
    )
    return actions


def ground(
    store: ClaimStore,
    docs: list[Retrieved],
    *,
    mode: str,
    extract_run_id: int,
    relate_run_id: int,
) -> Grounded:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose one of {', '.join(MODES)}")
    extract_meta, relate_meta = store.run_meta(extract_run_id), store.run_meta(relate_run_id)
    if extract_meta.stage != "extract":
        raise ValueError(f"run {extract_run_id} is not an extract run")
    if relate_meta.stage != "relate":
        raise ValueError(f"run {relate_run_id} is not a relate run")
    if relate_meta.snapshot_id != extract_meta.snapshot_id:
        raise ValueError("the relate run belongs to a different snapshot than the extract run")
    if extract_meta.status != "complete":
        raise ValueError(
            f"extract run {extract_run_id} did not complete (status {extract_meta.status}): "
            f"some pages have no claims. Resume it: `currant extract --resume {extract_run_id}`."
        )
    if extract_meta.params.get("limited"):
        raise ValueError(
            f"extract run {extract_run_id} covered only part of the snapshot (--limit); "
            "run it again without a limit"
        )
    if relate_meta.status != "complete":
        raise ValueError(
            f"relate run {relate_run_id} did not complete (status {relate_meta.status}): some "
            "pairs were never decided. Rerun `currant relate`; decided pairs come from the cache."
        )
    snapshot_id = extract_meta.snapshot_id
    texts = {d.doc_id: store.document_text(d.doc_id) for d in docs}  # unknown document: refused
    for doc in docs:
        if not store.has_page(snapshot_id, doc.doc_id, doc.url):
            raise ValueError(f"{doc.url} is not the url of document {doc.doc_id[:12]} here")
    pages = tuple(docs)
    actions = [] if mode == "baseline" else _plan(store, pages, mode, extract_run_id, relate_run_id)
    return Grounded(mode, pages, actions, render(pages, texts, actions))
