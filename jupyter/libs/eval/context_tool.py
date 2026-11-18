"""Allowlisted benchmark Markdown access without filesystem exposure."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class BenchmarkContext:
    def __init__(self, subject_root: Path) -> None:
        self.root = (subject_root / "context").resolve()

    def list_files(self) -> dict[str, list[str]]:
        return {"files": [path.relative_to(self.root).as_posix() for path in sorted(self.root.rglob("*.md"))]}

    def read(self, path: str) -> dict[str, str]:
        resolved = self._resolve(path)
        return {"path": path, "content": resolved.read_text(encoding="utf-8")}

    def search(self, query: str) -> dict[str, list[dict[str, object]]]:
        query_lower = query.lower()
        matches: list[dict[str, object]] = []
        for path in sorted(self.root.rglob("*.md")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if query_lower in line.lower():
                    matches.append({
                        "path": path.relative_to(self.root).as_posix(),
                        "line": line_number,
                        "text": line,
                    })
        return {"matches": matches[:100]}

    def _resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.suffix != ".md":
            raise ValueError("Context path is outside the allowlisted Markdown root")
        if not path.is_file():
            raise ValueError(f"Context file does not exist: {relative}")
        return path


CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "benchmark_context",
        "description": "List, read, or search the benchmark's allowlisted Markdown context.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {"type": "string", "enum": ["list", "read", "search"]},
                "path": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["operation"],
        },
    },
}

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_featureql",
        "description": "Submit the final FeatureQL query for hidden grading and end the run.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}
