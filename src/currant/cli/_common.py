"""Shared pieces of the command line: argument types, constants and store/model helpers."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import httpx

from currant import __version__
from currant.config import (
    Secret,
)
from currant.harness.arms import (
    ALL_ARMS,
)
from currant.llmcache import CachingModel, json_object_reply
from currant.serv import ServClient
from currant.store import ClaimStore, StoreError

# [0-9], not \d: \d also matches non-ASCII digits, and this string becomes a directory name.
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
USER_AGENT = f"currant-crawler/{__version__}"
DEFAULT_EVAL_DB = Path("data/evalset.db")
DEFAULT_REPPO_LEDGER = Path("data/reppo-ledger.jsonl")
DEFAULT_PROXY_RECEIPTS = Path("data/proxy-receipts")
PRIVATE_DIR = Path("docs/private")
CLI_DOC = "Command line entry point (`currant --help` lists every command)."


def non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {value}")
    return value


def int_list(raw: str) -> tuple[int, ...]:
    """Comma-separated positive integers, e.g. "1,2"."""
    try:
        return tuple(positive_int(part) for part in raw.split(",") if part.strip())
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(f"{raw!r}: {exc}") from None


def arm_list(raw: str) -> tuple[str, ...]:
    arms = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = [arm for arm in arms if arm not in ALL_ARMS]
    if not arms or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown arm {', '.join(unknown) or raw!r}; choose from {', '.join(ALL_ARMS)}"
        )
    return arms


def positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def non_negative_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not value >= 0:  # also rejects NaN
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {raw}")
    return value


def valid_date(text: str) -> bool:
    if not _DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def private_out_refused(out: Path, publish: bool) -> bool:
    if not publish and PRIVATE_DIR.resolve() not in out.resolve().parents:
        print(
            f"error: {out} is outside {PRIVATE_DIR}. Candidate sponsor-documentation conflicts "
            "stay private until two sources confirm them and the maintainers are told; pass "
            "--publish to override",
            file=sys.stderr,
        )
        return True
    return False


def open_model(
    http: httpx.Client, key: Secret, args: argparse.Namespace, raw_log: Path
) -> CachingModel | None:
    """The cached SERV client, or None (after printing why) if its cache or raw log cannot be
    opened: an unwritable location is an error message, not a traceback."""
    try:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        return CachingModel(
            ServClient(http, key, model=args.model),
            args.cache,
            accept=json_object_reply,
            raw_log=raw_log,
        )
    except (OSError, sqlite3.Error) as exc:
        print(f"error: cannot open the model cache or raw log: {exc}", file=sys.stderr)
        return None


def warn_if_log_failed(model: CachingModel, raw_log: Path) -> None:
    if model.log_errors:
        print(
            f"warning: {model.log_errors} raw-log writes to {raw_log} failed; the replies were "
            "still cached, but that part of the audit trail is missing",
            file=sys.stderr,
        )


def open_existing(path: Path) -> ClaimStore:
    """Open a claim store that must already exist: a typo must not create an empty one."""
    if not path.is_file():
        raise StoreError(f"no claim store at {path}")
    return ClaimStore(path)
