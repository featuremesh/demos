"""Append-only, secret-redacted run archives."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_OPENROUTER_KEY = re.compile(r"sk-or-v1-[A-Za-z0-9_-]+")
_SECRET_KEYS = {"authorization", "api_key", "token", "access_token"}


def run_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _OPENROUTER_KEY.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in _SECRET_KEYS or key.lower().endswith("_token") or "authorization" in key.lower() else redact(item)) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class RunArchive:
    def __init__(self, root: Path, campaign_id: str, run_id: str) -> None:
        self.path = root / campaign_id / run_id
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "featuremesh_requests").mkdir()
        for filename in (
            "conversation.jsonl",
            "openrouter_responses.jsonl",
            "tool_calls.jsonl",
            "submissions.jsonl",
        ):
            (self.path / filename).touch()

    def append(self, filename: str, record: dict[str, Any]) -> None:
        path = self.path / filename
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact(record), sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write(self, filename: str, record: dict[str, Any]) -> None:
        path = self.path / filename
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(redact(record), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def validate_run_archive(path: Path) -> None:
    required = {
        "run.json",
        "environment.json",
        "conversation.jsonl",
        "openrouter_responses.jsonl",
        "tool_calls.jsonl",
        "submissions.jsonl",
        "grade.json",
    }
    missing = sorted(name for name in required if not (path / name).is_file())
    must_have_records = {"conversation.jsonl", "openrouter_responses.jsonl"}
    empty = sorted(name for name in must_have_records if (path / name).is_file() and not (path / name).read_text(encoding="utf-8").strip())
    if missing or empty:
        raise ValueError(f"Incomplete run archive: missing={missing}, empty={empty}")
