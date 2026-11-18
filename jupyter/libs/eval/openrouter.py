"""Small non-streaming OpenRouter transport with bounded retries."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

import httpx

from .config import require_openrouter_api_key

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 120,
    ) -> None:
        self._api_key = api_key or require_openrouter_api_key()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._client.aclose()

    async def models(self) -> list[dict[str, Any]]:
        response = await self._client.get("/models")
        response.raise_for_status()
        return list(response.json()["data"])

    async def completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        provider: dict[str, Any] | None = None,
        model_parameters: dict[str, Any] | None = None,
        retries: int = 5,
    ) -> tuple[dict[str, Any], float, int]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if provider:
            payload["provider"] = provider
        if model_parameters:
            payload.update(model_parameters)
        started = monotonic()
        for attempt in range(retries + 1):
            try:
                response = await self._client.post("/chat/completions", json=payload)
            except httpx.TransportError:
                if attempt == retries:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
                continue
            if response.status_code not in {408, 409, 429} and response.status_code < 500:
                response.raise_for_status()
                return response.json(), monotonic() - started, attempt
            if attempt == retries:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 2**attempt
            await asyncio.sleep(min(delay, 30))
        raise AssertionError("unreachable")
