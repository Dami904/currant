"""The committed demo (examples/demo/) is what a cold reviewer can replay with no key and no
network. These tests keep it honest: it must replay, rebuilding it must give the same receipt, and
a tampered copy must fail."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from currant import cli

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo"


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_demo", ROOT / "scripts" / "build_demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_demo_replays(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["replay", str(DEMO / "receipt.json"), "--db", str(DEMO / "store.db")])
    assert code == 0 and "REPLAY OK" in capsys.readouterr().out


def test_rebuilding_the_demo_gives_the_same_receipt_and_context(tmp_path: Path) -> None:
    built = load_builder().build(tmp_path / "again")
    committed = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    assert built["receipt_id"] == committed["receipt_id"]
    assert built["context_sha256"] == committed["context_sha256"]
    assert (tmp_path / "again" / "context.txt").read_text(encoding="utf-8") == (
        DEMO / "context.txt"
    ).read_text(encoding="utf-8")


def test_the_context_file_hashes_to_the_receipt_byte_for_byte() -> None:
    receipt = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    raw = (DEMO / "context.txt").read_bytes()
    assert b"\r" not in raw  # LF only, on every platform
    assert hashlib.sha256(raw).hexdigest() == receipt["context_sha256"]


def test_the_demo_shows_a_cut_a_pull_and_a_contested_notice() -> None:
    receipt = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    kinds = sorted(a["kind"] for a in receipt["actions"])
    assert kinds == ["contested", "pull", "redact"]
    context = (DEMO / "context.txt").read_text(encoding="utf-8")
    assert "[REMOVED: superseded by newer documentation]" in context
    assert "CONTESTED" in context and "PULLED EVIDENCE" in context


def test_a_tampered_demo_receipt_fails_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(DEMO / "store.db", tmp_path / "store.db")
    receipt = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    receipt["actions"][0]["target"]["quote"] = "Something the page never said."
    (tmp_path / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    code = cli.main(["replay", str(tmp_path / "receipt.json"), "--db", str(tmp_path / "store.db")])
    assert code == 1 and "REPLAY FAILED" in capsys.readouterr().out


def test_the_demo_uses_invented_pages_not_a_sponsors_documentation() -> None:
    receipt = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    assert all(d["url"].startswith("https://docs.example.com/") for d in receipt["documents"])


def test_the_committed_receipt_viewer_demo_replays_without_a_key(tmp_path: Path) -> None:
    """`currant serve --receipts examples/demo/receipts` shows this receipt and replays it live."""
    import httpx

    from currant.proxy import GroundingProxy
    from currant.proxy_http import route
    from currant.store import ClaimStore

    store_copy = tmp_path / "store.db"
    shutil.copyfile(
        DEMO / "store.db", store_copy
    )  # opening a store can write; keep the demo intact
    committed = json.loads((DEMO / "receipt.json").read_text(encoding="utf-8"))
    proxy = GroundingProxy(
        ClaimStore(store_copy),
        extract_run_id=1,
        relate_run_id=2,
        http=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500))),
        receipts_dir=DEMO / "receipts",
    )
    rid = committed["receipt_id"]
    assert json.loads(route(proxy, "GET", "/receipts", b"", None).body) == [rid]
    replayed = json.loads(route(proxy, "GET", f"/receipts/{rid}/replay", b"", None).body)
    assert replayed["ok"] is True and replayed["context_sha256"] == committed["context_sha256"]
    shown = route(proxy, "GET", f"/receipts/{rid}/context", b"", None).body.decode()
    assert shown == (DEMO / "context.txt").read_text(encoding="utf-8")
