"""The one place that reads secrets.

`currant.guardrails` fails CI if any other file under `src/` names these variables or reads
the process environment. Rules this module keeps:

* A secret is wrapped in `Secret`, whose repr/str/format never show the value. Call
  `reveal()` only at the moment of use (an Authorization header) and never log the result.
* The process environment wins over `.env`; `.env` is a local convenience and is gitignored.
* Loading never writes into `os.environ`, so child processes do not inherit keys by accident.
* Diagnostics report presence, source and length only, never a value or a prefix.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SERV_KEY_NAME = "SERV_API_KEY"
REPPO_KEY_NAME = "REPPO_API_KEY"
WALLET_KEY_NAME = "WALLET_PRIVATE_KEY"
PROXY_TOKEN_NAME = "CURRANT_PROXY_TOKEN"  # optional: the proxy's own access token
SECRET_NAMES = (SERV_KEY_NAME, REPPO_KEY_NAME, WALLET_KEY_NAME, PROXY_TOKEN_NAME)
# Other names a person may already have used. The canonical name always wins.
ALIASES: dict[str, tuple[str, ...]] = {SERV_KEY_NAME: ("OPENSERV_API_KEY",)}

DEFAULT_DOTENV = Path(".env")


class MissingSecret(RuntimeError):
    """A required secret is not set (or is empty)."""


class DotenvError(RuntimeError):
    """The .env file exists but cannot be decoded."""


@dataclass(frozen=True, repr=False)
class Secret:
    name: str
    _value: str

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret({self.name}=<redacted, {len(self._value)} chars>)"

    __str__ = __repr__


@dataclass(frozen=True)
class SecretStatus:
    name: str
    source: str | None  # "environment", ".env", or None when unset
    length: int
    found_as: str | None = None  # the variable name actually used (the canonical name or an alias)


def _decode(data: bytes) -> str:
    # Windows tools disagree on encoding: PowerShell 5.1's `>` writes UTF-16, Notepad often
    # adds a UTF-8 BOM. Accept both rather than silently reading garbage.
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DotenvError(f"cannot decode the .env file as UTF-8 or UTF-16: {exc.reason}") from exc


def _clean_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    comment = raw.find(" #")
    return raw[:comment].rstrip() if comment != -1 else raw


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, rest = line.partition("=")
        key = key.strip()
        if not separator or not key.isidentifier():
            continue
        values[key] = _clean_value(rest.strip())
    return values


def _lookup(
    name: str, env: Mapping[str, str] | None, dotenv_path: Path | None
) -> tuple[str | None, str | None, str | None]:
    """Return (value, source, found_as). The process environment wins over the .env file,
    and the canonical name wins over its aliases."""
    environment = os.environ if env is None else env
    names = (name, *ALIASES.get(name, ()))
    for candidate in names:
        value = environment.get(candidate)
        if value:
            return value, "environment", candidate
    if dotenv_path is not None and dotenv_path.is_file():
        from_file = parse_dotenv(_decode(dotenv_path.read_bytes()))
        for candidate in names:
            value = from_file.get(candidate)
            if value:
                return value, ".env", candidate
    return None, None, None


def dotenv_names(dotenv_path: Path | None = DEFAULT_DOTENV) -> list[str]:
    """Variable names present in the .env file, in file order. Names only, never values:
    enough to spot a misnamed variable (OPENSERV_API_KEY vs SERV_API_KEY)."""
    if dotenv_path is None or not dotenv_path.is_file():
        return []
    return list(parse_dotenv(_decode(dotenv_path.read_bytes())))


def load_secret(
    name: str, *, env: Mapping[str, str] | None = None, dotenv_path: Path | None = DEFAULT_DOTENV
) -> Secret:
    value, _source, _found_as = _lookup(name, env, dotenv_path)
    if value is None:
        raise MissingSecret(
            f"{name} is not set. Put it in .env (see .env.example) or set it in the environment."
        )
    return Secret(name, value)


def secret_status(
    name: str, *, env: Mapping[str, str] | None = None, dotenv_path: Path | None = DEFAULT_DOTENV
) -> SecretStatus:
    value, source, found_as = _lookup(name, env, dotenv_path)
    return SecretStatus(name, source, len(value) if value else 0, found_as)


def all_secret_status(
    *, env: Mapping[str, str] | None = None, dotenv_path: Path | None = DEFAULT_DOTENV
) -> list[SecretStatus]:
    return [secret_status(name, env=env, dotenv_path=dotenv_path) for name in SECRET_NAMES]


def serv_api_key(dotenv_path: Path | None = DEFAULT_DOTENV) -> Secret:
    return load_secret(SERV_KEY_NAME, dotenv_path=dotenv_path)


def reppo_api_key(dotenv_path: Path | None = DEFAULT_DOTENV) -> Secret:
    return load_secret(REPPO_KEY_NAME, dotenv_path=dotenv_path)


def proxy_token(
    *, env: Mapping[str, str] | None = None, dotenv_path: Path | None = DEFAULT_DOTENV
) -> Secret | None:
    """The grounding proxy's own access token, or None when it is not set (then the proxy may
    only listen on loopback). It is separate from the SERV key, which callers send through."""
    value, _source, _found_as = _lookup(PROXY_TOKEN_NAME, env, dotenv_path)
    return Secret(PROXY_TOKEN_NAME, value) if value else None
