"""Ed25519 signatures for receipts: who produced a receipt, on top of what it covers.

A receipt already proves its context (its id is the hash of its body, and `replay` re-derives
the context). A signature adds who vouched for it. Rules:

* The signed message is the receipt id (which commits to the whole body) and the signing time,
  under a domain tag, so a signature for a receipt can never be reused for anything else.
* The signature lives in a sidecar file (`<receipt>.sig.json`), so a receipt and its id are
  unchanged by signing.
* Verification never trusts what the sidecar says about itself: the caller supplies the public
  key they trust, the receipt id is recomputed from the body, and the sidecar must name that same
  receipt. A sidecar carrying a different public key fails, whatever its signature.
* The private key comes only from `CURRANT_SIGNING_KEY` (read in `currant.config`) and is never
  printed or written into a receipt.

What it does not do: there is no revocation list and no expiry. A signature says "this key signed
this receipt at this time"; whether that key should still be trusted is the verifier's call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from currant.receipt import receipt_id

ALG = "ed25519"
DOMAIN = b"currant-receipt-signature-v1\n"
_HEX32 = re.compile(r"[0-9a-f]{64}")


class SigningError(ValueError):
    """A key or signature that cannot be used."""


def _key_bytes(hex_text: str, what: str) -> bytes:
    text = hex_text.strip().lower()
    if not _HEX32.fullmatch(text):
        raise SigningError(f"{what} must be 64 hex characters (32 bytes)")
    return bytes.fromhex(text)


def private_key(seed_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_key_bytes(seed_hex, "the signing key"))


def public_key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def new_seed_hex() -> str:
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat

    key = Ed25519PrivateKey.generate()
    return key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()


def message(rid: str, signed_at: str) -> bytes:
    return DOMAIN + rid.encode("ascii") + b"\n" + signed_at.encode("ascii")


def _body_id(receipt: dict[str, Any]) -> str:
    return receipt_id({k: v for k, v in receipt.items() if k != "receipt_id"})


def sign(receipt: dict[str, Any], key: Ed25519PrivateKey, signed_at: str) -> dict[str, str]:
    """The sidecar for a receipt. Refuses a receipt whose id does not match its body: signing a
    tampered receipt would vouch for it."""
    rid = receipt.get("receipt_id")
    if not isinstance(rid, str) or _body_id(receipt) != rid:
        raise SigningError("the receipt id does not match its body; refusing to sign it")
    return {
        "alg": ALG,
        "receipt_id": rid,
        "signed_at": signed_at,
        "public_key": public_key_hex(key),
        "signature": key.sign(message(rid, signed_at)).hex(),
    }


@dataclass
class SignatureCheck:
    ok: bool = True
    problems: list[str] = field(default_factory=list)

    def fail(self, problem: str) -> SignatureCheck:
        self.ok = False
        self.problems.append(problem)
        return self


def verify(receipt: object, sidecar: object, trusted_public_key_hex: str) -> SignatureCheck:
    """Check a sidecar against a receipt and a public key the caller trusts. Every check is
    recomputed here; nothing in the sidecar is taken on its word."""
    check = SignatureCheck()
    if not isinstance(receipt, dict) or not isinstance(sidecar, dict):
        return check.fail("the receipt and the signature must both be JSON objects")
    try:
        trusted = Ed25519PublicKey.from_public_bytes(
            _key_bytes(trusted_public_key_hex, "the trusted public key")
        )
    except SigningError as exc:
        return check.fail(str(exc))
    rid = receipt.get("receipt_id")
    if not isinstance(rid, str) or _body_id(receipt) != rid:
        return check.fail("the receipt id does not match its body (the receipt was changed)")
    if sidecar.get("alg") != ALG:
        return check.fail(f"unsupported signature algorithm {sidecar.get('alg')!r}")
    if sidecar.get("receipt_id") != rid:
        return check.fail("the signature is for a different receipt")
    if str(sidecar.get("public_key", "")).lower() != trusted_public_key_hex.strip().lower():
        return check.fail("the signature names a different key from the one you trust")
    signed_at, signature = sidecar.get("signed_at"), sidecar.get("signature")
    if not isinstance(signed_at, str) or not signed_at.isascii():
        return check.fail("the signature has no usable signed_at")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        return check.fail("the signature is not 64 bytes of hex")
    try:
        trusted.verify(bytes.fromhex(signature), message(rid, signed_at))
    except InvalidSignature:
        return check.fail("the signature does not verify under the trusted key")
    return check


def load_json(text: str) -> Any:
    return json.loads(text)
