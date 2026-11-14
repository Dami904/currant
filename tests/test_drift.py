from __future__ import annotations

from pathlib import Path

import pytest

from currant import cli
from currant.drift import drift_report
from tests.test_cli_ground import to_disk
from tests.test_ground import S10, S50, S70, T10, T50, T70, U1, U2, U3, World


def drifting() -> World:
    world = World(
        (U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"), (U3, T70, S70, 70, "current")
    )
    world.supersede(U2, U1, "This replaces the previous value of 10 in earlier documentation.")
    world.contradict(U2, U3)
    world.finish()
    return world


def test_the_report_quotes_both_sides_of_every_finding_and_says_it_is_unconfirmed() -> None:
    world = drifting()
    text = drift_report(world.store, world.extract, world.relate)
    assert "UNCONFIRMED" in text and "Replaced values (1)" in text
    assert "Conflicts with no order (1)" in text
    for url in (U1, U2, U3):
        assert url in text
    assert f"Older: “{S10}”" in text and f"Newer: “{S50}”" in text
    assert (
        text.count("Ordering evidence (ordering)") == 1 and "Ordering evidence (older)" not in text
    )
    conflicts = text.split("## Conflicts")[1]  # which side is A is not meaningful, both are shown
    assert S50 in conflicts and S70 in conflicts


def test_a_run_of_the_wrong_kind_or_snapshot_is_refused() -> None:
    world = drifting()
    with pytest.raises(ValueError, match="extract run and a relate run"):
        drift_report(world.store, world.relate, world.extract)
    unfinished = World((U1, T10, S10, 10, "current"), (U2, T50, S50, 50, "current"))
    with pytest.raises(
        ValueError, match="did not complete"
    ):  # a partial report reads as "no drift"
        drift_report(unfinished.store, unfinished.extract, unfinished.relate)


def test_the_command_writes_only_under_the_private_directory_unless_told_to_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # docs/private is relative to the working directory
    db = to_disk(drifting(), tmp_path / "c.db")
    world = drifting()
    common = ["drift-report", "--db", str(db), "--extract-run", str(world.extract)]
    common += ["--relate-run", str(world.relate)]
    elsewhere = tmp_path / "public" / "drift.md"
    sneaky = Path("docs") / "private" / ".." / "escaped.md"  # starts inside, ends outside
    assert cli.main([*common, "--out", str(sneaky)]) == 2 and not Path("docs/escaped.md").exists()
    capsys.readouterr()
    assert cli.main([*common, "--out", str(elsewhere)]) == 2
    assert "private" in capsys.readouterr().err and not elsewhere.exists()
    inside = Path("docs") / "private" / "drift.md"
    assert cli.main([*common, "--out", str(inside)]) == 0 and inside.exists()
    assert cli.main([*common]) == 0 and (Path("docs/private") / "drift-report.md").exists()
    assert cli.main([*common, "--out", str(elsewhere), "--publish"]) == 0 and elsewhere.exists()
