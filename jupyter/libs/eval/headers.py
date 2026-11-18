"""Headers and in-container URLs the eval runner uses for API and MCP calls."""

from __future__ import annotations

import os

from featuremesh.config import EVAL_HIDE_SOLUTIONS_HEADER

DEFAULT_API_URL = "http://127.0.0.1:18101"
DEFAULT_MCP_URL = "http://127.0.0.1:18100/sse"
DEFAULT_HARBOUR_SOURCE = (
    "/pip/featuremesh-registry/docs/website/authored/benchmarks/harbour_eval"
)


def eval_api_url() -> str:
    return os.getenv("FEATUREMESH_EVAL_API_URL", DEFAULT_API_URL)


def eval_mcp_url() -> str:
    return os.getenv("FEATUREMESH_EVAL_MCP_URL", DEFAULT_MCP_URL)


def eval_request_headers(bearer_token: str | None = None) -> dict[str, str]:
    headers = {EVAL_HIDE_SOLUTIONS_HEADER: "1"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers
