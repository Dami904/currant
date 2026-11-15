"""Receipt signing commands: keygen, sign, verify-signature (needs the `sign` extra)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from currant.config import SIGNING_KEY_NAME, DotenvError, signing_key
from currant.obs import utc_now

KEY_DIR = Path("data")  # git-ignored: the only place keygen writes a private key inside the repo


def _need_extra() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("error: signing needs the extra: uv sync --extra sign", file=sys.stderr)
        return False
    return True


def sidecar_path(receipt: Path) -> Path:
    return receipt.with_name(receipt.name.removesuffix(".json") + ".sig.json")


def cmd_keygen(args: argparse.Namespace) -> int:
    if not _need_extra():
        return 2
    from currant.signing import new_seed_hex, private_key, public_key_hex

    out: Path = args.out
    inside = out.resolve().is_relative_to(Path.cwd().resolve())
    if inside and not out.resolve().is_relative_to(KEY_DIR.resolve()):
        where = f"{KEY_DIR}/ (git-ignored)"
        print(f"error: inside the repository a private key may only go under {where}",
              file=sys.stderr)  # fmt: skip
        return 2
    if out.exists():
        print(f"error: {out} exists; refusing to overwrite a key", file=sys.stderr)
        return 2
    seed = new_seed_hex()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(seed + "\n", encoding="ascii")
    print(f"private key written to {out} (never commit or share it)")
    print(f"public key:  {public_key_hex(private_key(seed))}")
    print(f"to sign, set {SIGNING_KEY_NAME} to the contents of that file")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    if not _need_extra():
        return 2
    from currant.signing import SigningError, private_key, sign

    try:
        secret = signing_key(dotenv_path=args.dotenv)
        if secret is None:
            print(f"error: {SIGNING_KEY_NAME} is not set (see `currant keygen`)", file=sys.stderr)
            return 2
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise SigningError("the receipt is not a JSON object")
        sidecar = sign(
            receipt, private_key(secret.reveal()), utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except (DotenvError, SigningError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = args.out or sidecar_path(args.receipt)
    out.write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"signed {sidecar['receipt_id'][:16]}… with key {sidecar['public_key']}")
    print(f"signature:   {out}")
    return 0


def cmd_verify_signature(args: argparse.Namespace) -> int:
    if not _need_extra():
        return 2
    from currant.signing import verify

    sig = args.sig or sidecar_path(args.receipt)
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        sidecar = json.loads(sig.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    check = verify(receipt, sidecar, args.public_key)
    if check.ok:
        print(f"SIGNATURE OK: {args.public_key} signed this receipt at {sidecar['signed_at']}")
        return 0
    for problem in check.problems:
        print(f"SIGNATURE FAILED: {problem}")
    return 1
