"""Sequential campaign runner with clean project state per scored tuple."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import random
import subprocess  # nosec B404
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .agent import run_agent
from .archive import RunArchive, redact, run_timestamp
from .grading import grade_submission
from .headers import eval_api_url, eval_mcp_url
from .packages import assistance_payload
from .project import Project, ProjectController
from .setup import preflight_no_oracle_leak, setup_project

if TYPE_CHECKING:
    from .config import CampaignConfig


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _git_sha(path: Path) -> str:
    return subprocess.run(  # nosec B603, B607
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _copy_request_logs(request_log_root: Path | None, archive: RunArchive, started_epoch: float) -> None:
    if request_log_root is None or not request_log_root.exists():
        return
    destination = archive.path / "featuremesh_requests"
    for path in request_log_root.glob("*.txt"):
        if path.stat().st_mtime >= started_epoch:
            content = path.read_text(encoding="utf-8", errors="replace")
            (destination / path.name).write_text(
                str(redact(content)),
                encoding="utf-8",
            )


async def run_campaign(
    *,
    campaign: CampaignConfig,
    subject: Path,
    oracle: Path,
    archive_root: Path = Path("logs/bench_eval"),
) -> list[dict[str, Any]]:
    api_url = eval_api_url()
    mcp_url = eval_mcp_url()
    request_log_root_value = os.getenv("FEATUREMESH_REQUEST_LOG_DIRECTORY")
    request_log_root = Path(request_log_root_value) if request_log_root_value else None
    client_repo = Path(
        os.getenv(
            "FEATUREMESH_CLIENT_REPO",
            str(Path.cwd().parent / "featuremesh-client-py"),
        )
    )
    client_git = _git_sha(client_repo) if (client_repo / ".git").exists() else None
    subject_manifest = json.loads((subject / "manifest.json").read_text(encoding="utf-8"))
    oracle_manifest = json.loads((oracle / "manifest.json").read_text(encoding="utf-8"))
    oracle_tasks = {task["id"]: task for task in oracle_manifest["tasks"]}
    subject_tasks = {task["id"]: task for task in subject_manifest["tasks"]}
    selected = [task for task in campaign.tasks if task in oracle_tasks]
    if len(selected) != len(campaign.tasks):
        missing = sorted(set(campaign.tasks) - set(selected))
        raise ValueError(f"Campaign references unknown tasks: {missing}")
    episode_only = [task for task in selected if subject_tasks[task]["episode_only"]]
    if episode_only:
        raise ValueError(f"Tasks require an ordered episode: {episode_only}; use run-episode")

    controller = ProjectController.from_environment()
    results: list[dict[str, Any]] = []
    dimensions = list(
        itertools.product(
            campaign.models,
            selected,
            campaign.assistance,
            campaign.feature_profiles,
            range(1, campaign.repetitions + 1),
        )
    )
    random.Random(campaign.order_seed).shuffle(dimensions)
    try:
        for model, task_id, assistance, profile, repetition in dimensions:
            run_id = f"{run_timestamp()}-{campaign.arm}-{task_id}-{assistance}-{profile}-r{repetition}-{uuid.uuid4().hex[:8]}"
            archive = RunArchive(archive_root, campaign.campaign_id, run_id)
            run_started_epoch = time.time()
            run_started_monotonic = time.monotonic()
            project: Project | None = None
            run_record: dict[str, Any] = {
                "run_id": run_id,
                "campaign_id": campaign.campaign_id,
                "arm": campaign.arm,
                "model": model,
                "suite": subject_manifest["suite"],
                "task_id": task_id,
                "assistance": assistance,
                "feature_profile": profile,
                "difficulty": subject_tasks[task_id]["difficulty"],
                "repetition": repetition,
                "status": "provisioning",
                "started_at": _now(),
                "hashes": {
                    "subject_manifest": _file_hash(subject / "manifest.json"),
                    "oracle_manifest": _file_hash(oracle / "manifest.json"),
                    "registry_git": _git_sha(Path.cwd()),
                    "client_git": client_git,
                    "docs_corpus": _value_hash(subject_manifest["hashes"]),
                },
                "budgets": campaign.budgets.__dict__,
            }
            archive.write("run.json", run_record)
            archive.write(
                "environment.json",
                {
                    "api_url": api_url,
                    "mcp_url": mcp_url,
                    "subject_hashes": subject_manifest["hashes"],
                    "oracle_hashes": oracle_manifest["hashes"],
                    "registry_git": run_record["hashes"]["registry_git"],
                    "client_git": client_git,
                    "campaign": asdict(campaign),
                },
            )
            try:
                project = await controller.create()
                run_record.update({
                    "project_id": project.project_id,
                    "project_reference": project.reference,
                    "status": "setup",
                })
                archive.write("run.json", run_record)
                setup = await setup_project(
                    api_url=api_url,
                    mcp_url=mcp_url,
                    project_token=project.token,
                    subject=subject,
                    feature_profile=profile,
                )
                archive.write("setup.json", setup)
                oracle_task = oracle / "tasks" / task_id
                reference_query = (oracle_task / "reference.featureql").read_text(encoding="utf-8")
                leak = await preflight_no_oracle_leak(
                    api_url=api_url,
                    project_token=project.token,
                    task_id=task_id,
                    solution_snippet=oracle_tasks[task_id]["solution_snippet"],
                    reference_query=reference_query,
                )
                archive.write("leak_preflight.json", leak)
                run_record["status"] = "running"
                archive.write("run.json", run_record)
                prompt = assistance_payload(subject, oracle, task_id, assistance)
                profile_namespace = subject_manifest["feature_profiles"][profile].get("namespace")
                if profile_namespace:
                    prompt += f"\n\nA reusable semantic layer is available under `{profile_namespace}`. Discover it with describe(); do not assume its formulas."
                outcome = await run_agent(
                    campaign=campaign,
                    model=model,
                    task_id=task_id,
                    prompt=prompt,
                    subject_root=subject,
                    mcp_url=mcp_url,
                    project_token=project.token,
                    archive=archive,
                )
                prompt_tokens = outcome.usage.get("prompt_tokens", 0)
                archive.write(
                    "consumption.json",
                    {
                        "prompt_tokens": prompt_tokens,
                        "cached_tokens": outcome.usage.get("cached_tokens", 0),
                        "cache_write_tokens": outcome.usage.get("cache_write_tokens", 0),
                        "prompt_cache_hit_rate": (outcome.usage.get("cached_tokens", 0) / prompt_tokens if prompt_tokens else None),
                        "completion_tokens": outcome.usage.get("completion_tokens", 0),
                        "reasoning_tokens": outcome.usage.get("reasoning_tokens", 0),
                        "total_tokens": outcome.usage.get("total_tokens", 0),
                    },
                )
                archive.write(
                    "cost.json",
                    {
                        "cost": outcome.usage.get("cost", 0),
                        "upstream_inference_cost": outcome.usage.get(
                            "upstream_inference_cost",
                            0,
                        ),
                    },
                )
                mcp_environment = json.loads((archive.path / f"mcp_environment_{task_id}.json").read_text(encoding="utf-8"))
                run_record["hashes"].update({
                    "mcp_instructions": _value_hash(mcp_environment["mcp_instructions"]),
                    "tool_schemas": _value_hash(mcp_environment["tool_schemas"]),
                })
                if outcome.submission:
                    grade = await grade_submission(
                        api_url=api_url,
                        project_token=project.token,
                        oracle_task=oracle_task,
                        query=outcome.submission,
                    )
                else:
                    grade = {
                        "passed": False,
                        "oracle_valid": None,
                        "row_diff": None,
                        "reason": outcome.status,
                    }
                archive.write("grade.json", grade)
                if grade.get("oracle_valid") is False:
                    raise RuntimeError(f"Direct SQL oracle disagrees with expected rows for {task_id}")
                run_record.update({
                    "status": "passed" if grade["passed"] else "failed",
                    "agent_status": outcome.status,
                    "turns": outcome.turns,
                    "tool_calls": outcome.tool_calls,
                    "usage": outcome.usage,
                    "submission_chars": len(outcome.submission or ""),
                    "prebuilt_namespace_reused": bool(profile_namespace and outcome.submission and profile_namespace.lower() in outcome.submission.lower()),
                    "elapsed_seconds": time.monotonic() - run_started_monotonic,
                    "finished_at": _now(),
                })
            except Exception as exc:
                run_record.update({
                    "status": "infrastructure_error",
                    "error": str(exc),
                    "finished_at": _now(),
                })
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
                run_record["cleanup_status"] = cleanup_status
                _copy_request_logs(request_log_root, archive, run_started_epoch)
                archive.write("run.json", run_record)
                results.append(run_record)
    finally:
        await controller.close()
    return results
