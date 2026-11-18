"""Bounded OpenRouter tool-calling loop over a live FeatureMesh MCP session."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any

from .archive import RunArchive, redact
from .context_tool import CONTEXT_TOOL, SUBMIT_TOOL, BenchmarkContext
from .mcp_bridge import McpBridge
from .openrouter import OpenRouterClient

if TYPE_CHECKING:
    from .config import CampaignConfig


@dataclass(frozen=True)
class AgentOutcome:
    status: str
    submission: str | None
    turns: int
    tool_calls: int
    usage: dict[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def run_agent(
    *,
    campaign: CampaignConfig,
    model: str,
    task_id: str,
    prompt: str,
    subject_root: Any,
    mcp_url: str,
    project_token: str,
    archive: RunArchive,
    conversation: list[dict[str, Any]] | None = None,
) -> AgentOutcome:
    context = BenchmarkContext(subject_root)
    messages = conversation if conversation is not None else []
    repeated: Counter[str] = Counter()
    aggregate_usage: dict[str, float] = defaultdict(float)
    submission: str | None = None
    started = monotonic()
    total_tool_calls = 0
    total_tool_result_bytes = 0

    async with McpBridge(mcp_url, project_token) as bridge:
        system = (
            bridge.instructions.strip() + "\n\nBenchmark protocol: use only the listed tools and supplied context. "
            "Do not ask for or infer hidden grader assets. For each benchmark question, "
            "finish by calling submit_featureql exactly once with one FeatureQL query."
        )
        new_messages = [{"role": "user", "content": prompt}]
        if not messages:
            new_messages.insert(0, {"role": "system", "content": system})
        messages.extend(new_messages)
        tools = [*bridge.tools, CONTEXT_TOOL, SUBMIT_TOOL]
        archive.write(
            f"mcp_environment_{task_id}.json",
            {
                "model": model,
                "mcp_url": mcp_url,
                "mcp_instructions": system,
                "tool_schemas": tools,
            },
        )
        for message in new_messages:
            archive.append(
                "conversation.jsonl",
                {"at": _now(), "task_id": task_id, "message": message},
            )

        async with OpenRouterClient() as openrouter:
            for turn in range(1, campaign.budgets.turns + 1):
                if monotonic() - started > campaign.budgets.wall_seconds:
                    return AgentOutcome(
                        "wall_budget_exhausted",
                        submission,
                        turn - 1,
                        total_tool_calls,
                        dict(aggregate_usage),
                    )
                response, latency, retries = await openrouter.completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                    temperature=campaign.temperature,
                    max_tokens=max(
                        1,
                        campaign.budgets.output_tokens - int(aggregate_usage.get("completion_tokens", 0)),
                    ),
                    provider=campaign.provider,
                    model_parameters=campaign.model_parameters.get(model),
                )
                archive.append(
                    "openrouter_responses.jsonl",
                    {
                        "at": _now(),
                        "task_id": task_id,
                        "turn": turn,
                        "latency_seconds": latency,
                        "retries": retries,
                        "response": redact(response),
                    },
                )
                usage = response.get("usage") or {}
                for key, value in usage.items():
                    if isinstance(value, (int, float)):
                        aggregate_usage[key] += value
                prompt_details = usage.get("prompt_tokens_details") or {}
                completion_details = usage.get("completion_tokens_details") or {}
                cost_details = usage.get("cost_details") or {}
                aggregate_usage["cached_tokens"] += prompt_details.get("cached_tokens", 0)
                aggregate_usage["cache_write_tokens"] += prompt_details.get("cache_write_tokens", 0)
                aggregate_usage["reasoning_tokens"] += completion_details.get("reasoning_tokens", 0)
                aggregate_usage["upstream_inference_cost"] += cost_details.get("upstream_inference_cost", 0)
                choice = response["choices"][0]
                assistant = dict(choice["message"])
                messages.append(assistant)
                archive.append(
                    "conversation.jsonl",
                    {
                        "at": _now(),
                        "task_id": task_id,
                        "message": assistant,
                        "finish_reason": choice.get("finish_reason"),
                    },
                )
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    return AgentOutcome(
                        "no_submission",
                        None,
                        turn,
                        total_tool_calls,
                        dict(aggregate_usage),
                    )

                budget_status = None
                for tool_call in tool_calls:
                    total_tool_calls += 1
                    if total_tool_calls > campaign.budgets.tool_calls:
                        return AgentOutcome(
                            "tool_budget_exhausted",
                            submission,
                            turn,
                            total_tool_calls,
                            dict(aggregate_usage),
                        )
                    function = tool_call["function"]
                    name = function["name"]
                    raw_arguments = function.get("arguments") or "{}"
                    arguments: Any = raw_arguments
                    result: Any
                    tool_started = monotonic()
                    try:
                        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
                    except (TypeError, json.JSONDecodeError) as exc:
                        result = {
                            "error": "MALFORMED_TOOL_ARGUMENTS",
                            "message": str(exc),
                        }
                    else:
                        try:
                            signature = json.dumps([name, arguments], sort_keys=True, default=str)
                            repeated[signature] += 1
                            if repeated[signature] > campaign.budgets.identical_calls:
                                result = {
                                    "error": "REPEATED_TOOL_CALL_LIMIT",
                                    "message": "Choose a different action or submit.",
                                }
                                budget_status = "identical_call_budget_exhausted"
                            elif name == "benchmark_context":
                                operation = arguments.get("operation")
                                if operation == "list":
                                    result = context.list_files()
                                elif operation == "read":
                                    result = context.read(str(arguments.get("path", "")))
                                elif operation == "search":
                                    result = context.search(str(arguments.get("query", "")))
                                else:
                                    result = {"error": "Unknown context operation"}
                            elif name == "submit_featureql":
                                submission = str(arguments.get("query", "")).strip()
                                result = {"accepted": bool(submission)}
                                archive.append(
                                    "submissions.jsonl",
                                    {
                                        "at": _now(),
                                        "task_id": task_id,
                                        "turn": turn,
                                        "query": submission,
                                    },
                                )
                            else:
                                result = await bridge.call(name, arguments)
                        except Exception as exc:
                            result = {
                                "error": "TOOL_CALL_FAILED",
                                "message": str(exc),
                            }
                    serialized = json.dumps(result, default=str)
                    result_bytes = serialized.encode()
                    remaining_result_bytes = campaign.budgets.tool_result_bytes - total_tool_result_bytes
                    if len(result_bytes) > remaining_result_bytes:
                        serialized = result_bytes[: max(remaining_result_bytes, 0)].decode(errors="ignore") + "\n[TRUNCATED]"
                        budget_status = "tool_result_budget_exhausted"
                    total_tool_result_bytes += min(len(result_bytes), max(remaining_result_bytes, 0))
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": name,
                        "content": serialized,
                    }
                    messages.append(tool_message)
                    archive.append(
                        "tool_calls.jsonl",
                        {
                            "at": _now(),
                            "task_id": task_id,
                            "turn": turn,
                            "id": tool_call["id"],
                            "name": name,
                            "arguments": arguments,
                            "duration_seconds": monotonic() - tool_started,
                            "result": result,
                        },
                    )
                    archive.append(
                        "conversation.jsonl",
                        {"at": _now(), "task_id": task_id, "message": tool_message},
                    )
                if submission:
                    return AgentOutcome(
                        "submitted",
                        submission,
                        turn,
                        total_tool_calls,
                        dict(aggregate_usage),
                    )
                if budget_status:
                    return AgentOutcome(
                        budget_status,
                        submission,
                        turn,
                        total_tool_calls,
                        dict(aggregate_usage),
                    )
                if aggregate_usage.get("completion_tokens", 0) >= campaign.budgets.output_tokens:
                    return AgentOutcome(
                        "output_token_budget_exhausted",
                        submission,
                        turn,
                        total_tool_calls,
                        dict(aggregate_usage),
                    )
    return AgentOutcome(
        "turn_budget_exhausted",
        submission,
        campaign.budgets.turns,
        total_tool_calls,
        dict(aggregate_usage),
    )
