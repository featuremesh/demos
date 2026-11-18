"""Ordered episode execution with one shared project and fresh task conversations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .agent import run_agent
from .archive import RunArchive, run_timestamp
from .grading import grade_submission
from .headers import eval_api_url, eval_mcp_url, eval_request_headers
from .packages import assistance_payload
from .project import ProjectController
from .setup import preflight_no_oracle_leak, setup_project

if TYPE_CHECKING:
    from .config import CampaignConfig

_SEPARATOR = "-- BENCH_EVAL_STATEMENT --"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _apply_transition(api_url: str, project_token: str, transition: Path) -> list[dict[str, Any]]:
    headers = eval_request_headers(project_token)
    results = []
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=120) as client:
        for statement in transition.read_text(encoding="utf-8").split(_SEPARATOR):
            response = await client.post(
                "/query",
                json={
                    "query": statement.strip(),
                    "backend": "duckdb",
                    "structured": True,
                },
            )
            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise RuntimeError(f"Episode transition failed: {result['errors']}")
            results.append(result)
    return results


async def run_episode(
    *,
    campaign: CampaignConfig,
    model: str,
    episode_id: str,
    assistance: str,
    feature_profile: str,
    repetition: int,
    subject: Path,
    oracle: Path,
    shared_conversation: bool = False,
    archive_root: Path = Path("logs/bench_eval"),
) -> dict[str, Any]:
    api_url = eval_api_url()
    mcp_url = eval_mcp_url()
    subject_manifest = json.loads((subject / "manifest.json").read_text(encoding="utf-8"))
    episodes = {episode["id"]: episode for episode in subject_manifest.get("episodes", [])}
    if episode_id not in episodes:
        raise ValueError(f"Unknown episode {episode_id}")
    oracle_manifest = json.loads((oracle / "manifest.json").read_text(encoding="utf-8"))
    oracle_tasks = {task["id"]: task for task in oracle_manifest["tasks"]}
    run_id = f"{run_timestamp()}-{campaign.arm}-episode-{episode_id}-{assistance}-{feature_profile}-r{repetition}-{uuid.uuid4().hex[:8]}"
    archive = RunArchive(archive_root, campaign.campaign_id, run_id)
    record: dict[str, Any] = {
        "run_id": run_id,
        "campaign_id": campaign.campaign_id,
        "arm": campaign.arm,
        "model": model,
        "suite": subject_manifest["suite"],
        "task_id": f"episode:{episode_id}",
        "episode_tasks": episodes[episode_id]["tasks"],
        "assistance": assistance,
        "feature_profile": feature_profile,
        "repetition": repetition,
        "shared_conversation": shared_conversation,
        "budgets": campaign.budgets.__dict__,
        "status": "provisioning",
        "started_at": _now(),
    }
    archive.write("run.json", record)
    archive.write(
        "environment.json",
        {
            "api_url": api_url,
            "mcp_url": mcp_url,
            "subject_hashes": subject_manifest["hashes"],
            "oracle_hashes": oracle_manifest["hashes"],
        },
    )
    controller = ProjectController.from_environment()
    project = None
    grades: dict[str, Any] = {}
    conversation: list[dict[str, Any]] | None = [] if shared_conversation else None
    try:
        project = await controller.create()
        record.update({
            "project_id": project.project_id,
            "project_reference": project.reference,
            "status": "setup",
        })
        archive.write("run.json", record)
        setup = await setup_project(
            api_url=api_url,
            mcp_url=mcp_url,
            project_token=project.token,
            subject=subject,
            feature_profile=feature_profile,
        )
        archive.write("setup.json", setup)
        for task_index, task_id in enumerate(episodes[episode_id]["tasks"]):
            oracle_task = oracle / "tasks" / task_id
            leak = await preflight_no_oracle_leak(
                api_url=api_url,
                project_token=project.token,
                task_id=task_id,
                solution_snippet=oracle_tasks[task_id]["solution_snippet"],
                reference_query=(oracle_task / "reference.featureql").read_text(encoding="utf-8"),
            )
            archive.write(f"leak_preflight_{task_id}.json", leak)
            prompt = assistance_payload(subject, oracle, task_id, assistance)
            transition_namespace = episodes[episode_id].get("transition_namespace")
            if task_index and transition_namespace:
                prompt += (
                    f"\n\nEarlier tasks in this episode created reusable state under `{transition_namespace}`. Discover and reuse it rather than rebuilding the earlier result."
                )
            outcome = await run_agent(
                campaign=campaign,
                model=model,
                task_id=task_id,
                prompt=prompt,
                subject_root=subject,
                mcp_url=mcp_url,
                project_token=project.token,
                archive=archive,
                conversation=conversation,
            )
            task_outcome = {
                "agent_status": outcome.status,
                "turns": outcome.turns,
                "tool_calls": outcome.tool_calls,
                "usage": outcome.usage,
                "passed": None,
            }
            record.setdefault("task_outcomes", {})[task_id] = task_outcome
            grade = (
                await grade_submission(
                    api_url=api_url,
                    project_token=project.token,
                    oracle_task=oracle_task,
                    query=outcome.submission,
                )
                if outcome.submission
                else {"passed": False, "reason": outcome.status}
            )
            grades[task_id] = grade
            if grade.get("oracle_valid") is False:
                raise RuntimeError(f"Direct SQL oracle disagrees with expected rows for {task_id}")
            task_outcome["passed"] = grade["passed"]
            transition = oracle_tasks[task_id].get("transition")
            if grade["passed"] and transition:
                transition_results = await _apply_transition(api_url, project.token, oracle / transition)
                archive.write(
                    f"transition_{task_id}.json",
                    {"results": transition_results},
                )
            elif not grade["passed"] and (not shared_conversation or transition_namespace):
                break
        record["status"] = "passed" if len(grades) == len(episodes[episode_id]["tasks"]) and all(grade["passed"] for grade in grades.values()) else "failed"
    except Exception as exc:
        record.update({"status": "infrastructure_error", "error": str(exc)})
    finally:
        cleanup_status = "not_created"
        if project is not None:
            try:
                controller.delete_database(project)
                await controller.delete(project)
                cleanup_status = "complete"
            except Exception as exc:
                controller.queue_cleanup(project, exc)
                cleanup_status = "cleanup_pending"
        await controller.close()
        record.update({
            "cleanup_status": cleanup_status,
            "finished_at": _now(),
        })
        task_usages = {task_id: outcome["usage"] for task_id, outcome in record.get("task_outcomes", {}).items()}
        usage_totals = {
            key: sum(float(usage.get(key, 0)) for usage in task_usages.values())
            for key in (
                "prompt_tokens",
                "cached_tokens",
                "cache_write_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "total_tokens",
                "cost",
                "upstream_inference_cost",
            )
        }
        archive.write(
            "consumption.json",
            {
                "tasks": task_usages,
                "totals": {key: value for key, value in usage_totals.items() if key not in {"cost", "upstream_inference_cost"}},
                "prompt_cache_hit_rate": (usage_totals["cached_tokens"] / usage_totals["prompt_tokens"] if usage_totals["prompt_tokens"] else None),
            },
        )
        archive.write(
            "cost.json",
            {
                "cost": usage_totals["cost"],
                "upstream_inference_cost": usage_totals["upstream_inference_cost"],
            },
        )
        archive.write("grade.json", {"tasks": grades})
        archive.write("run.json", record)
    return record
