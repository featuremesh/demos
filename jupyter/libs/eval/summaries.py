"""Concise human-readable summaries for benchmark run archives."""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from difflib import unified_diff
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def _code_details(title: str, content: str) -> str:
    return f"<details>\n<summary>{title}</summary>\n\n<pre>{html.escape(content.strip())}</pre>\n</details>"


def _parsed_result(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("text", "content", "slt"):
            if isinstance(result.get(key), str):
                return result[key]
    return result if isinstance(result, str) else json.dumps(result, default=str)


def _error_codes(result: Any) -> list[str]:
    return sorted(set(re.findall(r"\b(?:UE|OE|AE)/[A-Z0-9-]+\b", _result_text(result))))


def _reasoning_intent(reasoning: str) -> str:
    heading = re.search(r"\*\*(.+?)\*\*", reasoning)
    if heading:
        return heading.group(1).strip()
    first_line = next((line.strip() for line in reasoning.splitlines() if line.strip()), "")
    return first_line[:160]


def _tool_call_lines(name: str, arguments: dict[str, Any], previous_query: str | None) -> list[str]:
    if name == "featuremesh_help":
        terms = ", ".join(f"`{term}`" for term in arguments.get("terms", []))
        return [f"- Called `help()` for {terms}."]
    if name == "benchmark_context":
        operation = arguments.get("operation")
        target = arguments.get("path") or arguments.get("query") or ""
        suffix = f" `{target}`" if target else ""
        return [f"- Called benchmark context `{operation}`{suffix}."]
    query = arguments.get("query")
    if isinstance(query, str):
        if query == previous_query:
            return [f"- Called `{name}` with the unchanged query."]
        if previous_query:
            difference = "\n".join(
                unified_diff(
                    previous_query.splitlines(),
                    query.splitlines(),
                    fromfile="previous",
                    tofile="current",
                    lineterm="",
                )
            )
            return [
                f"- Called `{name}` with a revised query.",
                "",
                _code_details("Query changes", difference),
            ]
        return [f"- Called `{name}`.", "", _code_details("Query", query)]
    return [f"- Called `{name}`."]


def _tool_result_line(name: str, content: Any) -> str:
    result = _parsed_result(content)
    errors = result.get("errors") if isinstance(result, dict) else None
    codes = _error_codes(errors) if errors else []
    if codes:
        return f"- `{name}` returned errors: {', '.join(f'`{code}`' for code in codes)}."

    if name == "featuremesh_help":
        text = _result_text(result)
        headings = []
        for line in text.splitlines():
            if line.startswith("# "):
                heading = line.removeprefix("# ").replace("`", "").strip()
                if heading.lower().startswith("no-schema"):
                    continue
                if heading and heading not in headings:
                    headings.append(heading)
        sections = ", ".join(f"`{heading}`" for heading in headings[:6])
        suffix = f" Sections: {sections}." if sections else ""
        return f"- `help()` returned {len(text):,} characters.{suffix}"

    if name == "benchmark_context":
        if isinstance(result, dict) and isinstance(result.get("content"), str):
            return f"- Context returned `{result.get('path', 'document')}` ({len(result['content']):,} characters)."
        if isinstance(result, dict) and isinstance(result.get("files"), list):
            return f"- Context listed {len(result['files'])} files."
        if isinstance(result, list):
            return f"- Context returned {len(result)} entries."

    if name == "submit_featureql":
        accepted = isinstance(result, dict) and result.get("accepted")
        return f"- Submission {'accepted' if accepted else 'rejected'}."

    if isinstance(result, dict):
        errors = result.get("errors") or []
        warnings = result.get("warnings") or []
        dataframe = result.get("dataframe") or result.get("result")
        if warnings:
            warning = warnings[0]
            if isinstance(warning, dict):
                code = warning.get("code")
                message = warning.get("message")
                label = f"`{code}`: " if code else ""
                suffix = f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
                return f"- Warning {label}{message}{suffix}."
        facts = []
        if errors:
            facts.append(f"{len(errors)} errors")
        if isinstance(dataframe, list):
            facts.append(f"{len(dataframe)} rows")
        if facts:
            return f"- `{name}` returned {', '.join(facts)}."

    if name == "featuremesh_validate":
        return "- Validation completed without a structured error."
    if name == "featuremesh_query":
        return "- Query completed without a structured error."
    return f"- `{name}` completed."


def _usage_by_task(
    response_records: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    usage_by_task: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for record in response_records:
        task_id = str(record.get("task_id"))
        usage = (record.get("response") or {}).get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        values = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "cached_tokens": prompt_details.get("cached_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "cost": usage.get("cost", 0),
        }
        for key, value in values.items():
            if value is not None:
                usage_by_task[task_id][key] += float(value)
    return {task_id: dict(usage) for task_id, usage in usage_by_task.items()}


def _efficiency_lines(
    tool_records: list[dict[str, Any]],
    conversation: list[dict[str, Any]],
    *,
    shared_conversation: bool,
) -> list[str]:
    counts = Counter(str(record.get("name")) for record in tool_records)
    assistant_turns = sum((record.get("message") or {}).get("role") == "assistant" for record in conversation)
    help_records = [record for record in tool_records if record.get("name") == "featuremesh_help"]
    help_characters = sum(len(_result_text(record.get("result"))) for record in help_records)
    lines = [
        f"- {assistant_turns} agent turns and {len(tool_records)} tool calls: "
        f"{counts.get('featuremesh_help', 0)} help, "
        f"{counts.get('benchmark_context', 0)} context, "
        f"{counts.get('featuremesh_validate', 0)} validate, "
        f"{counts.get('featuremesh_query', 0)} query, "
        f"{counts.get('submit_featureql', 0)} submit.",
        f"- Help retrieval added {help_characters:,} characters across {len(help_records)} calls.",
    ]

    signatures = Counter(tuple((record.get("arguments") or {}).get("terms") or []) for record in help_records)
    repeated = [(terms, count) for terms, count in signatures.items() if terms and count > 1]
    for terms, count in repeated:
        context = " despite the shared conversation" if shared_conversation else ""
        lines.append(
            f"- Repeated help retrieval{context}: {', '.join(f'`{term}`' for term in terms)} was loaded {count} times. Load stable onboarding guidance once per conversation."
        )

    for index, record in enumerate(tool_records):
        if record.get("name") != "featuremesh_validate":
            continue
        warnings = (record.get("result") or {}).get("warnings") or []
        if not warnings:
            continue
        task_id = str(record.get("task_id"))
        later_records = tool_records[index + 1 :]
        clean_validation_offset = next(
            (
                offset
                for offset, later in enumerate(later_records)
                if later.get("task_id") == task_id and later.get("name") == "featuremesh_validate" and not ((later.get("result") or {}).get("warnings") or [])
            ),
            None,
        )
        if clean_validation_offset is None:
            continue
        help_between = sum(later.get("task_id") == task_id and later.get("name") == "featuremesh_help" for later in later_records[:clean_validation_offset])
        warning = warnings[0] if isinstance(warnings[0], dict) else {}
        code = warning.get("code", "warning")
        lines.append(
            f"- `{task_id}` cleared `{code}` after {help_between} additional help "
            "calls. The warning already included a concrete rewrite, so this is a "
            "candidate for reducing documentation detours."
        )

    return lines


def _task_efficiency_lines(
    task_ids: list[str],
    tool_records: list[dict[str, Any]],
    conversation: list[dict[str, Any]],
    task_usage: dict[str, dict[str, float]],
) -> list[str]:
    turn_counts = Counter(str(record.get("task_id")) for record in conversation if (record.get("message") or {}).get("role") == "assistant")
    tool_counts = Counter(str(record.get("task_id")) for record in tool_records)
    help_counts = Counter(str(record.get("task_id")) for record in tool_records if record.get("name") == "featuremesh_help")
    lines = ["- Per-task effort:"]
    for task_id in task_ids:
        usage = task_usage.get(task_id) or {}
        cost = usage.get("cost")
        cost_label = f"${float(cost):.5f}" if cost is not None else "cost unavailable"
        prompt_tokens = usage.get("prompt_tokens")
        cached_tokens = usage.get("cached_tokens", 0)
        cache_label = f"{float(cached_tokens) / float(prompt_tokens):.1%} cached" if prompt_tokens else "cache unavailable"
        lines.append(f"  - `{task_id}`: {turn_counts[task_id]} turns, {tool_counts[task_id]} tools, {help_counts[task_id]} help, {cost_label}, {cache_label}.")
    return lines


def _grade_line(task_id: str | None, grade: dict[str, Any]) -> str:
    label = f"`{task_id}`: " if task_id else ""
    status = "**passed**" if grade.get("passed") else "**failed**"
    facts = [status]
    if grade.get("oracle_valid") is not None:
        facts.append(f"oracle {'valid' if grade['oracle_valid'] else 'invalid'}")
    row_diff = grade.get("row_diff")
    if isinstance(row_diff, dict):
        missing = len(row_diff.get("missing") or [])
        unexpected = len(row_diff.get("unexpected") or [])
        if missing or unexpected:
            facts.append(f"{missing} missing / {unexpected} unexpected rows")
    if grade.get("reason"):
        facts.append(str(grade["reason"]))
    codes = _error_codes([
        *(grade.get("actual_errors") or []),
        *(grade.get("oracle_errors") or []),
    ])
    if codes:
        facts.append(", ".join(codes))
    return f"- {label}{'; '.join(facts)}."


def write_run_summary(run_directory: Path) -> Path:
    run = _read_json(run_directory / "run.json")
    consumption = _read_json(run_directory / "consumption.json")
    cost = _read_json(run_directory / "cost.json")
    grade = _read_json(run_directory / "grade.json")
    conversation = _read_jsonl(run_directory / "conversation.jsonl")
    tool_records = _read_jsonl(run_directory / "tool_calls.jsonl")
    submissions = _read_jsonl(run_directory / "submissions.jsonl")
    response_records = _read_jsonl(run_directory / "openrouter_responses.jsonl")

    task_usage = _usage_by_task(response_records)
    if task_usage:
        totals = {
            key: sum(usage.get(key, 0) for usage in task_usage.values())
            for key in (
                "prompt_tokens",
                "cached_tokens",
                "completion_tokens",
                "total_tokens",
                "cost",
            )
        }
    else:
        totals = consumption.get("totals") or consumption or run.get("usage", {})
    cache_hit_rate = float(totals.get("cached_tokens", 0)) / float(totals["prompt_tokens"]) if totals.get("prompt_tokens") else None
    task_ids = [str(task_id) for task_id in (run.get("episode_tasks") or [str(run.get("task_id"))])]
    task_label = ", ".join(task_ids)
    task_grades = grade.get("tasks")
    submitted_tasks = {str(submission.get("task_id")) for submission in submissions if submission.get("task_id")}
    graded_tasks = set(task_grades) if isinstance(task_grades, dict) else set(submitted_tasks) if grade else set()
    ungraded_tasks = sorted(submitted_tasks - graded_tasks)
    cost_value = totals.get("cost")
    if cost_value is None:
        cost_value = cost.get("cost", run.get("usage", {}).get("cost"))
    cost_label = f"${float(cost_value):.5f}" if cost_value is not None else "unknown"
    cache_label = f"{float(cache_hit_rate):.1%}" if cache_hit_rate is not None else "unknown"
    status = "harness error" if run.get("status") == "infrastructure_error" else str(run.get("status"))
    lines = [
        "# Benchmark run summary",
        "",
        "## Run",
        f"- Status: **{status}**",
        f"- Tasks: {task_label}",
        f"- Model: `{run.get('model')}`",
        f"- Assistance/profile: {run.get('assistance')} / {run.get('feature_profile')}",
        f"- Shared conversation: {run.get('shared_conversation', False)}",
        f"- Cost: {cost_label}",
        f"- Prompt cache hit rate: {cache_label}",
        f"- Tool calls: {len(tool_records)}",
        f"- Cleanup: {run.get('cleanup_status')}",
    ]
    if ungraded_tasks:
        lines.append(f"- Failure point: after {', '.join(f'`{task}`' for task in ungraded_tasks)} submitted, before grading.")
    elif run.get("error"):
        lines.append("- Failure details are retained in `run.json`.")

    lines.extend(["", "## Results"])
    if isinstance(task_grades, dict):
        lines.extend(_grade_line(task_id, task_grade) for task_id, task_grade in task_grades.items())
    elif grade:
        lines.append(_grade_line(None, grade))
    else:
        lines.append("- No grade record was produced.")
    lines.extend(f"- `{task_id}`: **submitted; grade unavailable due to harness failure**." for task_id in ungraded_tasks)

    efficiency_lines = _efficiency_lines(
        tool_records,
        conversation,
        shared_conversation=bool(run.get("shared_conversation")),
    )
    efficiency_lines = [
        *efficiency_lines[:2],
        *_task_efficiency_lines(
            task_ids,
            tool_records,
            conversation,
            task_usage,
        ),
        *efficiency_lines[2:],
    ]
    lines.extend([
        "",
        "## Efficiency review",
        *efficiency_lines,
    ])

    lines.extend(["", "## Conversation"])
    turns: dict[str, int] = defaultdict(int)
    last_queries: dict[str, str] = {}
    current_task: str | None = None
    for record in conversation:
        message = record.get("message") or {}
        role = str(message.get("role", "unknown"))
        task_id = str(record.get("task_id", "run"))
        content = message.get("content")
        if role == "system":
            continue
        if role == "user":
            if task_id != current_task:
                lines.extend(["", f"### {task_id}"])
                current_task = task_id
            lines.extend(["", "#### Question", "", _quote(str(content or ""))])
        elif role == "assistant":
            turns[task_id] += 1
            lines.extend(["", f"#### Turn {turns[task_id]}"])
            if message.get("reasoning"):
                lines.append(f"- Intent: {_reasoning_intent(str(message['reasoning']))}.")
            if content:
                lines.extend(["", "**Response**", "", _quote(str(content))])
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(arguments)
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                name = str(function.get("name", "unknown"))
                lines.extend([
                    "",
                    *_tool_call_lines(
                        name,
                        arguments,
                        last_queries.get(task_id),
                    ),
                ])
                query = arguments.get("query")
                if isinstance(query, str):
                    last_queries[task_id] = query
        elif role == "tool":
            lines.extend([_tool_result_line(str(message.get("name", "unknown")), content)])

    output = run_directory / "summary.md"
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def write_summaries(log_root: Path) -> list[Path]:
    return [write_run_summary(run_json.parent) for run_json in sorted(log_root.glob("*/*/run.json"))]
