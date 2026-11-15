"""Receipt signatures. Each test fails if its check in currant.signing is removed."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from currant.config import SIGNING_KEY_NAME, signing_key
from currant.signing import (
    SigningError,
    new_seed_hex,
    private_key,
    public_key_hex,
    sign,
    verify,
)

ROOT = Path(__file__).resolve().parent.parent
RECEIPT: dict[str, Any] = json.loads(
    (ROOT / "examples" / "real" / "receipt.json").read_text(encoding="utf-8")
)
AT = "2026-11-15T12:00:00Z"


@pytest.fixture
def keys() -> tuple[Any, str]:
    key = private_key(new_seed_hex())
    return key, public_key_hex(key)


def test_a_signed_receipt_verifies_under_its_key(keys: tuple[Any, str]) -> None:
    key, public = keys
    sidecar = sign(RECEIPT, key, AT)
    assert sidecar["receipt_id"] == RECEIPT["receipt_id"] and sidecar["public_key"] == public
    check = verify(RECEIPT, sidecar, public)
    assert check.ok, check.problems


def test_a_changed_receipt_fails_even_with_a_valid_signature(keys: tuple[Any, str]) -> None:
    key, public = keys
    sidecar = sign(RECEIPT, key, AT)
    changed = copy.deepcopy(RECEIPT)
    changed["question"] = "Something else?"
    check = verify(changed, sidecar, public)
    assert not check.ok and "does not match its body" in check.problems[0]


def test_a_signature_for_another_receipt_fails(keys: tuple[Any, str]) -> None:
    key, public = keys
    other = copy.deepcopy(RECEIPT)
    other["question"] = "Something else?"
    from currant.receipt import receipt_id

    other["receipt_id"] = receipt_id({k: v for k, v in other.items() if k != "receipt_id"})
    check = verify(RECEIPT, sign(other, key, AT), public)
    assert not check.ok and "different receipt" in check.problems[0]


def test_a_key_the_verifier_does_not_trust_fails(keys: tuple[Any, str]) -> None:
    key, _public = keys
    stranger = private_key(new_seed_hex())
    sidecar = sign(RECEIPT, stranger, AT)  # self-consistent, but signed by someone else
    check = verify(RECEIPT, sidecar, public_key_hex(key))
    assert not check.ok and "different key" in check.problems[0]


def test_a_forged_signature_under_the_trusted_key_name_fails(keys: tuple[Any, str]) -> None:
    _key, public = keys
    stranger = private_key(new_seed_hex())
    forged = sign(RECEIPT, stranger, AT)
    forged["public_key"] = public  # claims the trusted key, signed by another
    check = verify(RECEIPT, forged, public)
    assert not check.ok and "does not verify" in check.problems[0]


def test_changing_the_signing_time_breaks_the_signature(keys: tuple[Any, str]) -> None:
    key, public = keys
    sidecar = sign(RECEIPT, key, AT)
    sidecar["signed_at"] = "2030-01-01T00:00:00Z"
    assert not verify(RECEIPT, sidecar, public).ok


def test_a_tampered_receipt_is_never_signed(keys: tuple[Any, str]) -> None:
    key, _public = keys
    changed = copy.deepcopy(RECEIPT)
    changed["mode"] = "redact"
    with pytest.raises(SigningError, match="refusing to sign"):
        sign(changed, key, AT)


def test_malformed_keys_and_sidecars_are_refused(keys: tuple[Any, str]) -> None:
    key, public = keys
    with pytest.raises(SigningError):
        private_key("not hex")
    assert not verify(RECEIPT, {"alg": "rsa"}, public).ok
    assert not verify(RECEIPT, sign(RECEIPT, key, AT), "abc").ok
    assert not verify("x", {}, public).ok


def test_keygen_sign_and_verify_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from currant.cli import main

    key_file = tmp_path / "keys" / "k.hex"
    assert main(["keygen", "--out", str(key_file)]) == 0
    public = capsys.readouterr().out.split("public key:")[1].split()[0]
    assert main(["keygen", "--out", str(key_file)]) == 2  # never overwrites a key
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(RECEIPT), encoding="utf-8")
    monkeypatch.setenv(SIGNING_KEY_NAME, key_file.read_text(encoding="ascii").strip())
    assert main(["sign", str(receipt), "--dotenv", str(tmp_path / "none.env")]) == 0
    out = capsys.readouterr().out
    assert key_file.read_text(encoding="ascii").strip() not in out  # the private key is never shown
    assert (tmp_path / "receipt.sig.json").is_file()
    assert main(["verify-signature", str(receipt), "--public-key", public]) == 0
    changed = dict(RECEIPT, question="Something else?")
    receipt.write_text(json.dumps(changed), encoding="utf-8")
    assert main(["verify-signature", str(receipt), "--public-key", public]) == 1


def test_keygen_refuses_to_write_a_key_into_the_repository_outside_data() -> None:
    from currant.cli import main

    assert main(["keygen", "--out", "examples/key.hex"]) == 2
    assert not Path("examples/key.hex").exists()


def test_the_signing_key_comes_only_from_its_environment_variable(
    keys: tuple[Any, str],
) -> None:
    assert signing_key(env={}, dotenv_path=None) is None
    seed = new_seed_hex()
    secret = signing_key(env={SIGNING_KEY_NAME: seed}, dotenv_path=None)
    assert secret is not None and secret.reveal() == seed and seed not in repr(secret)
