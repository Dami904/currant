from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from currant import cli
from currant.evalset import EvalLocked, EvalStore
from currant.harness.real_items import import_worksheet, make_worksheet
from tests.test_cli_ground import to_disk
from tests.test_ground import R10, S10, S50, S70, T10, T50, T70, U1, U2, U3, World

DATED_OLD = "Last updated: 2026-03-14"
DATED_NEW = "Updated 2026-09-02"


def world(*, dated: bool = False) -> World:
    old = f"{DATED_OLD}\n\n{T10}" if dated else T10
    new = f"{DATED_NEW}\n\n{T50}" if dated else T50
    w = World((U1, old, S10, 10, "current"), (U2, new, S50, 50, "current"),
              (U3, T70, S70, 70, "current"))  # fmt: skip
    w.finish()
    return w


def item_for(sheet: dict[str, Any], newer: str, older: str) -> dict[str, Any]:
    """The worksheet item pairing these two urls, and which side (a or b) holds the newer one."""
    for item in sheet["items"]:
        urls = {item["a"]["url"]: "a", item["b"]["url"]: "b"}
        if newer in urls and older in urls:
            return {**item, "_newer": urls[newer]}
    raise AssertionError("no candidate pair for those pages")


def load(w: World) -> tuple[dict[str, Any], EvalStore]:
    return make_worksheet(w.store, w.extract), EvalStore(":memory:")


# --- the worksheet -------------------------------------------------------------------------------


def test_the_worksheet_proposes_pairs_with_their_quotes_and_shows_no_detector_verdict() -> None:
    w = world()
    sheet = make_worksheet(w.store, w.extract)
    assert sheet["extract_run"] == w.extract and sheet["instructions"]
    item = item_for(sheet, U2, U1)
    assert {item["a"]["quote"], item["b"]["quote"]} == {S10, S50}
    assert {item["a"]["number"], item["b"]["number"]} == {10, 50}
    assert item["verdict"] == "" and item["question"].startswith("What is the free evaluations")
    # the detector's verdict is not offered to the person who labels: only the candidate stage runs
    assert set(item) == {  # exactly these fields: nothing the detector concluded is among them
        "id", "question", "cluster", "seen", "a", "b", "verdict", "ordering_quote",
        "date_quote_newer", "date_quote_older", "note", "_claims", "_newer",
    }  # fmt: skip
    assert set(item["a"]) == {"url", "quote", "value", "number", "page_date"}
    assert len(make_worksheet(w.store, w.extract, max_items=1)["items"]) == 1


# --- importing a labelled worksheet --------------------------------------------------------------


def test_an_explicit_replacement_becomes_a_sealed_heldout_item_with_the_right_label() -> None:
    w = world()
    sheet, evals = load(w)
    item = item_for(sheet, U2, U1)
    item.update(verdict=f"{item['_newer']}_newer_explicit", ordering_quote=R10)
    sheet["items"] = [{k: v for k, v in item.items() if k != "_newer"}]
    report = import_worksheet(w.store, w.extract, evals, sheet)
    assert (report.added, report.problems) == (1, [])
    (row,) = evals.items()
    assert row.kind == "real" and row.split == "heldout"
    assert [p["url"] for p in row.spec["pages"]] and "label" not in json.dumps(row.spec)
    with pytest.raises(EvalLocked):
        evals.label(row.item_id)  # sealed until the freeze
    evals.freeze("test")
    label = evals.label(row.item_id)
    assert label["scenario"] == "supersedes_explicit" and label["expected_state"] == "CANON"
    assert (label["stale_value_number"], label["current_value_number"]) == (10, 50)
    stale = next(p for p in row.spec["pages"] if p["id"] == label["stale_page_id"])
    start, end = label["stale_span"]
    assert stale["url"] == U1 and stale["text"][start:end] == S10


def test_a_dated_pair_is_checked_by_our_code_and_a_contested_one_needs_no_quote() -> None:
    w = world(dated=True)
    sheet, evals = load(w)
    dated = item_for(sheet, U2, U1)
    dated.update(
        verdict=f"{dated['_newer']}_newer_dated",
        date_quote_newer=DATED_NEW,
        date_quote_older=DATED_OLD,
    )
    contested = item_for(sheet, U3, U2)
    contested.update(verdict="contested", seen=True, cluster="real-other")
    sheet["items"] = [dated, contested]
    report = import_worksheet(w.store, w.extract, evals, sheet)
    assert (report.added, report.problems) == (2, [])
    by_split = {i.split for i in evals.items()}
    assert by_split == {"heldout", "dev"}  # a pair you studied first is dev, never held out
    evals.freeze("test")
    scenarios = {evals.label(i.item_id)["scenario"] for i in evals.items()}
    assert scenarios == {"supersedes_dated", "contested_implicit"}
    contested_label = next(
        evals.label(i.item_id)
        for i in evals.items()
        if evals.label(i.item_id)["expected_state"] == "CONTESTED"
    )
    assert contested_label["current_value_number"] is None


