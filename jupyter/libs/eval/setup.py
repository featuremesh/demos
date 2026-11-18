"""Controller-only dataset/profile loading and oracle leak preflights."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from .headers import eval_request_headers
from .mcp_bridge import McpBridge

if TYPE_CHECKING:
    from pathlib import Path

_FEATUREQL_SEPARATOR = "-- BENCH_EVAL_STATEMENT --"


def _has_error(value: Any) -> bool:
    if isinstance(value, dict):
        if any(value.get(key) for key in ("error", "errors")):
            return True
        return any(_has_error(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_error(item) for item in value)
    return False


async def setup_project(
    *,
    api_url: str,
    mcp_url: str,
    project_token: str,
    subject: Path,
    feature_profile: str,
) -> dict[str, Any]:
    manifest = json.loads((subject / "manifest.json").read_text(encoding="utf-8"))
    headers = eval_request_headers(project_token)
    setup_results: list[Any] = []
    scope_marker = f"bench_eval_scope_{uuid.uuid4().hex}"
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=120) as client:
        dataset = await client.post(
            "/direct_sql_query",
            json={"query": (subject / "dataset.sql").read_text(encoding="utf-8")},
        )
        dataset.raise_for_status()
        dataset_result = dataset.json()
        if dataset_result.get("errors"):
            raise RuntimeError(f"Dataset setup failed: {dataset_result['errors']}")
        setup_results.append(dataset_result)
        marker = await client.post(
            "/direct_sql_query",
            json={"query": (f"CREATE TABLE {scope_marker} AS SELECT 1 AS project_scope")},
        )
        marker.raise_for_status()
        profile = (subject / "feature_profiles" / f"{feature_profile}.featureql").read_text(encoding="utf-8")
        for statement in profile.split(_FEATUREQL_SEPARATOR):
            if not statement.strip():
                continue
            response = await client.post(
                "/query",
                json={
                    "query": statement.strip(),
                    "backend": manifest["backend"],
                    "structured": True,
                },
            )
            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise RuntimeError(f"Feature profile setup failed: {result['errors']}")
            setup_results.append(result)

    async with McpBridge(mcp_url, project_token) as bridge:
        health = await bridge.call("direct_sql_query", {"query": manifest["dataset_health_sql"]})
        marker_health = await bridge.call(
            "direct_sql_query",
            {"query": f"SELECT project_scope FROM {scope_marker}"},
        )
        namespace = manifest["feature_profiles"][feature_profile].get("namespace")
        described = None
        if namespace:
            described = await bridge.call(
                "featuremesh_describe",
                {
                    "prefixes": [namespace],
                    "backend": manifest["backend"],
                    "structured": True,
                },
            )
    if _has_error(health):
        raise RuntimeError(f"MCP dataset health check failed: {health}")
    if _has_error(marker_health) or marker_health.get("result") != [{"project_scope": 1}]:
        raise RuntimeError(f"API/MCP project scope mismatch: {marker_health}")
    if described is not None and _has_error(described):
        raise RuntimeError(f"MCP feature health check failed: {described}")
    return {
        "setup": setup_results,
        "mcp_health": health,
        "scope_marker_health": marker_health,
        "describe": described,
    }


async def preflight_no_oracle_leak(
    *,
    api_url: str,
    project_token: str,
    task_id: str,
    solution_snippet: str,
    reference_query: str,
) -> dict[str, Any]:
    headers = eval_request_headers(project_token)
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=120) as client:
        tests = await client.post(
            "/query",
            json={
                "query": (f"SHOW TESTS WHERE NAME LIKE '%#{solution_snippet}';"),
                "backend": "duckdb",
                "structured": True,
            },
        )
        tests.raise_for_status()
        help_response = await client.post(
            "/help",
            json={
                "terms": [solution_snippet],
                "backend": "duckdb",
                "detail": "full",
                "structured": True,
            },
        )
        help_response.raise_for_status()
    tests_payload = tests.json()
    help_payload = help_response.json()
    if tests_payload.get("errors") or help_payload.get("errors"):
        raise RuntimeError(f"Oracle leak preflight failed: tests={tests_payload.get('errors')} help={help_payload.get('errors')}")
    serialized = json.dumps(
        {
            key: help_payload.get(key)
            for key in (
                "doc_pages",
                "code_samples",
                "function_signatures",
                "function_tests",
            )
        },
        sort_keys=True,
    )
    tests_serialized = json.dumps(tests_payload.get("dataframe") or [], sort_keys=True)
    leak_sources = [
        source
        for source, leaked in (
            ("tests", solution_snippet in tests_serialized),
            ("help-name", solution_snippet in serialized),
            ("help-content", reference_query.strip() in serialized),
        )
        if leaked
    ]
    if leak_sources:
        visible_names = [
            row.get("NAME")
            for key in (
                "doc_pages",
                "code_samples",
                "function_signatures",
                "function_tests",
            )
            for row in (help_payload.get(key) or [])
            if isinstance(row, dict)
        ]
        raise RuntimeError(
            f"Oracle leakage detected for {task_id} through {leak_sources}; "
            f"visible names={visible_names}; send X-FeatureMesh-Eval-Hide-Solutions: 1 on MCP/API calls"
        )
    return {"tests_hidden": True, "help_hidden": True}
