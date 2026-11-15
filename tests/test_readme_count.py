"""The README states the test count in several places; they must all equal the real count.

The real count is only known on a run of the whole suite, so on a partial run (`pytest -k`, one
file) this test checks only that the README's copies agree with each other."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import COLLECTED

ROOT = Path(__file__).resolve().parent.parent
COUNTS = (
    r"tests-(\d+)%20passing",
    r"\*\*(\d+) tests pass, all offline",
    r"\| \*\*(\d+)\*\* +\| tests, all offline",
    r"`pytest` \((\d+) tests\)",
)


def stated() -> list[int]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    found = []
    for pattern in COUNTS:
        match = re.search(pattern, readme)
        assert match, f"the README no longer states the test count as {pattern!r}"
        found.append(int(match.group(1)))
    return found


def test_the_readme_states_one_test_count_and_it_is_the_real_one(
    request: pytest.FixtureRequest,
) -> None:
    counts = stated()
    assert len(set(counts)) == 1, f"the README gives different test counts: {counts}"
    total, files = request.config.stash[COLLECTED]
    every_file = frozenset(p.resolve() for p in (ROOT / "tests").glob("test_*.py"))
    if frozenset(p.resolve() for p in files) == every_file:
        assert counts[0] == total, f"README says {counts[0]} tests, the suite has {total}"
