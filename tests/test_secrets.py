from __future__ import annotations

from pathlib import Path

import pytest

from currant import cli
from currant.config import (
    MissingSecret,
    Secret,
    all_secret_status,
    dotenv_names,
    load_secret,
    parse_dotenv,
    secret_status,
)

# Not shaped like any real key, so this file never trips the secret scan.
VALUE = "placeholder-value-for-tests"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_dotenv_handles_comments_export_quotes_and_blank_values() -> None:
    text = (
        '# a comment\n\nSERV_API_KEY=abc\nexport REPPO_API_KEY = "two words"\n'
        "A='single'\nB=plain # trailing comment\nC=\nD=a=b==\nnot a pair\n9BAD=x\n"
    )
    assert parse_dotenv(text) == {
        "SERV_API_KEY": "abc",
        "REPPO_API_KEY": "two words",
        "A": "single",
        "B": "plain",
        "C": "",
        "D": "a=b==",
    }


def test_parse_dotenv_survives_a_bom_and_windows_line_endings() -> None:
    assert parse_dotenv("\ufeffA=1\r\nB=2\r\n") == {"A": "1", "B": "2"}


def test_a_utf16_dotenv_is_read_correctly(tmp_path: Path) -> None:
    # Windows PowerShell's `>` redirect writes UTF-16; a naive reader would see garbage.
    path = tmp_path / ".env"
    path.write_bytes(f"SERV_API_KEY={VALUE}\n".encode("utf-16"))
    assert load_secret("SERV_API_KEY", env={}, dotenv_path=path).reveal() == VALUE


def test_a_utf8_bom_dotenv_is_read_correctly(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbf" + f"SERV_API_KEY={VALUE}\n".encode())
    assert load_secret("SERV_API_KEY", env={}, dotenv_path=path).reveal() == VALUE


def test_the_process_environment_beats_dotenv(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "SERV_API_KEY=from-file\n")
    secret = load_secret("SERV_API_KEY", env={"SERV_API_KEY": "from-env"}, dotenv_path=path)
    assert secret.reveal() == "from-env"


def test_dotenv_is_used_when_the_environment_has_nothing(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", f"REPPO_API_KEY={VALUE}\n")
    assert load_secret("REPPO_API_KEY", env={}, dotenv_path=path).reveal() == VALUE


def test_a_missing_secret_raises_without_leaking_anything_else(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", f"OTHER_KEY={VALUE}\n")
    with pytest.raises(MissingSecret) as raised:
        load_secret("SERV_API_KEY", env={}, dotenv_path=path)
    message = str(raised.value)
    assert "SERV_API_KEY" in message and ".env" in message
    assert VALUE not in message


def test_an_empty_value_counts_as_missing(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "SERV_API_KEY=\n")
    with pytest.raises(MissingSecret):
        load_secret("SERV_API_KEY", env={}, dotenv_path=path)
    with pytest.raises(MissingSecret):
        load_secret("SERV_API_KEY", env={"SERV_API_KEY": ""}, dotenv_path=None)


def test_a_missing_dotenv_file_is_fine_when_the_environment_has_the_key(tmp_path: Path) -> None:
    secret = load_secret(
        "SERV_API_KEY", env={"SERV_API_KEY": VALUE}, dotenv_path=tmp_path / "nope.env"
    )
    assert secret.reveal() == VALUE


def test_a_secret_never_shows_its_value_when_printed_or_formatted() -> None:
    secret = Secret("SERV_API_KEY", VALUE)
    for rendered in (repr(secret), str(secret), f"{secret}", f"{secret!r}", format(secret, "")):
        assert VALUE not in rendered
        assert "SERV_API_KEY" in rendered
    assert secret.reveal() == VALUE


def test_status_reports_source_and_length_but_never_the_value(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", f"SERV_API_KEY={VALUE}\n")
    from_file = secret_status("SERV_API_KEY", env={}, dotenv_path=path)
    assert (from_file.source, from_file.length) == (".env", len(VALUE))
    from_env = secret_status("SERV_API_KEY", env={"SERV_API_KEY": "abc"}, dotenv_path=path)
    assert (from_env.source, from_env.length) == ("environment", 3)
    unset = secret_status("SERV_API_KEY", env={}, dotenv_path=tmp_path / "nope.env")
    assert (unset.source, unset.length) == (None, 0)
    assert VALUE not in repr(from_file)


def test_loading_a_secret_does_not_write_into_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SERV_API_KEY", raising=False)
    path = write(tmp_path / ".env", f"SERV_API_KEY={VALUE}\n")
    load_secret("SERV_API_KEY", dotenv_path=path)
    import os

    assert "SERV_API_KEY" not in os.environ  # child processes must not inherit it by accident


def test_the_secrets_command_prints_presence_and_length_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for status in all_secret_status(env={}, dotenv_path=None):
        monkeypatch.delenv(status.name, raising=False)
    path = write(tmp_path / ".env", f"SERV_API_KEY={VALUE}\n")
    assert cli.main(["secrets", "--dotenv", str(path)]) == 0
    out = capsys.readouterr().out
    assert VALUE not in out
    assert "SERV_API_KEY" in out and f"{len(VALUE)} chars" in out
    assert "REPPO_API_KEY" in out and "NOT SET" in out


def test_dotenv_names_lists_names_only(tmp_path: Path) -> None:
    text = f"# c\nOPENSERV_API_KEY={VALUE}\nexport REPPO_API_KEY=x\n"
    path = write(tmp_path / ".env", text)
    names = dotenv_names(path)
    assert names == ["OPENSERV_API_KEY", "REPPO_API_KEY"]
    assert dotenv_names(tmp_path / "nope.env") == []


def test_the_secrets_command_hints_at_unknown_variables_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for status in all_secret_status(env={}, dotenv_path=None):
        monkeypatch.delenv(status.name, raising=False)
    path = write(tmp_path / ".env", f"SOME_SERVICE_TOKEN={VALUE}\n")
    assert cli.main(["secrets", "--dotenv", str(path)]) == 0
    out = capsys.readouterr().out
    assert "SOME_SERVICE_TOKEN" in out and VALUE not in out
    assert "SERV_API_KEY" in out and "NOT SET" in out


def test_the_longer_openserv_name_is_accepted_as_an_alias(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", f"OPENSERV_API_KEY={VALUE}\n")
    assert load_secret("SERV_API_KEY", env={}, dotenv_path=path).reveal() == VALUE
    from_env = load_secret("SERV_API_KEY", env={"OPENSERV_API_KEY": "e"}, dotenv_path=None)
    assert from_env.reveal() == "e"


def test_the_canonical_name_wins_over_its_alias(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "OPENSERV_API_KEY=alias\nSERV_API_KEY=canonical\n")
    assert load_secret("SERV_API_KEY", env={}, dotenv_path=path).reveal() == "canonical"
    env = {"SERV_API_KEY": "env-canonical", "OPENSERV_API_KEY": "env-alias"}
    assert load_secret("SERV_API_KEY", env=env, dotenv_path=None).reveal() == "env-canonical"


def test_status_says_which_name_the_key_was_found_under(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", f"OPENSERV_API_KEY={VALUE}\n")
    status = secret_status("SERV_API_KEY", env={}, dotenv_path=path)
    assert (status.source, status.found_as, status.length) == (
        ".env",
        "OPENSERV_API_KEY",
        len(VALUE),
    )
    assert secret_status("SERV_API_KEY", env={}, dotenv_path=None).found_as is None
