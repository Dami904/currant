"""The landing page (site/index.html) is a claim in public, so it is held to the same rule as the
rest of Currant: a quotation on it must be verbatim from the checked drift data, a number on it must
also be written in the repository's own docs, and it must load nothing from anywhere else. Each
test fails if its guard is removed."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "index.html"
DRIFT = ROOT / "docs" / "drift" / "reppo-eval-api.json"
DOCS = ("README.md", "docs/LIMITATIONS.md")


def squash(text: str) -> str:
    return " ".join(html.unescape(text).split())


class Quotes(HTMLParser):
    """Collects the text of every <q> element: the page marks each verbatim quotation with it."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.current: list[str] = []
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "q":
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "q" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.found.append(squash("".join(self.current)))
                self.current = []

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.current.append(data)


def page_quotes(text: str) -> list[str]:
    parser = Quotes()
    parser.feed(text)
    return parser.found


def drift_quotes() -> set[str]:
    data = json.loads(DRIFT.read_text(encoding="utf-8"))
    return {squash(s["quote"]) for f in data["findings"] for s in f["sides"]}


def test_every_quotation_on_the_page_is_verbatim_from_the_checked_drift_data() -> None:
    quotes = page_quotes(PAGE.read_text(encoding="utf-8"))
    assert len(quotes) >= 6  # the page really shows the evidence, not just claims it
    allowed = drift_quotes()
    assert [q for q in quotes if q not in allowed] == []


def test_a_changed_quotation_is_caught() -> None:
    text = PAGE.read_text(encoding="utf-8").replace(
        "An evaluation costs 100 credits.", "An evaluation costs 90 credits.", 1
    )
    assert page_quotes(text) != page_quotes(PAGE.read_text(encoding="utf-8"))
    assert [q for q in page_quotes(text) if q not in drift_quotes()] != []


NUMBERS = ("0.857", "0.828", "84.2", "59.0", "66.7", "-7.7", "463", "611")


def test_every_headline_number_is_also_written_in_the_repository_docs() -> None:
    # The page uses a typographic minus (U+2212) where the docs write a hyphen.
    page = html.unescape(PAGE.read_text(encoding="utf-8")).replace(chr(0x2212), "-")
    docs = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in DOCS)
    for number in NUMBERS:
        assert number in page, f"{number} is no longer on the page"
        assert number in docs, f"{number} is on the page but not in README or LIMITATIONS"


def test_the_page_loads_nothing_from_anywhere_else() -> None:
    page = PAGE.read_text(encoding="utf-8")
    assert re.search(r"<script[^>]*\bsrc\s*=\s*[\"']/src/main\.ts", page, re.I)  # our own module
    assert not re.search(r"<script[^>]*\bsrc\s*=\s*[\"']?(https?:)?//", page, re.I)
    assert not re.search(r"<link[^>]*\bhref\s*=\s*[\"']?https?:", page, re.I)
    assert not re.search(r"@import|url\(\s*[\"']?https?:", page, re.I)
    assert not re.search(
        r"<(img|iframe|video|audio|source)[^>]*\bsrc\s*=\s*[\"']?https?:", page, re.I
    )


def test_the_page_states_what_it_does_not_show() -> None:
    page = PAGE.read_text(encoding="utf-8").lower()
    assert "does not show" in page and "we lost" in page  # the honest parts stay on the page


def test_every_external_link_opens_safely() -> None:
    page = PAGE.read_text(encoding="utf-8")
    for tag in re.findall(r"<a\b[^>]*\bhref\s*=\s*[\"']https?://[^>]*>", page, re.I):
        assert "noopener" in tag, tag


SITE_SRC = ROOT / "site" / "src"


def test_the_demo_files_on_the_page_are_byte_identical_to_the_committed_demo() -> None:
    # The page replays a copy of examples/demo/; if the copy drifted, its hash check would lie.
    for name in ("context.txt", "receipt.json"):
        assert (SITE_SRC / "demo" / name).read_bytes() == (
            ROOT / "examples" / "demo" / name
        ).read_bytes()


def test_the_demo_context_hashes_to_the_receipt() -> None:
    import hashlib

    receipt = json.loads((SITE_SRC / "demo" / "receipt.json").read_text(encoding="utf-8"))
    context = (SITE_SRC / "demo" / "context.txt").read_bytes()
    assert hashlib.sha256(context).hexdigest() == receipt["context_sha256"]


def test_the_page_scripts_make_no_network_calls_and_write_no_html() -> None:
    sources = list(SITE_SRC.glob("*.ts"))
    assert {p.name for p in sources} >= {"main.ts", "hero.ts", "demo.ts", "verify.ts"}
    for path in sources:
        code = path.read_text(encoding="utf-8")
        for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "innerHTML", "eval("):
            assert banned not in code, f"{path.name} uses {banned}"


