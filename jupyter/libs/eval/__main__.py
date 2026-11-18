"""CLI for benchmark export, execution, smoke gates, cleanup, and reports."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from .archive import validate_run_archive
from .config import load_campaign
from .episodes import run_episode
from .openrouter import OpenRouterClient
from .packages import export_suite
from .project import ProjectController
from .reports import build_report, write_report
from .runner import run_campaign
from .smoke import validate_harbour_gate
from .summaries import write_run_summary, write_summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m libs.eval")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)

    models = commands.add_parser("models")
    models.add_argument("--campaign", type=Path, required=True)
    models.add_argument("--output", type=Path, required=True)

    run = commands.add_parser("run")
    run.add_argument("--campaign", type=Path, required=True)
    run.add_argument("--subject", type=Path, required=True)
    run.add_argument("--oracle", type=Path, required=True)

    episode = commands.add_parser("run-episode")
    episode.add_argument("--campaign", type=Path, required=True)
    episode.add_argument("--subject", type=Path, required=True)
    episode.add_argument("--oracle", type=Path, required=True)
    episode.add_argument("--episode", required=True)
    episode.add_argument("--model")
    episode.add_argument("--assistance", default="A0")
    episode.add_argument("--feature-profile", default="scratch")
    episode.add_argument("--repetition", type=int, default=1)
    episode.add_argument("--shared-conversation", action="store_true")
    episode.add_argument("--tool-result-bytes", type=int)

    smoke = commands.add_parser("smoke-harbour")
    smoke.add_argument("--campaign", type=Path, required=True)
    smoke.add_argument("--subject", type=Path, required=True)
    smoke.add_argument("--oracle", type=Path, required=True)

    report = commands.add_parser("report")
    report.add_argument("--campaign", type=Path, required=True)
    report.add_argument("--logs", type=Path, default=Path("logs/bench_eval"))

    summarize = commands.add_parser("summarize")
    summarize.add_argument("--logs", type=Path, default=Path("logs/bench_eval"))
    summarize.add_argument("--run", type=Path)

    commands.add_parser("reconcile")
    return parser


async def _models(campaign_path: Path, output: Path) -> None:
    campaign = load_campaign(campaign_path)
    async with OpenRouterClient() as client:
        models = await client.models()
    by_id = {model["id"]: model for model in models}
    missing = [model for model in campaign.models if model not in by_id]
    unsupported = [model for model in campaign.models if model in by_id and "tools" not in (by_id[model].get("supported_parameters") or [])]
    if missing or unsupported:
        raise RuntimeError(f"Invalid model ladder: missing={missing}, without tools={unsupported}")
    snapshot = [by_id[model] for model in campaign.models]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def _reconcile() -> None:
    controller = ProjectController.from_environment()
    try:
        remaining = await controller.reconcile()
    finally:
        await controller.close()
    print(json.dumps({"cleanup_pending": remaining}, indent=2))


async def _main() -> None:
    args = _parser().parse_args()
    if args.command == "export":
        subject, oracle = export_suite(args.source, args.output)
        print(json.dumps({"subject": str(subject), "oracle": str(oracle)}, indent=2))
    elif args.command == "models":
        await _models(args.campaign, args.output)
    elif args.command == "run":
        campaign = load_campaign(args.campaign)
        results = await run_campaign(campaign=campaign, subject=args.subject, oracle=args.oracle)
        print(json.dumps(results, indent=2))
    elif args.command == "run-episode":
        campaign = load_campaign(args.campaign)
        if args.tool_result_bytes is not None:
            if args.tool_result_bytes <= 0:
                raise ValueError("--tool-result-bytes must be positive")
            campaign = replace(
                campaign,
                budgets=replace(
                    campaign.budgets,
                    tool_result_bytes=args.tool_result_bytes,
                ),
            )
        result = await run_episode(
            campaign=campaign,
            model=args.model or campaign.models[0],
            episode_id=args.episode,
            assistance=args.assistance,
            feature_profile=args.feature_profile,
            repetition=args.repetition,
            subject=args.subject,
            oracle=args.oracle,
            shared_conversation=args.shared_conversation,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "smoke-harbour":
        campaign = load_campaign(args.campaign)
        gate = await validate_harbour_gate(args.subject, args.oracle)
        pilot = replace(
            campaign,
            models=(campaign.models[-1],),
            tasks=("T1", "T7"),
            assistance=("A0",),
            feature_profiles=("scratch",),
            repetitions=1,
            budgets=replace(
                campaign.budgets,
                tool_result_bytes=4 * 1024 * 1024,
            ),
            scored=False,
        )
        runs = await run_campaign(campaign=pilot, subject=args.subject, oracle=args.oracle)
        for run in runs:
            validate_run_archive(Path("logs/bench_eval") / pilot.campaign_id / run["run_id"])
        print(json.dumps({"gate": gate, "runs": runs}, indent=2))
    elif args.command == "report":
        campaign = load_campaign(args.campaign, require_secret=False)
        root = args.logs / campaign.campaign_id
        report = build_report(
            root,
            model_order=list(campaign.models),
            target_solve_rate=campaign.target_solve_rate,
            target_recovery_rate=campaign.target_recovery_rate,
        )
        write_report(root, report)
        print(json.dumps(report, indent=2))
    elif args.command == "summarize":
        paths = [write_run_summary(args.run)] if args.run else write_summaries(args.logs)
        print(json.dumps({"summaries": [str(path) for path in paths]}, indent=2))
    elif args.command == "reconcile":
        await _reconcile()


if __name__ == "__main__":
    asyncio.run(_main())
