from __future__ import annotations

import io
import sys
from pathlib import Path

import httpx
import pytest

from currant import cli
from tests.helpers import md

REAL_CLIENT = httpx.Client  # captured before any monkeypatching

CONFIG = """
[[corpus]]
name = "docs"
indexes = ["https://docs.example.com/llms.txt"]
allow = ["https://docs.example.com/"]
pages = ["https://docs.example.com/a.md"]
max_pages = {max_pages}
"""


def patch_network(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    def factory(
        *, headers: dict[str, str], timeout: httpx.Timeout, follow_redirects: bool
    ) -> httpx.Client:
        return REAL_CLIENT(
            transport=handler, headers=headers, timeout=timeout, follow_redirects=follow_redirects
        )

    monkeypatch.setattr("currant.cli.httpx.Client", factory)


@pytest.fixture
def no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a run gets as far as building an HTTP client."""

    def forbidden(**_kwargs: object) -> httpx.Client:
        raise AssertionError("an HTTP client was built; a guard that should stop the run is gone")

    monkeypatch.setattr("currant.cli.httpx.Client", forbidden)


def write_config(tmp_path: Path, max_pages: int = 500) -> Path:
    path = tmp_path / "corpora.toml"
    path.write_text(CONFIG.format(max_pages=max_pages), encoding="utf-8")
    return path


def two_page_site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/llms.txt":
        return md("- [A](/a.md)\n- [B](/b.md)\n")
    return md("# page\n")


def test_crawl_then_verify_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_network(monkeypatch, httpx.MockTransport(two_page_site))
    out = tmp_path / "snaps"
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(out)]
    assert cli.main([*argv, "--date", "2026-11-05", "--delay", "0"]) == 0

    printed = capsys.readouterr().out
    assert "corpus_hash:" in printed and "complete:    yes" in printed
    log = (out / "2026-11-05" / "crawl.log.jsonl").read_text(encoding="utf-8")
    assert "crawl_done" in log

    assert cli.main(["verify", str(out / "2026-11-05")]) == 0
    assert "OK" in capsys.readouterr().out


def test_crawl_exits_nonzero_when_a_page_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return md("- [A](/a.md)\n") if request.url.path == "/llms.txt" else httpx.Response(503)

    patch_network(monkeypatch, httpx.MockTransport(handler))
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(tmp_path / "s")]
    assert cli.main([*argv, "--date", "2026-11-05", "--delay", "0", "--max-attempts", "1"]) == 1


def test_truncation_fails_the_run_unless_explicitly_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_network(monkeypatch, httpx.MockTransport(two_page_site))
    config = str(write_config(tmp_path, max_pages=1))  # a.md is configured, b.md gets dropped
    argv = ["crawl", "--config", config, "--out", str(tmp_path / "s"), "--delay", "0"]

    assert cli.main([*argv, "--date", "2026-11-05"]) == 1
    assert "page cap reached" in capsys.readouterr().out
    assert cli.main([*argv, "--date", "2026-11-06", "--allow-truncation"]) == 0

    snapshot = str(tmp_path / "s" / "2026-11-06")
    assert cli.main(["verify", snapshot]) == 1  # a truncated snapshot is not clean...
    assert cli.main(["verify", snapshot, "--allow-unreconciled"]) == 0  # ...unless you say so


@pytest.mark.parametrize(
    "bad_date",
    [
        "11/05/2026",
        "../../evil",
        "2026-13-45",
        "٢٠٢٦-11-05",
        "2026-11-05\n",
        "20261105",  # valid ISO 8601, and accepted by date.fromisoformat, but not our format
        "2026-W45-3",  # ISO week date: same
    ],
)
def test_bad_dates_exit_2_before_anything_is_built_or_written(
    tmp_path: Path, no_client: None, bad_date: str
) -> None:
    out = tmp_path / "out"
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(out), "--date", bad_date]
    assert cli.main(argv) == 2
    assert not out.exists()


def test_bad_config_and_unknown_corpus_exit_2(
    tmp_path: Path, no_client: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = str(tmp_path / "out")
    config = str(write_config(tmp_path))
    assert cli.main(["crawl", "--config", str(tmp_path / "missing.toml"), "--out", out]) == 2
    assert cli.main(["crawl", "--config", config, "--out", out, "--corpus", "nope"]) == 2
    bad = tmp_path / "bad.toml"
    bad.write_text("[[corpus]]\nname = '../x'\n", encoding="utf-8")
    assert cli.main(["crawl", "--config", str(bad), "--out", out]) == 2
    err = capsys.readouterr().err
    assert "unknown corpus" in err and "config error" in err


@pytest.mark.parametrize("flag", [["--max-attempts", "0"], ["--delay", "-1"]])
def test_invalid_numeric_options_are_rejected_by_argparse(
    tmp_path: Path, no_client: None, flag: list[str]
) -> None:
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(tmp_path / "o"), *flag]
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2


def test_an_unwritable_output_location_exits_2_instead_of_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_network(monkeypatch, httpx.MockTransport(two_page_site))
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(blocker)]
    assert cli.main([*argv, "--date", "2026-11-05"]) == 2
    assert "error:" in capsys.readouterr().err


def test_a_corrupt_manifest_exits_2_and_is_left_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_network(monkeypatch, httpx.MockTransport(two_page_site))
    snapshot = tmp_path / "s" / "2026-11-05"
    snapshot.mkdir(parents=True)
    (snapshot / "manifest.json").write_text("{not json", encoding="utf-8")
    argv = ["crawl", "--config", str(write_config(tmp_path)), "--out", str(tmp_path / "s")]
    assert cli.main([*argv, "--date", "2026-11-05", "--delay", "0"]) == 2
    assert (snapshot / "manifest.json").read_text(encoding="utf-8") == "{not json"
    assert "not modified" in capsys.readouterr().err


def test_verify_fails_on_empty_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["verify", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_page_quote_the_console_cannot_encode_is_printed_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seen when labelling real items: a cp1252 Windows console crashed on an arrow in a quote.
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    cli._tolerate_console_encoding()
    print("sentence → and a cent sign ¢ and 中")
    console.flush()
    assert raw.getvalue().startswith(b"sentence ")
