"""Harbour hard gate before legacy benchmark normalization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .headers import eval_api_url, eval_mcp_url
from .grading import grade_submission
from .project import ProjectController
from .setup import preflight_no_oracle_leak, setup_project

if TYPE_CHECKING:
    from pathlib import Path


async def validate_harbour_gate(subject: Path, oracle: Path, *, tasks: tuple[str, ...] = ("T1", "T7")) -> list[dict[str, Any]]:
    api_url = eval_api_url()
    mcp_url = eval_mcp_url()
    manifest = json.loads((oracle / "manifest.json").read_text(encoding="utf-8"))
    metadata = {task["id"]: task for task in manifest["tasks"]}
    controller = ProjectController.from_environment()
    results: list[dict[str, Any]] = []
    try:
        for task_id in tasks:
            project = await controller.create()
            try:
                await setup_project(
                    api_url=api_url,
                    mcp_url=mcp_url,
                    project_token=project.token,
                    subject=subject,
                    feature_profile="scratch",
                )
                task_root = oracle / "tasks" / task_id
                reference = (task_root / "reference.featureql").read_text(encoding="utf-8")
                await preflight_no_oracle_leak(
                    api_url=api_url,
                    project_token=project.token,
                    task_id=task_id,
                    solution_snippet=metadata[task_id]["solution_snippet"],
                    reference_query=reference,
                )
                correct = await grade_submission(
                    api_url=api_url,
                    project_token=project.token,
                    oracle_task=task_root,
                    query=reference,
                )
                wrong = await grade_submission(
                    api_url=api_url,
                    project_token=project.token,
                    oracle_task=task_root,
                    query="SELECT WRONG := 1;",
                )
                if not correct["passed"] or not correct["oracle_valid"] or wrong["passed"] or not any(wrong["row_diff"].values()):
                    raise RuntimeError(
                        f"Harbour grading gate failed for {task_id}: "
                        f"correct_passed={correct['passed']} "
                        f"oracle_valid={correct['oracle_valid']} "
                        f"actual_errors={correct['actual_errors']} "
                        f"expected_rows={correct['expected_rows']} "
                        f"actual_rows={correct['actual_rows']} "
                        f"oracle_rows={correct['oracle_rows']} "
                        f"sltest={correct['sltest']} "
                        f"wrong_passed={wrong['passed']}"
                    )
                results.append({
                    "task": task_id,
                    "reference_passed": True,
                    "wrong_failed": True,
                    "oracle_valid": correct["oracle_valid"],
                })
            finally:
                controller.delete_database(project)
                await controller.delete(project)
                if (controller.db_root / f"{project.name}.duckdb").exists():
                    raise RuntimeError(f"Project DuckDB file survived cleanup: {project.name}")
    finally:
        await controller.close()
    return results
