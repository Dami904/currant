from __future__ import annotations

from pathlib import Path

import pytest

from currant.guardrails import MAX_SOURCE_LINES, check, main, scan

REPO = Path(__file__).parents[1]

# Rule-trigger strings are assembled at runtime so this file does not trip its own scan.
SKIP_MARK = "pytest.mark." + "skip"
XFAIL_MARK = "pytest.mark." + "xfail"
TYPE_IGNORE = "# type: " + "ignore[arg-type]"
BARE_NOQA = "# no" + "qa"
CODED_NOQA = "# no" + "qa: E501"


def tree(root: Path, files: dict[str, str]) -> Path:
    files = {".gitignore": ".env\n", **files}
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def flagged(root: Path) -> str:
    return "\n".join(check(root))


def test_this_repo_passes_its_own_guardrails() -> None:
    assert check(REPO) == []


def test_clean_tree_passes(tmp_path: Path) -> None:
    assert check(tree(tmp_path, {"src/currant/a.py": "x = 1\n"})) == []


# --- secrets -----------------------------------------------------------------------------


def test_secret_env_name_outside_config_is_flagged(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/currant/client.py": "key = lookup('SERV_API_KEY')\n"})
    violations = check(root)
    assert len(violations) == 1
    assert "src/currant/client.py" in violations[0] and "SERV_API_KEY" in violations[0]


def test_the_openserv_alias_name_is_guarded_too(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/currant/client.py": "key = lookup('OPENSERV_API_KEY')\n"})
    assert "OPENSERV_API_KEY" in flagged(root)


def test_secret_env_name_in_config_tests_and_docs_is_allowed(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "src/currant/config.py": "import os\nos.environ['SERV_API_KEY']\n",
            "tests/test_x.py": "SERV_API_KEY = 'set in test'\n",
            "README.md": "export SERV_API_KEY=...\n",
        },
    )
    assert check(root) == []


@pytest.mark.parametrize(
    "snippet",
    ["import os\nx = os.environ['HOME']\n", "import os\nx = os.getenv('HOME')\n"],
)
def test_reading_the_environment_outside_config_is_flagged(tmp_path: Path, snippet: str) -> None:
    root = tree(tmp_path, {"src/currant/thing.py": snippet})
    assert "src/currant/thing.py" in flagged(root) and "environment" in flagged(root)


def test_secret_shaped_strings_are_flagged(tmp_path: Path) -> None:
    # Built at runtime so this test file does not itself trip the scan.
    wallet_key = "0x" + "ab" * 32
    pem = "-----BEGIN " + "RSA PRIVATE KEY-----"
    api_key = "sk-" + "A1b2C3d4" * 4
    root = tree(
        tmp_path,
        {"docs/a.md": wallet_key, "docs/b.md": pem, "src/currant/c.py": f"K = '{api_key}'"},
    )
    text = flagged(root)
    assert "docs/a.md" in text and "wallet key" in text
    assert "docs/b.md" in text and "private key block" in text
    assert "src/currant/c.py" in text and "sk- style" in text


def test_cloud_and_github_token_shapes_are_flagged(tmp_path: Path) -> None:
    aws = "AKIA" + "ABCDEFGHIJKLMNOP"
    github = "ghp_" + "a" * 36
    root = tree(tmp_path, {"docs/aws.md": aws, "docs/gh.md": github})
    text = flagged(root)
    assert "docs/aws.md" in text and "AWS access key" in text
    assert "docs/gh.md" in text and "GitHub token" in text


def test_dotenv_variants_are_never_read_except_the_example(tmp_path: Path) -> None:
    secret = "0x" + "ab" * 32
    root = tree(tmp_path, {".env.local": secret, ".env.production": secret, ".env": secret})
    assert check(root) == []  # not read, so not even scanned
    (root / ".env.example").write_text(secret, encoding="utf-8")
    assert ".env.example" in flagged(root)  # the example is committed, so it is checked


def test_only_the_top_level_snapshots_dir_is_skipped(tmp_path: Path) -> None:
    secret = "0x" + "ab" * 32
    root = tree(
        tmp_path,
        {"snapshots/2026-11-05/pages/x.md": secret, "data/export.txt": secret},
    )
    assert check(root) == []  # crawled third-party text and the rebuildable store are not scanned
    (root / "src" / "currant" / "snapshots").mkdir(parents=True)
    (root / "src" / "currant" / "snapshots" / "leak.py").write_text(secret, encoding="utf-8")
    assert "src/currant/snapshots/leak.py" in flagged(root)


def test_files_that_cannot_be_scanned_are_reported_not_silently_skipped(tmp_path: Path) -> None:
    root = tree(tmp_path, {})
    (root / "big.txt").write_text("x" * 1_100_000, encoding="utf-8")
    result = scan(root)
    assert result.violations == []
    assert "big.txt" in "\n".join(result.notes)


def test_gitignore_must_ignore_dotenv(tmp_path: Path) -> None:
    root = tree(tmp_path, {})
    (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    assert ".gitignore" in flagged(root)
    (root / ".gitignore").unlink()
    assert ".gitignore" in flagged(root)


# --- network and hygiene rules -----------------------------------------------------------


def test_http_clients_may_only_be_built_in_the_cli_or_live_scripts(tmp_path: Path) -> None:
    client = "import httpx\nc = httpx.Client()\n"
    root = tree(
        tmp_path,
        {
            "src/currant/cli/pipeline.py": client,
            "scripts/live_smoke.py": client,
            "tests/test_x.py": client,
            "src/currant/crawl/sneaky.py": client,
            "src/currant/cli.py": client,  # the old single-file path is no longer allowed
            "src/currant/clix/a.py": client,  # nor a sibling whose name merely starts with cli
            "scripts/other.py": "import urllib.request\nurllib.request.urlopen('http://x')\n",
        },
    )
    # Compare the flagged *paths*: the message itself names the cli package as the allowed place.
    assert {v.split(":")[0] for v in check(root)} == {
        "src/currant/crawl/sneaky.py",
        "src/currant/cli.py",
        "src/currant/clix/a.py",
        "scripts/other.py",
    }


def test_a_source_file_over_the_line_cap_is_flagged(tmp_path: Path) -> None:
    at_cap = "x = 1\n" * MAX_SOURCE_LINES
    root = tree(
        tmp_path,
        {
            "src/currant/fine.py": at_cap,
            "src/currant/big.py": at_cap + "y = 2\n",
            "tests/test_long.py": at_cap + "y = 2\n",  # tests are exempt: tables of cases
        },
    )
    assert {v.split(":")[0] for v in check(root)} == {"src/currant/big.py"}
    assert "lines" in flagged(root)


@pytest.mark.parametrize(
    ("snippet", "label"),
    [
        (f"{SKIP_MARK}\ndef test_a(): ...\n", "skipped"),
        (f"{XFAIL_MARK}\ndef test_a(): ...\n", "skipped"),
        (f"x: int = 'a'  {TYPE_IGNORE}\n", "type-check"),
        (f"import os  {BARE_NOQA}\n", "lint"),
    ],
)
def test_suppressed_failures_are_flagged(tmp_path: Path, snippet: str, label: str) -> None:
    root = tree(tmp_path, {"tests/test_a.py": snippet})
    text = flagged(root)
    assert "tests/test_a.py" in text and label in text


def test_a_specific_lint_exemption_with_a_code_is_allowed(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/currant/a.py": f"x = 1  {CODED_NOQA}\n"})
    assert check(root) == []


def test_main_exit_codes_and_notes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = tree(tmp_path / "clean", {})
    dirty = tree(tmp_path / "dirty", {"src/currant/x.py": "REPPO_API_KEY"})
    (clean / "big.txt").write_text("x" * 1_100_000, encoding="utf-8")
    assert main([str(clean)]) == 0
    assert "NOT SCANNED" in capsys.readouterr().out
    assert main([str(dirty)]) == 1


# --- evaluation labels never reach the pipeline -------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "src/currant/extract.py",
        "src/currant/store.py",
        "src/currant/serv.py",
        "src/currant/config.py",
        "src/currant/crawl/runner.py",
        "src/currant/detect.py",
        "src/currant/ground.py",
        "src/currant/receipt.py",
        "src/currant/llmcache.py",
        "src/currant/obs.py",
        "src/currant/retrieve.py",
        "src/currant/harness/answer.py",
        "src/currant/harness/stats.py",
    ],
)
@pytest.mark.parametrize(
    "line",
    [
        "from currant.evalset import EvalStore",
        "import currant.evalset",
        "from currant import evalset",
        "from currant import obs, evalset",
    ],
)
def test_pipeline_modules_may_not_import_the_evaluation_store(
    tmp_path: Path, path: str, line: str
) -> None:
    root = tree(tmp_path, {path: f"{line}\nx = 1\n"})
    assert "evaluation store" in flagged(root) and path in flagged(root)


def test_the_cli_the_harness_and_tests_may_import_it(tmp_path: Path) -> None:
    line = "from currant.evalset import EvalStore\n"
    root = tree(
        tmp_path,
        {
            "src/currant/cli/evaluation.py": line,
            "src/currant/evalset.py": "x = 1\n",
            "src/currant/harness/run.py": line,
            "tests/test_x.py": line,
        },
    )
    assert check(root) == []


def test_mentioning_the_word_in_a_comment_is_not_an_import(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/currant/store.py": "# labels live in evalset, not here\nx = 1\n"})
    assert check(root) == []


@pytest.mark.parametrize(
    "call",
    ["store.label(item_id)", "evals.labels('dev')", "self._evals.label (x)", "EvalStore.labels(s)"],
)
@pytest.mark.parametrize(
    "runner", ["src/currant/harness/run_items.py", "src/currant/harness/arms.py"]
)
def test_the_item_runner_may_not_read_labels(tmp_path: Path, call: str, runner: str) -> None:
    # These import ItemRow, so the import ban cannot cover them.
    root = tree(tmp_path, {runner: f"x = {call}" + chr(10)})
    assert "item runner" in flagged(root)


def test_the_item_runner_may_import_the_item_type_and_other_harness_files_may_read_labels(
    tmp_path: Path,
) -> None:
    root = tree(
        tmp_path,
        {
            "src/currant/harness/run_items.py": "from currant.evalset import ItemRow" + chr(10),
            "src/currant/harness/score.py": "y = evals.label(i)" + chr(10),
        },
    )
    assert check(root) == []


# --- binary files, private notes, and the item runner ----------------------------------------


def test_a_binary_file_is_scanned_for_key_shapes_not_skipped(tmp_path: Path) -> None:
    root = tree(tmp_path, {})
    blob = bytes([0xFF, 0xFE, 0x00, 0x80]) + b"ghp_" + b"A" * 36 + bytes([0x00])
    (root / "examples").mkdir()
    (root / "examples" / "store.db").write_bytes(blob)
    assert "examples/store.db" in flagged(root)


def test_a_clean_binary_file_passes_without_a_note(tmp_path: Path) -> None:
    root = tree(tmp_path, {})
    (root / "store.db").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80]) + b"just rows")
    result = scan(root)
    assert result.violations == [] and result.notes == []


