"""Frozen campaign configuration and startup validation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Budgets:
    turns: int
    tool_calls: int
    identical_calls: int
    output_tokens: int
    wall_seconds: int
    tool_result_bytes: int


@dataclass(frozen=True)
class CampaignConfig:
    campaign_id: str
    arm: str
    models: tuple[str, ...]
    tasks: tuple[str, ...]
    assistance: tuple[str, ...]
    feature_profiles: tuple[str, ...]
    repetitions: int
    order_seed: int
    temperature: float
    target_solve_rate: float
    target_recovery_rate: float
    provider: dict[str, Any]
    model_parameters: dict[str, dict[str, Any]]
    budgets: Budgets
    scored: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CampaignConfig:
        assistance = tuple(raw["assistance"])
        profiles = tuple(raw["feature_profiles"])
        if set(assistance) - {"A0", "A1", "A2", "A3"}:
            raise ValueError("assistance must contain only A0, A1, A2, and A3")
        if set(profiles) - {"scratch", "prebuilt"}:
            raise ValueError("feature_profiles must contain scratch or prebuilt")
        models = tuple(raw["models"])
        tasks = tuple(raw["tasks"])
        if not models or not tasks or not assistance or not profiles:
            raise ValueError("models, tasks, assistance, and feature_profiles must be non-empty")
        if len(set(models)) != len(models) or len(set(tasks)) != len(tasks):
            raise ValueError("models and tasks must not contain duplicates")
        model_parameters = {str(model): dict(parameters) for model, parameters in raw.get("model_parameters", {}).items()}
        unknown_model_parameters = sorted(set(model_parameters) - set(models))
        if unknown_model_parameters:
            raise ValueError(f"model_parameters references unknown models: {unknown_model_parameters}")
        reserved_parameters = {
            "model",
            "messages",
            "tools",
            "temperature",
            "max_tokens",
            "provider",
        }
        if any(reserved_parameters.intersection(parameters) for parameters in model_parameters.values()):
            raise ValueError("model_parameters cannot override core request fields")
        scored = bool(raw.get("scored", True))
        if scored and any(model == "openrouter/free" for model in models):
            raise ValueError("Scored campaigns cannot use openrouter/free")
        budgets = Budgets(**raw["budgets"])
        if any(value <= 0 for value in budgets.__dict__.values()):
            raise ValueError("All budgets must be positive")
        repetitions = int(raw["repetitions"])
        if repetitions <= 0:
            raise ValueError("repetitions must be positive")
        target_solve_rate = float(raw["target_solve_rate"])
        target_recovery_rate = float(raw["target_recovery_rate"])
        if not all(0 <= rate <= 1 for rate in (target_solve_rate, target_recovery_rate)):
            raise ValueError("target rates must be between 0 and 1")
        return cls(
            campaign_id=str(raw["campaign_id"]),
            arm=str(raw["arm"]),
            models=models,
            tasks=tasks,
            assistance=assistance,
            feature_profiles=profiles,
            repetitions=repetitions,
            order_seed=int(raw["order_seed"]),
            temperature=float(raw["temperature"]),
            target_solve_rate=target_solve_rate,
            target_recovery_rate=target_recovery_rate,
            provider=dict(raw.get("provider", {})),
            model_parameters=model_parameters,
            budgets=budgets,
            scored=scored,
        )


def require_openrouter_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is required; set it in the environment, never in files")
    return key


def load_campaign(path: Path, *, require_secret: bool = True) -> CampaignConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    campaign = CampaignConfig.from_dict(raw)
    if require_secret:
        require_openrouter_api_key()
    return campaign
