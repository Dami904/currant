"""Structured JSON-lines logging with no third-party dependency.

Every failure path in the crawler logs through this before returning a clean result, so a
failed run can be reconstructed from the log file alone.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TextIO


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class JsonLogger:
    def __init__(
        self,
        *,
        run_id: str | None = None,
        stream: TextIO | None = None,
        file: TextIO | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._stream = stream if stream is not None else sys.stderr
        self._file = file
        self._now = now

    def event(self, level: str, msg: str, **fields: Any) -> None:
        record = {"ts": self._now().isoformat(), "run_id": self.run_id, "level": level, "msg": msg}
        record.update(fields)
        line = json.dumps(record, sort_keys=True, default=str)
        print(line, file=self._stream)
        if self._file is not None:
            print(line, file=self._file, flush=True)

    def info(self, msg: str, **fields: Any) -> None:
        self.event("info", msg, **fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self.event("warn", msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self.event("error", msg, **fields)
