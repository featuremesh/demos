"""FastAPI batch API — run with ``uvicorn libs.server.api_server:app`` (port 8101).

Endpoints
---------
FeatureQL  : POST /query, /translate, /validate, /describe, /help, /sltest, /sltest_stream
"""

from __future__ import annotations

import logging

import featuremesh
from featuremesh.server import create_batch_client_app

from libs.server.shared import (
    CAPABILITIES_NOTES,
    CLIENTS,
    REQUEST_LOG_DIRECTORY,
    SERVING_CLIENTS,
    SERVING_EXECUTORS,
    SQL_EXECUTOR,
)

logger = logging.getLogger("api-server")

# ---------------------------------------------------------------------------
# FeatureQL
# ---------------------------------------------------------------------------

app = create_batch_client_app(
    CLIENTS,
    title="FeatureQL Multi-Backend API",
    description=(
        "HTTP Batch API: POST /query, /translate, /validate, /describe, /help; "
        "SLT /sltest and /sltest_stream. POST /query accepts timeit=true (duckdb) "
        "for stable execution benchmarks. "
        "Run MCP separately on :8100 for the same CLIENTS."
    ),
    version="2.2",
    logger=logger,
    health_server_label="featureql-api",
    serving_clients=SERVING_CLIENTS,
    sql_executor=SQL_EXECUTOR,
    serving_executors=SERVING_EXECUTORS,
    capabilities_notes=[*CAPABILITIES_NOTES],
    request_log_directory=REQUEST_LOG_DIRECTORY,
)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting HTTP server on :8101 (featuremesh %s) — run MCP separately on :8100",
        featuremesh.__version__,
    )
    uvicorn.run(app, host="0.0.0.0", port=8101)
