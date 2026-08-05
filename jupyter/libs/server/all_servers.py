"""Optional single process: HTTP :8101 + MCP :8100 in one interpreter (MCP runs in a thread).

Prefer two terminals: ``just api-server`` and ``just mcp-server`` for clearer isolation.

Run: ``python libs/server/all_servers.py`` or ``just batch-server``.
"""

from __future__ import annotations

import logging

import featuremesh
from featuremesh.server import create_batch_client_server_bundle, run_batch_client_server_bundle

from libs.server.shared import (
    CAPABILITIES_NOTES,
    CLIENTS,
    REQUEST_LOG_DIRECTORY,
    SERVING_CLIENTS,
    SERVING_EXECUTORS,
    SQL_EXECUTOR,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("all-servers")

_bundle = create_batch_client_server_bundle(
    CLIENTS,
    serving_clients=SERVING_CLIENTS,
    logger=logger,
    sql_executor=SQL_EXECUTOR,
    title="FeatureQL Multi-Backend API",
    description=(
        "Combined HTTP + MCP (single process). For production-style separation, "
        "use libs.server.api_server and libs.server.mcp_server in two processes."
    ),
    version="2.2",
    app_router_kwargs={
        "request_log_directory": REQUEST_LOG_DIRECTORY,
        "health_server_label": "featureql-api",
        "serving_executors": SERVING_EXECUTORS,
        "capabilities_notes": [
            "This is the combined all_servers process (HTTP 8101 + MCP thread 8100).",
            *CAPABILITIES_NOTES,
        ],
    },
)

app = _bundle.app
mcp = _bundle.mcp

__all__ = ["app", "mcp"]


if __name__ == "__main__":
    logger.info(
        "Starting combined servers (MCP 8100 thread, HTTP 8101) featuremesh %s",
        featuremesh.__version__,
    )
    run_batch_client_server_bundle(_bundle, http_port=8101, mcp_transport="sse")
