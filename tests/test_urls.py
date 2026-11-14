import pytest

from currant.crawl.urls import canonicalize, is_allowed


def test_canonicalize_normalises_case_port_fragment_and_userinfo() -> None:
    assert (
        canonicalize("HTTPS://User:pw@Docs.Example.com:443/a/b.md?x=1#frag")
        == "https://docs.example.com/a/b.md?x=1"
    )
    assert canonicalize("http://example.com:80") == "http://example.com/"
    assert canonicalize("https://example.com:8443/x") == "https://example.com:8443/x"


@pytest.mark.parametrize(
    "bad", ["mailto:a@b.c", "javascript:alert(1)", "/relative", "", "ftp://x/y"]
)
def test_canonicalize_rejects_non_http(bad: str) -> None:
    with pytest.raises(ValueError):
        canonicalize(bad)


def test_is_allowed_matches_prefix_only() -> None:
    allow = ["https://docs.reppo.ai/", "https://eval.reppo.xyz/agents.md"]
    assert is_allowed("https://docs.reppo.ai/concepts/evaluation-api.md", allow)
    assert is_allowed("https://eval.reppo.xyz/agents.md", allow)
    assert not is_allowed("https://eval.reppo.xyz/billing", allow)


def test_is_allowed_rejects_lookalike_hosts() -> None:
    allow = ["https://docs.reppo.ai/"]
    assert not is_allowed("https://docs.reppo.ai.evil.example/x", allow)
    assert not is_allowed("https://docs.reppo.ai@evil.example/x", allow)
    assert not is_allowed("http://docs.reppo.ai/x", allow)  # scheme downgrade
    assert not is_allowed("not a url", allow)


def test_a_file_prefix_allows_exactly_that_url() -> None:
    allow = ["https://eval.reppo.xyz/agents.md"]
    assert is_allowed("https://eval.reppo.xyz/agents.md", allow)
    assert not is_allowed("https://eval.reppo.xyz/agents.md.evil", allow)
    assert not is_allowed("https://eval.reppo.xyz/agents.md?x=1", allow)
    assert not is_allowed("https://eval.reppo.xyz/agents.md/extra", allow)