@pytest.mark.parametrize(
    "phrase", ["not for publication", "Not For Publication", "NOT FOR PUBLICATION"]
)
def test_a_tracked_doc_may_not_be_marked_not_for_publication(tmp_path: Path, phrase: str) -> None:
    root = tree(tmp_path, {"docs/NOTES.md": f"These are internal notes, {phrase}.\n"})
    assert "docs/NOTES.md" in flagged(root) and "docs/private" in flagged(root)


def test_the_private_directory_may_hold_such_notes_if_it_is_ignored(tmp_path: Path) -> None:
    root = tree(tmp_path, {"docs/private/DRIFT.md": "not for publication\n"})
    gitignore = root / ".gitignore"
    gitignore.write_text(
        gitignore.read_text(encoding="utf-8") + "docs/private/\n", encoding="utf-8"
    )
    assert check(root) == []


def test_a_private_directory_that_is_not_ignored_is_flagged(tmp_path: Path) -> None:
    root = tree(tmp_path, {"docs/private/DRIFT.md": "notes\n"})
    assert "must ignore docs/private/" in flagged(root)


@pytest.mark.parametrize(
    "call",
    [
        "x = _read_label(store, i)",
        "x = getattr(store, 'label')(i)",
        "x = conn.execute('SELECT * FROM labels')",
    ],
)
def test_the_item_runner_may_not_reach_labels_by_other_routes(tmp_path: Path, call: str) -> None:
    root = tree(tmp_path, {"src/currant/harness/run_items.py": call + chr(10)})
    assert "item runner" in flagged(root)


def test_binary_bytes_that_spell_a_secret_name_are_not_mistaken_for_code(tmp_path: Path) -> None:
    # Only the key-shape scan applies to binary files; the text rules (env names in src/) must not.
    root = tree(tmp_path, {})
    (root / "src" / "currant").mkdir(parents=True)
    (root / "src" / "currant" / "blob.bin").write_bytes(
        bytes([0xFF, 0x00]) + b"REPPO_API_KEY os.environ"
    )
    assert check(root) == []