@pytest.mark.parametrize(
    ("fill", "reason"),
    [
        (
            {"verdict": "a_newer_explicit", "ordering_quote": "This sentence is invented."},
            "word for word",
        ),
        ({"verdict": "a_newer_explicit", "ordering_quote": ""}, "word for word"),
        (
            {
                "verdict": "a_newer_dated",
                "date_quote_newer": DATED_OLD,
                "date_quote_older": DATED_NEW,
            },
            "not after",
        ),
        (
            {
                "verdict": "a_newer_dated",
                "date_quote_newer": "No date here",
                "date_quote_older": DATED_OLD,
            },
            "word for word",
        ),
        (
            {
                "verdict": "a_newer_dated",
                "date_quote_newer": "# Limits",
                "date_quote_older": DATED_NEW,
            },
            "no ISO date",
        ),
        ({"verdict": "maybe"}, "unknown verdict"),
        ({"verdict": "contested", "question": "  "}, "question is empty"),
    ],
)
def test_a_wrong_or_unverifiable_label_is_refused_not_sealed(
    fill: dict[str, Any], reason: str
) -> None:
    w = world(dated=True)
    sheet, evals = load(w)
    item = item_for(sheet, U2, U1)
    newer = item.pop("_newer")
    if str(fill["verdict"]).startswith("a_"):  # say it about the side that is really the OLDER page
        fill = {
            **fill,
            "verdict": fill["verdict"].replace("a_", f"{'b' if newer == 'a' else 'a'}_"),
        }
    sheet["items"] = [{**item, **fill}]
    report = import_worksheet(w.store, w.extract, evals, sheet)
    assert report.added == 0 and evals.items() == []
    assert len(report.problems) == 1 and reason in report.problems[0]


def test_unlabelled_pairs_and_non_conflicts_are_skipped_and_a_duplicate_is_refused() -> None:
    w = world()
    sheet, evals = load(w)
    first = {**item_for(sheet, U2, U1), "verdict": "contested"}
    first.pop("_newer")
    sheet["items"] = [
        {**sheet["items"][0], "verdict": ""},
        {**sheet["items"][1], "verdict": "not_a_conflict"},
        first,
        {**first, "id": "again"},
    ]
    report = import_worksheet(w.store, w.extract, evals, sheet)
    assert report.added == 1 and len(report.skipped) == 2
    assert len(report.problems) == 1 and "already exists" in report.problems[0]


def test_nothing_can_be_imported_after_the_freeze() -> None:
    w = world()
    sheet, evals = load(w)
    evals.freeze("closed")
    item = {**sheet["items"][0], "verdict": "contested"}
    sheet["items"] = [item]
    report = import_worksheet(w.store, w.extract, evals, sheet)
    assert report.added == 0 and "closed after the freeze" in report.problems[0]


# --- the commands --------------------------------------------------------------------------------


def test_the_commands_round_trip_and_the_worksheet_stays_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    w = world()
    db = to_disk(w, tmp_path / "c.db")
    common = ["--db", str(db), "--extract-run", str(w.extract)]
    assert cli.main(["real-worksheet", *common, "--out", str(tmp_path / "public.json")]) == 2
    assert "private" in capsys.readouterr().err and not (tmp_path / "public.json").exists()
    assert cli.main(["real-worksheet", *common]) == 0
    path = Path("docs/private/real-worksheet.json")
    sheet = json.loads(path.read_text(encoding="utf-8"))
    sheet["items"][0]["verdict"] = "contested"
    path.write_text(json.dumps(sheet), encoding="utf-8")
    evalset = tmp_path / "evals.db"
    assert cli.main(["real-import", "--db", str(db), "--evalset", str(evalset)]) == 0
    out = capsys.readouterr().out
    assert "added 1 real items" in out and "commit root:" in out and "BEFORE" in out
    with EvalStore(evalset) as evals:
        assert [i.kind for i in evals.items()] == ["real"]


# --- labelling at the terminal -------------------------------------------------------------------


def scripted(answers: list[str]) -> tuple[Any, list[str]]:
    shown: list[str] = []
    queue = iter(answers)
    return (lambda _prompt: next(queue)), shown


def test_the_labeller_checks_pasted_quotes_at_once_and_saves_after_every_answer() -> None:
    from currant.harness.real_items import label_session

    w = world()
    sheet, _evals = load(w)
    sheet["items"] = [item_for(sheet, U2, U1), item_for(sheet, U3, U2)]
    newer = sheet["items"][0].pop("_newer")
    sheet["items"][1].pop("_newer")
    saves: list[str] = []
    ask, shown = scripted(
        [newer, "an invented sentence", newer, R10, "n", "q"]  # a bad quote is refused, then redone
    )
    counts = label_session(
        w.store, w.extract, sheet, ask, shown.append, lambda ws: saves.append(json.dumps(ws))
    )
    assert counts == {"labelled": 2, "skipped": 0, "left": 0}  # "n" is a label too: no item
    first = sheet["items"][0]
    assert first["verdict"] == f"{newer}_newer_explicit" and first["ordering_quote"] == R10
    assert any("not accepted" in line and "word for word" in line for line in shown)
    assert len(saves) == 2 and sheet["items"][1]["verdict"] == "not_a_conflict"  # each saved


def test_the_labeller_asks_again_for_an_unknown_key_and_skips_without_saving() -> None:
    from currant.harness.real_items import label_session

    w = world()
    sheet, _evals = load(w)
    sheet["items"] = [{k: v for k, v in item_for(sheet, U2, U1).items() if k != "_newer"}]
    saves: list[Any] = []
    ask, shown = scripted(["zzz", "s"])
    counts = label_session(w.store, w.extract, sheet, ask, shown.append, saves.append)
    assert counts == {"labelled": 0, "skipped": 1, "left": 0} and saves == []
    assert any("choose a, b, da, db" in line for line in shown)
    assert sheet["items"][0]["verdict"] == ""
