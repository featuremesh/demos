"""FastAPI batch API — run with ``uvicorn libs.server.api_server:app`` (port 8101)."""

from __future__ import annotations

import logging

import featuremesh
from featuremesh.server import create_batch_client_app

from libs.server.shared import CAPABILITIES_NOTES, CLIENTS, SERVING_CLIENT

app = create_batch_client_app(
    CLIENTS,
    title="FeatureQL Multi-Backend API",
    description=(
        "HTTP Batch API: POST /query, /translate, /validate, /describe, /help; "
        "SLT /test and /test_stream. Run MCP separately on :8100 for the same CLIENTS."
    ),
    version="2.1",
    logger=logging.getLogger("api-server"),
    health_server_label="featureql-api",
    serving_client=SERVING_CLIENT,
    capabilities_notes=CAPABILITIES_NOTES,
)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    logging.getLogger("api-server").info(
        "Starting HTTP server on :8101 (featuremesh %s) — run MCP separately on :8100",
        featuremesh.__version__,
    )
    uvicorn.run(app, host="0.0.0.0", port=8101)
