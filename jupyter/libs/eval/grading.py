"""Hidden SLT grading and independent DuckDB-oracle validation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from .headers import eval_request_headers

if TYPE_CHECKING:
    from pathlib import Path

_SLT_TYPES = {
    "BIGINT": "I",
    "INTEGER": "I",
    "VARCHAR": "V",
    "BOOLEAN": "B",
    "DOUBLE": "D",
    "FLOAT": "R",
    "TIMESTAMP": "T",
    "DATE": "T",
}


def _slt_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    return str(value)


def _submission_slt(query: str, expected: dict[str, Any]) -> str:
    schema = expected["schema"]
    header = ",".join(f"{column['name']}:{_SLT_TYPES.get(str(column['type']).split('#')[0], 'V')}" for column in schema)
    types = "|".join(str(column["type"]) for column in schema)
    rows = "\n".join("\t".join(_slt_value(row[column["name"]]) for column in schema) for row in expected["data"])
    return f"# schema: {types}\nquery {header}\n{query.strip()}\n----\n{rows}\n"


def _normalize(value: Any, type_label: str | None = None) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if value == "TRUE":
            return True
        if value == "FALSE":
            return False
        if value == "NULL":
            return None
    base_type = type_label.split("#", 1)[0].split("(", 1)[0] if type_label else None
    if base_type in {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "UBIGINT"}:
        return int(value)
    if base_type in {"DOUBLE", "FLOAT", "REAL", "DECIMAL"}:
        return float(value)
    return value


def _normalized_rows(rows: list[dict[str, Any]], schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = [str(column["name"]) for column in schema]
    type_labels = [str(column["type"]) for column in schema]
    normalized = []
    for row in rows:
        casefolded = {key.casefold(): value for key, value in row.items()}
        if all(column.casefold() in casefolded for column in columns):
            values = [casefolded[column.casefold()] for column in columns]
        elif len(row) == len(columns):
            values = list(row.values())
        else:
            normalized.append({key: _normalize(value) for key, value in row.items()})
            continue
        normalized.append({column: _normalize(value, type_label) for column, value, type_label in zip(columns, values, type_labels, strict=True)})
    return normalized


def _sltest_passed(result: Any) -> bool:
    if isinstance(result, list):
        return bool(result) and all(isinstance(item, dict) and item.get("status") == "PASS" for item in result)
    if isinstance(result, dict):
        for key in ("results", "snippets", "tests"):
            if isinstance(result.get(key), list):
                return _sltest_passed(result[key])
        return result.get("status") == "PASS" or (result.get("failed") == 0 and result.get("passed", 0) > 0)
    return False


async def grade_submission(
    *,
    api_url: str,
    project_token: str,
    oracle_task: Path,
    query: str,
) -> dict[str, Any]:
    expected = json.loads((oracle_task / "expected.json").read_text(encoding="utf-8"))
    slt = _submission_slt(query, expected)
    escaped = slt.replace("'", "''")
    source = f"SELECT NAME := 'bench_eval#001.submission', CONTENT := '{escaped}';"
    headers = eval_request_headers(project_token)
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=120) as client:
        sltest_response = await client.post(
            "/sltest",
            json={
                "backend": "duckdb",
                "source": source,
                "halt_on_fail": False,
            },
        )
        sltest_response.raise_for_status()
        sltest_rows = sltest_response.json()

        actual_response = await client.post(
            "/query",
            json={"query": query, "backend": "duckdb", "structured": True},
        )
        actual_response.raise_for_status()
        actual_result = actual_response.json()

        oracle_response = await client.post(
            "/direct_sql_query",
            json={
                "query": (oracle_task / "oracle.sql").read_text(encoding="utf-8"),
            },
        )
        oracle_response.raise_for_status()
        oracle_result = oracle_response.json()

    schema = list(expected["schema"])
    expected_rows = _normalized_rows(list(expected["data"]), schema)
    actual_rows = _normalized_rows(list(actual_result.get("dataframe") or []), schema)
    oracle_rows = _normalized_rows(list(oracle_result.get("result") or []), schema)
    oracle_valid = not oracle_result.get("errors") and oracle_rows == expected_rows
    actual_valid = not actual_result.get("errors") and actual_rows == expected_rows
    passed = _sltest_passed(sltest_rows) and actual_valid
    return {
        "passed": passed,
        "sltest": sltest_rows,
        "expected_schema": expected["schema"],
        "expected_rows": expected_rows,
        "actual_schema": actual_result.get("schema") or actual_result.get("output_schema"),
        "actual_rows": actual_rows,
        "actual_errors": actual_result.get("errors") or [],
        "oracle_rows": oracle_rows,
        "oracle_errors": oracle_result.get("errors") or [],
        "oracle_valid": oracle_valid,
        "row_diff": {
            "missing": [row for row in expected_rows if row not in actual_rows],
            "unexpected": [row for row in actual_rows if row not in expected_rows],
        },
    }