HOW = ROOT / "site" / "how.html"
HOW_NUMBERS = (
    "132 pages",
    "1,011 claims",
    "1,160",
    "9,240",
    "21 ",
    "0.857",
    "0.828",
    "84.2",
    "463",
    "611",
)


def test_the_how_page_loads_only_its_own_script_and_nothing_from_elsewhere() -> None:
    page = HOW.read_text(encoding="utf-8")
    assert re.search(r"<script[^>]*\bsrc\s*=\s*[\"']/src/how\.ts", page, re.I)
    assert len(re.findall(r"<script\b", page, re.I)) == 1
    assert not re.search(r"<script[^>]*\bsrc\s*=\s*[\"']?(https?:)?//", page, re.I)
    assert not re.search(r"<link[^>]*\bhref\s*=\s*[\"']?https?:", page, re.I)
    assert not re.search(r"@import|url\(\s*[\"']?https?:", page, re.I)


def test_every_external_link_on_the_how_page_opens_safely() -> None:
    page = HOW.read_text(encoding="utf-8")
    tags = re.findall(r"<a\b[^>]*\bhref\s*=\s*[\"']https?://[^>]*>", page, re.I)
    assert tags, "the page lost its external links"
    for tag in tags:
        assert "noopener" in tag, tag


def test_every_figure_on_the_how_page_is_also_written_in_the_repository_docs() -> None:
    page = html.unescape(HOW.read_text(encoding="utf-8"))
    docs = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in DOCS)
    for number in HOW_NUMBERS:
        assert number in page, f"{number!r} is no longer on the how page"
        assert number in docs, f"{number!r} is on the how page but not in README or LIMITATIONS"


def test_the_pages_name_the_other_sites_with_their_outcome() -> None:
    # The Stripe trial found no documentation error, so there is nothing to disclose first and the
    # user lifted the anonymity on 2026-11-15. Naming a vendor is only allowed next to the plain
    # outcome, so the name never reads as an accusation; Kite's safe failure must stay visible.
    for path in (PAGE, HOW):
        page = path.read_text(encoding="utf-8").lower()
        assert "stripe" in page and "found nothing to report" in page, path.name
        assert "kite" in page and "changelog" in page, path.name


def test_both_pages_state_what_is_not_built() -> None:
    page = HOW.read_text(encoding="utf-8").lower()
    assert 'id="not-built"' in page and "no key directory" in page
    # The contested-answer gap was fixed after the audit and re-audited on 2026-11-15; the page must
    # keep the v1 loss and give the v2 re-audit with its inconclusive interval, not drop either.
    assert "named neither value" in page and "answer-v2" in page and "re-audited" in page
    assert "+7.5" in page and "-11 to +26" in page


VERIFY = ROOT / "site" / "verify.html"


def test_the_receipt_check_page_uses_a_byte_identical_copy_of_the_real_receipt() -> None:
    # The page preloads examples/real/; if the copy drifted, "MATCH" would be about other text.
    import hashlib

    for name in ("context.txt", "receipt.json"):
        assert (SITE_SRC / "real" / name).read_bytes() == (
            ROOT / "examples" / "real" / name
        ).read_bytes()
    receipt = json.loads((SITE_SRC / "real" / "receipt.json").read_text(encoding="utf-8"))
    context = (SITE_SRC / "real" / "context.txt").read_bytes()
    assert hashlib.sha256(context).hexdigest() == receipt["context_sha256"]
    assert b"\r" not in context  # a textarea would turn CRLF into LF and break the match


def test_the_receipt_check_page_loads_only_its_own_script() -> None:
    page = VERIFY.read_text(encoding="utf-8")
    assert re.search(r"<script[^>]*\bsrc\s*=\s*[\"']/src/verify\.ts", page, re.I)
    assert len(re.findall(r"<script\b", page, re.I)) == 1
    assert not re.search(r"(src|href)\s*=\s*[\"']?https?:", page, re.I)
    assert "stri" + "pe" not in page.lower()


def test_the_how_page_reads_its_receipt_from_the_committed_demo_copy() -> None:
    code = (SITE_SRC / "how.ts").read_text(encoding="utf-8")
    assert 'from "./demo/receipt.json"' in code
    receipt = json.loads((SITE_SRC / "demo" / "receipt.json").read_text(encoding="utf-8"))
    assert {a["kind"] for a in receipt["actions"]} >= {"redact", "pull", "contested"}
