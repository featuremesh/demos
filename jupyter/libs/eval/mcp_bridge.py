"""Authenticated MCP session exposed as OpenRouter function tools."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from .headers import eval_request_headers


class McpBridge:
    def __init__(self, url: str, bearer_token: str) -> None:
        self.url = url
        self._bearer_token = bearer_token
        self._stack = AsyncExitStack()
        self._session: Any = None
        self.instructions = ""
        self.tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> McpBridge:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:
            raise RuntimeError("Install the MCP SDK to run eval: pip install 'mcp>=1.6.0,<2'") from exc
        streams = await self._stack.enter_async_context(
            sse_client(
                self.url,
                headers=eval_request_headers(self._bearer_token),
            )
        )
        self._session = await self._stack.enter_async_context(ClientSession(*streams))
        initialized = await self._session.initialize()
        self.instructions = initialized.instructions or ""
        listed = await self._session.list_tools()
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in listed.tools
        ]
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, arguments)
        payload = result.model_dump(mode="json", exclude_none=True)
        structured = payload.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for content in payload.get("content", []):
            if content.get("type") == "text":
                try:
                    parsed = json.loads(content["text"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return payload
