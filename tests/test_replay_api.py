"""The hosted, read-only receipt replay (`currant.replay_api`, served by site/api/replay.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from currant import replay_api
from currant.store import ClaimStore, SchemaMismatch

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "examples" / "real"
DEMO = ROOT / "examples" / "demo"
STORE_DIR = ROOT / "site" / "api" / "_stores"  # what the Vercel function serves


def receipt(where: Path = REAL) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((where / "receipt.json").read_text(encoding="utf-8"))
    return loaded


def call(body: object, stores: Path | None = None) -> tuple[int, dict[str, Any]]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    status, payload = replay_api.handle(raw, stores or STORE_DIR)
    parsed: dict[str, Any] = json.loads(payload)
    return status, parsed


# --- the read-only store ---------------------------------------------------------------


def test_a_read_only_store_can_be_read_but_never_written(tmp_path: Path) -> None:
    copy = tmp_path / "store.db"
    shutil.copy(REAL / "store.db", copy)
    before = hashlib.sha256(copy.read_bytes()).hexdigest()
    with ClaimStore.open_readonly(copy) as store:
        assert store.schema_version() > 0
        with pytest.raises(sqlite3.OperationalError):
            store.conn.execute("CREATE TABLE x (y)")
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before
    assert not (tmp_path / "store.db-wal").exists()  # opening read-only switched nothing on


def test_a_read_only_open_never_creates_a_store(tmp_path: Path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        ClaimStore.open_readonly(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_a_read_only_open_refuses_an_empty_file_instead_of_building_a_schema(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    with pytest.raises(SchemaMismatch):
        ClaimStore.open_readonly(empty)


# --- the hosted stores -----------------------------------------------------------------


def test_the_hosted_stores_are_byte_identical_to_the_committed_examples() -> None:
    for name, source in (("real.db", REAL), ("demo.db", DEMO)):
        hosted = STORE_DIR / name
        assert hosted.read_bytes() == (source / "store.db").read_bytes(), name


def test_every_hosted_store_is_pinned_by_hash_and_corpus() -> None:
    for corpus_hash, (name, sha) in replay_api.HOSTED.items():
        data = (STORE_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, name
        with ClaimStore.open_readonly(STORE_DIR / name) as store:
            hashes = {r[0] for r in store.conn.execute("SELECT corpus_hash FROM snapshots")}
        assert corpus_hash in hashes, name


# --- replay through the handler --------------------------------------------------------


@pytest.mark.parametrize("where", [REAL, DEMO])
def test_a_committed_receipt_replays_on_the_hosted_store(where: Path) -> None:
    status, out = call(receipt(where))
    assert status == 200
    assert out["verdict"] == "REPLAYED", out
    assert out["problems"] == []
    assert out["context_sha256"] == receipt(where)["context_sha256"]


def test_an_edited_receipt_fails_with_the_reason() -> None:
    edited = receipt()
    edited["context_sha256"] = "0" * 64
    status, out = call(edited)
    assert status == 200 and out["verdict"] == "FAILED"
    assert any("receipt_id" in p for p in out["problems"])


def test_a_forged_receipt_resealed_with_a_new_id_still_fails() -> None:
    from currant.receipt import receipt_id

    forged = receipt()
    forged["actions"] = []
    forged["receipt_id"] = receipt_id({k: v for k, v in forged.items() if k != "receipt_id"})
    _, out = call(forged)
    assert out["verdict"] == "FAILED"
    assert any("different actions" in p for p in out["problems"])


def test_an_unknown_corpus_is_not_replayed_and_not_passed() -> None:
    other = receipt()
    other["corpus"] = {**other["corpus"], "corpus_hash": "f" * 64}
    status, out = call(other)
    assert status == 200 and out["verdict"] == "UNKNOWN"
    assert "no hosted store" in out["problems"][0]


def test_a_store_whose_bytes_changed_is_refused(tmp_path: Path) -> None:
    for name, _ in replay_api.HOSTED.values():
        shutil.copy(STORE_DIR / name, tmp_path / name)
    real_name = replay_api.HOSTED[receipt()["corpus"]["corpus_hash"]][0]
    with (tmp_path / real_name).open("ab") as f:
        f.write(b"\0")
    _, out = call(receipt(), tmp_path)
    assert out["verdict"] == "UNKNOWN"
    assert "does not match its pinned hash" in out["problems"][0]


@pytest.mark.parametrize(
    "body",
    [b"", b"not json", b"[1, 2]", b'"a string"', b"\xff\xfe"],
)
def test_input_that_is_not_a_receipt_object_is_a_400(body: bytes) -> None:
    status, out = call(body)
    assert status == 400 and out["verdict"] == "FAILED"


def test_a_receipt_object_missing_fields_fails_with_the_reason() -> None:
    status, out = call({"receipt_version": 1})
    assert status == 200 and out["verdict"] == "FAILED"
    assert any("missing fields" in p for p in out["problems"])


def test_an_oversized_body_is_refused_before_it_is_parsed() -> None:
    status, out = call(b"{" + b" " * replay_api.MAX_BODY + b"}")
    assert status == 413 and out["verdict"] == "FAILED"


class _Unreadable:
    def read(self, *_: Any) -> bytes:
        raise AssertionError("the body was read")


def test_the_function_refuses_an_oversized_declared_length_without_reading_it() -> None:
    adapter = load_adapter()
    fake: Any = object.__new__(adapter.handler)  # no socket: only the request fields it uses
    sent: list[int] = []
    fake.headers = {"Content-Length": str(replay_api.MAX_BODY + 1)}
    fake.rfile = _Unreadable()
    fake._send = lambda status, body: sent.append(status)
    fake.do_POST()
    assert sent == [413]


def test_the_reply_names_the_code_and_the_store_it_used() -> None:
    _, out = call(receipt())
    assert out["store"]["sha256"] == replay_api.HOSTED[receipt()["corpus"]["corpus_hash"]][1]
    assert out["replay_api"] == replay_api.REPLAY_API_VERSION


def test_an_unexpected_error_is_unknown_never_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any) -> Any:
        raise RuntimeError("disk gone")

    monkeypatch.setattr(replay_api, "replay", boom)
    status, out = call(receipt())
    assert status == 500 and out["verdict"] == "UNKNOWN"
    assert "disk gone" not in json.dumps(out)  # internal detail is not echoed to the caller


# --- the Vercel adapter ----------------------------------------------------------------


def load_adapter() -> ModuleType:
    path = ROOT / "site" / "api" / "replay.py"
    spec = importlib.util.spec_from_file_location("site_api_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_vercel_function_only_delegates_to_the_package() -> None:
    adapter = load_adapter()
    assert adapter.handle is replay_api.handle
    assert adapter.STORE_DIR == STORE_DIR


def test_the_vercel_requirements_pin_currant_to_one_commit() -> None:
    lines = (ROOT / "site" / "requirements.txt").read_text(encoding="utf-8").split("\n")
    pins = [x for x in lines if x.startswith("currant @ git+https://github.com/Dami904/currant@")]
    assert len(pins) == 1
    sha = pins[0].rsplit("@", 1)[1]
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)


# --- audit follow-ups (2026-11-18) -----------------------------------------------------


def test_deeply_nested_json_is_a_400_not_a_crash() -> None:
    status, out = call(b"[" * 200_000)
    assert status == 400 and out["verdict"] == "FAILED"


def test_anything_escaping_handle_is_still_a_json_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = load_adapter()

    def boom(*_: Any) -> Any:
        raise MemoryError

    monkeypatch.setattr(adapter, "handle", boom)
    fake: Any = object.__new__(adapter.handler)
    sent: list[tuple[int, bytes]] = []
    fake.headers = {"Content-Length": "2"}
    fake.rfile = __import__("io").BytesIO(b"{}")
    fake._send = lambda status, body: sent.append((status, body))
    fake.do_POST()
    status, body = sent[0]
    assert status == 500 and json.loads(body)["verdict"] == "UNKNOWN"


def test_a_request_without_a_length_is_a_411_not_a_misleading_parse_error() -> None:
    adapter = load_adapter()
    fake: Any = object.__new__(adapter.handler)
    sent: list[int] = []
    fake.headers = {}
    fake.rfile = _Unreadable()
    fake._send = lambda status, body: sent.append(status)
    fake.do_POST()
    assert sent == [411]


def test_every_reply_carries_a_request_id_that_the_log_line_also_carries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out = call(receipt())
    logged = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    assert len(out["request_id"]) == 16
    line = next(x for x in logged if x.get("request_id") == out["request_id"])
    assert line["receipt"] == receipt()["receipt_id"][:12]  # a public hash prefix, never the body
    assert receipt()["question"] not in json.dumps(logged)


def test_an_unhosted_corpus_is_logged_with_its_hash(capsys: pytest.CaptureFixture[str]) -> None:
    other = receipt()
    other["corpus"] = {**other["corpus"], "corpus_hash": "f" * 64}
    call(other)
    assert '"corpus_hash": "' + "f" * 64 in capsys.readouterr().err


def test_a_hash_mismatch_logs_both_hashes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, _ in replay_api.HOSTED.values():
        shutil.copy(STORE_DIR / name, tmp_path / name)
    real_name, pinned = replay_api.HOSTED[receipt()["corpus"]["corpus_hash"]]
    (tmp_path / real_name).write_bytes(b"changed")
    call(receipt(), tmp_path)
    err = capsys.readouterr().err
    assert pinned in err and hashlib.sha256(b"changed").hexdigest() in err


def test_an_unexpected_error_is_logged_with_its_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_: Any) -> Any:
        raise RuntimeError("disk gone")

    monkeypatch.setattr(replay_api, "replay", boom)
    call(receipt())
    assert "disk gone" in capsys.readouterr().err  # in the server log, not in the reply


def test_a_corrupt_store_file_raises_and_closes(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        ClaimStore.open_readonly(junk)
    junk.unlink()  # on Windows this fails if a connection was left open


def test_a_read_only_store_has_every_attribute_a_normal_one_has(tmp_path: Path) -> None:
    normal = ClaimStore(tmp_path / "n.db")
    with ClaimStore.open_readonly(STORE_DIR / "demo.db") as ro:
        assert set(vars(ro)) == set(vars(normal))
    normal.close()


VERIFY_TS = ROOT / "site" / "src" / "verify.ts"


def test_the_page_shows_a_timeout_or_network_error_as_unknown_never_failed() -> None:
    code = VERIFY_TS.read_text(encoding="utf-8")
    catch = code[code.rindex("} catch {") : code.rindex("} finally {")]
    assert "UNKNOWN" in catch and "FAILED" not in catch and '"bad"' not in catch


def test_the_page_trusts_replayed_only_from_a_200() -> None:
    code = VERIFY_TS.read_text(encoding="utf-8")
    assert 'response.ok && verdictName === "REPLAYED"' in code


# --- the pin check ---------------------------------------------------------------------


def load_pin_check() -> ModuleType:
    path = ROOT / "scripts" / "check_replay_pin.py"
    spec = importlib.util.spec_from_file_location("check_replay_pin", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_git(has_code: bool, same_src: bool) -> Any:
    def git(*args: str) -> int:
        if args[0] == "cat-file":
            return 0 if has_code else 1
        if args[0] == "diff":
            return 0 if same_src else 1
        raise AssertionError(args)

    return git


@pytest.mark.parametrize(
    ("has_code", "same_src", "problem"),
    [
        (True, True, None),
        (False, True, "does not contain"),
        (True, False, "changed since"),
    ],
)
def test_the_pin_check_names_what_is_wrong(
    has_code: bool, same_src: bool, problem: str | None
) -> None:
    pin_check = load_pin_check()
    problems = pin_check.check("a" * 40, fake_git(has_code, same_src))
    assert (problems == []) if problem is None else (problem in problems[0])


def test_the_pin_check_reads_the_committed_requirements() -> None:
    sha = load_pin_check().pinned_sha(ROOT / "site" / "requirements.txt")
    assert len(sha) == 40
