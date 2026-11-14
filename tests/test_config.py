from pathlib import Path

import pytest

from currant.crawl.config import ConfigError, load_config, parse_config

GOOD = """
[[corpus]]
name = "docs"
indexes = ["https://docs.example.com/llms.txt"]
allow = ["https://docs.example.com/"]
pages = ["https://docs.example.com/a.md"]
"""


def test_committed_config_loads() -> None:
    corpora = load_config(Path(__file__).parents[1] / "corpora.toml")
    assert [c.name for c in corpora] == ["openserv", "reppo", "kite"]
    assert [c.enabled for c in corpora] == [True, True, False]


def test_defaults() -> None:
    (corpus,) = parse_config(GOOD)
    assert corpus.enabled is True
    assert corpus.max_pages == 500


@pytest.mark.parametrize("name", ["../escape", "Has Caps", "a/b", "", "-lead"])
def test_corpus_name_cannot_traverse_paths(name: str) -> None:
    with pytest.raises(ConfigError, match="corpus name"):
        parse_config(GOOD.replace('"docs"', f'"{name}"'))


def test_page_outside_allow_list_is_rejected() -> None:
    bad = GOOD.replace("https://docs.example.com/a.md", "https://evil.example.org/a.md")
    with pytest.raises(ConfigError, match="outside its allow list"):
        parse_config(bad)


def test_duplicate_names_and_bad_limits_are_rejected() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config(GOOD + GOOD)
    with pytest.raises(ConfigError, match="max_pages"):
        parse_config(GOOD + "max_pages = 0\n")
    with pytest.raises(ConfigError, match="no \\[\\[corpus\\]\\]"):
        parse_config("x = 1")
    with pytest.raises(ConfigError, match="invalid TOML"):
        parse_config("[[corpus")


def test_empty_allow_list_is_rejected() -> None:
    with pytest.raises(ConfigError, match="allow must not be empty"):
        parse_config(GOOD.replace('allow = ["https://docs.example.com/"]', "allow = []"))


def test_max_pages_rejects_booleans() -> None:
    with pytest.raises(ConfigError, match="max_pages"):
        parse_config(GOOD + "max_pages = true\n")


def test_enabled_must_be_a_boolean() -> None:
    with pytest.raises(ConfigError, match="enabled"):
        parse_config(GOOD + 'enabled = "yes"\n')
