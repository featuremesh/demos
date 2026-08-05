"""MCP FastMCP server — run with ``python libs/server/mcp_server.py`` (SSE on :8100)."""

from __future__ import annotations

import logging

from featuremesh.server import create_batch_client_mcp

from libs.server.shared import (
    CLIENTS,
    REQUEST_LOG_DIRECTORY,
    SERVING_CLIENTS,
    SQL_EXECUTOR,
)

log = logging.getLogger("mcp-server")

mcp = create_batch_client_mcp(
    CLIENTS,
    serving_clients=SERVING_CLIENTS,
    logger=log,
    sql_executor=SQL_EXECUTOR,
    request_log_directory=REQUEST_LOG_DIRECTORY,
    host="0.0.0.0",
    port=8100,
)

__all__ = ["mcp"]


if __name__ == "__main__":
    print("Starting MCP server on :8100 (run HTTP API separately on :8101)")
    mcp.run(transport="sse")
