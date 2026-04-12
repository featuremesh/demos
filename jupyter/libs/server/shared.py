"""Shared registry, token, SQL executor, and :class:`~featuremesh.client.BatchClient` map.

Edit this module to tune your environment; :mod:`libs.server.api_server` and
:mod:`libs.server.mcp_server` import from here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import featuremesh
import pandas as pd
from featuremesh import Backend, BatchClient, Registry

from libs.helpers.utils import get_featuremesh_config
from libs.helpers.utils_db import query_duckdb

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# -----------------------------------------------------------------------------
# User configuration — registry, token, SQL execution, clients
# -----------------------------------------------------------------------------

SQL_EXECUTOR: Callable[[str], pd.DataFrame] = query_duckdb

fm_config = get_featuremesh_config()
access_token = fm_config["service_account_token"]

featuremesh.set_default("registry", Registry.MANAGED)
featuremesh.set_default("managed.host", fm_config["managed.host"])
featuremesh.set_default("access.host", fm_config["access.host"])

# featuremesh.set_default("registry", Registry.LOCAL)
# featuremesh.set_default("local.db_path", "tmp/test_project.db")

client_duckdb = BatchClient(access_token, Backend.DUCKDB, SQL_EXECUTOR)

CLIENTS: dict[Backend, BatchClient] = {
    Backend.DUCKDB: client_duckdb,
}

# Optional: featuremesh_query with backend="online"
# from featuremesh.client import ServingClient
# SERVING_CLIENT = ServingClient(access_token)
SERVING_CLIENT = None

CAPABILITIES_NOTES = [
    "ServingClient (online): set SERVING_CLIENT in libs/server/shared.py for backend=online.",
    "Prefer separate processes: `just api-server` (8101) and `just mcp-server` (8100).",
    "Optional single process: `python libs/server/all_servers.py` or `just batch-server`.",
    "POST /test returns JSON; POST /test_stream streams SSE.",
    "MCP raw-SQL tool uses SQL_EXECUTOR from shared config.",
]

__all__ = [
    "SQL_EXECUTOR",
    "access_token",
    "CLIENTS",
    "SERVING_CLIENT",
    "CAPABILITIES_NOTES",
]
