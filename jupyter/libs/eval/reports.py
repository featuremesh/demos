"""Paired harness-quality summaries from append-only run archives."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


def _read_runs(campaign_root: Path) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(campaign_root.glob("*/run.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        run["_path"] = path.parent
        runs.append(run)
    return runs


def _tool_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(run["_path"]) / "tool_calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _failure_class(run: dict[str, Any]) -> str | None:
    if run.get("failure_class"):
        return str(run["failure_class"])
    if run["status"] == "passed":
        return None
    if run["status"] == "infrastructure_error":
        return "engine defect"
    if run.get("agent_status") in {
        "no_submission",
        "tool_budget_exhausted",
        "turn_budget_exhausted",
    }:
        return "model/tool-protocol failure"
    calls = _tool_records(run)
    serialized_calls = json.dumps(calls, default=str)
    if "MALFORMED_TOOL_ARGUMENTS" in serialized_calls:
        return "model/tool-protocol failure"
    if "TOOL_CALL_FAILED" in serialized_calls:
        return "broken/unhelpful tool"
    if "Unknown tool" in serialized_calls:
        return "missing tool"
    featuremesh_calls = [call for call in calls if call["name"].startswith("featuremesh_")]
    if not featuremesh_calls:
        return "tool non-use"
    help_calls = [call for call in calls if call["name"] == "featuremesh_help"]
    if help_calls:
        if all(not call.get("result") for call in help_calls):
            return "documentation-routing"
        return "documentation-retention"
    grade_path = Path(run["_path"]) / "grade.json"
    if grade_path.exists():
        grade = json.loads(grade_path.read_text(encoding="utf-8"))
        if grade.get("oracle_valid") is False:
            return "task/spec defect"
        if "AE/" in json.dumps(grade.get("actual_errors", [])):
            return "engine defect"
    return "language gap"


def _has_error(value: Any) -> bool:
    if isinstance(value, dict):
        if any(value.get(key) for key in ("error", "errors")):
            return True
        return any(_has_error(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_error(item) for item in value)
    return False


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _mean(runs: list[dict[str, Any]], key: str) -> float | None:
    values = [float(run[key]) for run in runs if run.get(key) is not None]
    return mean(values) if values else None


def _usage_sum(runs: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for run in runs:
        usage = run.get("usage", {})
        if key in usage:
            total += float(usage[key])
            continue
        if key != "cached_tokens":
            continue
        path = Path(run["_path"]) / "openrouter_responses.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    response_usage = json.loads(line).get("response", {}).get("usage", {})
                    total += float(
                        response_usage.get("prompt_tokens_details", {}).get(
                            "cached_tokens",
                            0,
                        )
                    )
    return total


def _first_query_failed(run: dict[str, Any]) -> bool:
    first_query = next(
        (call for call in _tool_records(run) if call["name"] == "featuremesh_query"),
        None,
    )
    return first_query is not None and _has_error(first_query.get("result", {}))


def build_report(
    campaign_root: Path,
    *,
    model_order: list[str],
    target_solve_rate: float,
    target_recovery_rate: float,
) -> dict[str, Any]:
    runs = _read_runs(campaign_root)
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_arm[run["arm"]].append(run)

    arms: dict[str, Any] = {}
    for arm, arm_runs in by_arm.items():
        scored = [run for run in arm_runs if run["status"] != "infrastructure_error"]
        passed = [run for run in scored if run["status"] == "passed"]
        a0 = [run for run in scored if run["assistance"] == "A0"]
        recoverable = 0
        recovered = 0
        tool_usage: dict[str, int] = defaultdict(int)
        error_codes: dict[str, int] = defaultdict(int)
        diagnostics = {
            "help_calls": 0,
            "validate_calls": 0,
            "diagnose_calls": 0,
            "successful_after_help": 0,
            "malformed_tool_calls": 0,
            "structured_output_omissions": 0,
        }
        for run in scored:
            calls = _tool_records(run)
            for call in calls:
                tool_usage[call["name"]] += 1
                serialized_result = json.dumps(call.get("result", {}), default=str)
                for code in re.findall(r"\b(?:UE|OE|AE)/[A-Z0-9-]+\b", serialized_result):
                    error_codes[code] += 1
                if call["name"] == "featuremesh_help":
                    diagnostics["help_calls"] += 1
                elif call["name"] == "featuremesh_validate":
                    diagnostics["validate_calls"] += 1
                elif call["name"] == "featuremesh_diagnose":
                    diagnostics["diagnose_calls"] += 1
                if "MALFORMED_TOOL_ARGUMENTS" in serialized_result:
                    diagnostics["malformed_tool_calls"] += 1
                if call["name"] in {
                    "featuremesh_query",
                    "featuremesh_translate",
                    "featuremesh_validate",
                    "featuremesh_describe",
                    "featuremesh_help",
                    "featuremesh_diagnose",
                } and "structured" not in call.get("arguments", {}):
                    diagnostics["structured_output_omissions"] += 1
            query_calls = [call for call in calls if call["name"] == "featuremesh_query"]
            first_failed = bool(query_calls) and _has_error(query_calls[0].get("result", {}))
            if first_failed:
                recoverable += 1
                recovered += run["status"] == "passed"
            if run["status"] == "passed" and any(call["name"] == "featuremesh_help" for call in calls):
                diagnostics["successful_after_help"] += 1
        by_model: dict[str, Any] = {}
        for model in model_order:
            model_runs = [run for run in scored if run["model"] == model]
            model_recoverable = [run for run in model_runs if _first_query_failed(run)]
            solve_values = [run["status"] == "passed" for run in model_runs]
            prompt_tokens = _usage_sum(model_runs, "prompt_tokens")
            by_model[model] = {
                "runs": len(model_runs),
                "solve_rate": _rate(solve_values),
                "solve_stddev": pstdev(solve_values) if len(solve_values) > 1 else 0,
                "recovery_rate": _rate([run["status"] == "passed" for run in model_recoverable]),
                "mean_tool_calls": _mean(model_runs, "tool_calls"),
                "mean_tokens": _mean(
                    [
                        {"tokens": run.get("usage", {}).get("total_tokens") or (run.get("usage", {}).get("prompt_tokens", 0) + run.get("usage", {}).get("completion_tokens", 0))}
                        for run in model_runs
                    ],
                    "tokens",
                ),
                "mean_cost": _mean(
                    [{"cost": run.get("usage", {}).get("cost")} for run in model_runs],
                    "cost",
                ),
                "total_cost": _usage_sum(model_runs, "cost"),
                "prompt_cache_hit_rate": (_usage_sum(model_runs, "cached_tokens") / prompt_tokens if prompt_tokens else None),
                "mean_elapsed_seconds": _mean(model_runs, "elapsed_seconds"),
            }
        frontier = None
        for model in reversed(model_order):
            metrics = by_model[model]
            recovery_rate = metrics["recovery_rate"]
            if metrics["solve_rate"] is not None and metrics["solve_rate"] >= target_solve_rate and (recovery_rate is None or recovery_rate >= target_recovery_rate):
                frontier = model
                break
        failures: dict[str, int] = defaultdict(int)
        for run in scored:
            classification = _failure_class(run)
            if classification:
                failures[classification] += 1
        difficulties = sorted({int(run["difficulty"]) for run in scored if "difficulty" in run})
        arm_prompt_tokens = _usage_sum(scored, "prompt_tokens")
        arms[arm] = {
            "runs": len(scored),
            "solve_rate": len(passed) / len(scored) if scored else None,
            "a0_solve_rate": (sum(run["status"] == "passed" for run in a0) / len(a0) if a0 else None),
            "harness_frontier": frontier,
            "recovery_rate": (recovered / recoverable if recoverable else None),
            "meets_recovery_target": (recovered / recoverable >= target_recovery_rate if recoverable else None),
            "total_cost": _usage_sum(scored, "cost"),
            "prompt_cache_hit_rate": (_usage_sum(scored, "cached_tokens") / arm_prompt_tokens if arm_prompt_tokens else None),
            "by_model": by_model,
            "by_difficulty": {
                str(difficulty): {
                    "runs": len(difficulty_runs := [run for run in scored if run.get("difficulty") == difficulty]),
                    "solve_rate": _rate([run["status"] == "passed" for run in difficulty_runs]),
                }
                for difficulty in difficulties
            },
            "tool_usage": dict(tool_usage),
            "error_codes": dict(error_codes),
            "diagnostics": diagnostics,
            "prebuilt_reuse_rate": _rate([bool(run.get("prebuilt_namespace_reused")) for run in scored if run["feature_profile"] == "prebuilt"]),
            "failure_classes": dict(failures),
        }

    pairs: list[dict[str, Any]] = []
    baseline = {
        (
            run["model"],
            run["task_id"],
            run["assistance"],
            run["feature_profile"],
            run["repetition"],
        ): run
        for run in by_arm.get("baseline", [])
    }
    for candidate in by_arm.get("candidate", []):
        key = (
            candidate["model"],
            candidate["task_id"],
            candidate["assistance"],
            candidate["feature_profile"],
            candidate["repetition"],
        )
        if key in baseline:
            pairs.append({
                "dimensions": key,
                "baseline_passed": baseline[key]["status"] == "passed",
                "candidate_passed": candidate["status"] == "passed",
                "tool_call_delta": candidate.get("tool_calls", 0) - baseline[key].get("tool_calls", 0),
            })

    assistance_order = ("A0", "A1", "A2", "A3")
    minimum_assistance: list[dict[str, Any]] = []
    grouped_attempts: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run["status"] != "infrastructure_error":
            grouped_attempts[
                (
                    run["arm"],
                    run["model"],
                    run["task_id"],
                    run["feature_profile"],
                    run["repetition"],
                )
            ].append(run)
    for dimensions, attempts in grouped_attempts.items():
        passing_levels = {run["assistance"] for run in attempts if run["status"] == "passed"}
        minimum_assistance.append({
            "dimensions": dimensions,
            "minimum_assistance": next(
                (level for level in assistance_order if level in passing_levels),
                "unsolved",
            ),
        })

    profile_pairs: list[dict[str, Any]] = []
    scratch = {
        (
            run["arm"],
            run["model"],
            run["task_id"],
            run["assistance"],
            run["repetition"],
        ): run
        for run in runs
        if run.get("feature_profile") == "scratch" and run["status"] != "infrastructure_error"
    }
    for prebuilt in runs:
        key = (
            prebuilt["arm"],
            prebuilt["model"],
            prebuilt["task_id"],
            prebuilt["assistance"],
            prebuilt["repetition"],
        )
        if prebuilt.get("feature_profile") == "prebuilt" and prebuilt["status"] != "infrastructure_error" and key in scratch:
            baseline_run = scratch[key]
            profile_pairs.append({
                "dimensions": key,
                "scratch_passed": baseline_run["status"] == "passed",
                "prebuilt_passed": prebuilt["status"] == "passed",
                "tool_call_reduction": baseline_run.get("tool_calls", 0) - prebuilt.get("tool_calls", 0),
                "query_char_reduction": baseline_run.get("submission_chars", 0) - prebuilt.get("submission_chars", 0),
                "elapsed_reduction": baseline_run.get("elapsed_seconds", 0) - prebuilt.get("elapsed_seconds", 0),
            })
    return {
        "arms": arms,
        "paired_runs": pairs,
        "minimum_assistance": minimum_assistance,
        "profile_pairs": profile_pairs,
    }


def write_report(campaign_root: Path, report: dict[str, Any]) -> None:
    (campaign_root / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Harness-quality report", ""]
    for arm, metrics in report["arms"].items():
        lines.extend([
            f"## {arm}",
            "",
            f"- Runs: {metrics['runs']}",
            f"- Solve rate: {metrics['solve_rate']}",
            f"- A0 solve rate: {metrics['a0_solve_rate']}",
            f"- Harness frontier: {metrics['harness_frontier'] or 'none'}",
            f"- Recovery rate: {metrics['recovery_rate']}",
            f"- Total cost: {metrics['total_cost']}",
            f"- Prompt cache hit rate: {metrics['prompt_cache_hit_rate']}",
            f"- Prebuilt reuse rate: {metrics['prebuilt_reuse_rate']}",
            f"- Failure classes: {json.dumps(metrics['failure_classes'], sort_keys=True)}",
            "",
        ])
    lines.append(f"Paired runs: {len(report['paired_runs'])}")
    lines.append(f"Scratch/prebuilt pairs: {len(report['profile_pairs'])}")
    (campaign_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
