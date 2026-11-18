"""Shared registry, token, SQL executor, and :class:`~featuremesh.client.BatchClient` map.

Edit this module to tune your environment; :mod:`libs.server.api_server` and
:mod:`libs.server.mcp_server` import from here.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import featuremesh
import pandas as pd
from featuremesh import (
    BatchClient,
    RegistryDeployment,
    ServingClient,
    ServingDeployment,
)

from libs.helpers.serving_executors import make_serving_executors
from libs.helpers.utils import (
    get_featuremesh_config,
    get_postgres_url,
    get_redis_url,
)
from libs.helpers.utils_db import (
    query_bigquery,
    query_duckdb,
    query_trino,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# -----------------------------------------------------------------------------
# User configuration — registry, token, SQL execution, clients
# -----------------------------------------------------------------------------

# HTTP API, MCP, and BatchClient all execute DuckDB SQL through this. Spatial is
# installed/loaded once in libs.helpers.utils_db.get_duckdb_conn().
SQL_EXECUTOR: Callable[[str], pd.DataFrame] = query_duckdb

fm_config = get_featuremesh_config()
access_token = fm_config["service_account_token"]

featuremesh.set_default("registry", RegistryDeployment.MANAGED)
featuremesh.set_default("serving", ServingDeployment.ONPREM)
featuremesh.set_default("managed.host", fm_config["managed.host"])
featuremesh.set_default("access.host", fm_config["access.host"])
featuremesh.set_default("serving.host", fm_config["serving.host"])
featuremesh.set_default("managed.timeout", 30)
featuremesh.set_default("serving.timeout", 30)

# featuremesh.set_default("registry", RegistryDeployment.LOCAL)
# featuremesh.set_default("local.db_path", "data/my_project.db")

# Product DuckDB (SQLGlot) + temporary Jinja DuckDB reference for comparisons.
client_duckdb = BatchClient(access_token, "duckdb", query_duckdb)
client_jj_duckdb = BatchClient(access_token, "jj_duckdb", query_duckdb)
client_trino = BatchClient(access_token, "trino", query_trino)
client_bigquery = BatchClient(access_token, "bigquery", query_bigquery)

CLIENTS: dict[str, BatchClient] = {
    "duckdb": client_duckdb,
    "jj_duckdb": client_jj_duckdb,
    "trino": client_trino,
    "bigquery": client_bigquery,
}

SERVING_CLIENTS: dict[str, ServingClient] = {
    "serving": ServingClient(access_token=access_token),
}

# Named fixture backends for SLT ``using postgres|redis|sqlite`` (HTTP /sltest*).
SERVING_EXECUTORS = make_serving_executors(
    postgres=get_postgres_url(),
    redis=get_redis_url(),
    sqlite=os.getenv("SQLITE_STORAGE_PATH", ":memory:"),
)

# HTTP (:18101) and MCP (:18100) request logs — ``{time}_{api|mcp}_{endpoint}_{ok|fail}.txt``
REQUEST_LOG_DIRECTORY = Path(__file__).resolve().parent.parent.parent / "logs"
REQUEST_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

CAPABILITIES_NOTES = [
    "ServingClient: backend=serving on POST /query and productivity APIs "
    "(translate / validate / describe / help / diagnose / sltest / sltest_multi).",
    "Prefer separate processes: `uvicorn libs.server.api_server:app --port 18101` and "
    "`python libs/server/mcp_server.py` (18100).",
    "Optional single process: `python libs/server/all_servers.py`.",
    "POST /sltest returns JSON; POST /sltest_stream streams SSE; "
    "POST /sltest_multi runs the suite on execute_backends (flat list[dict]).",
    "POST /query accepts timeit=true (duckdb only) for stable execution benchmarks.",
    "POST /direct_sql_query and MCP direct_sql_query accept timeit=true for raw SQL benchmarks.",
    "MCP raw-SQL tool uses SQL_EXECUTOR from shared config.",
    "Batch backends: duckdb, jj_duckdb, trino, bigquery. Serving: serving.",
    "Serving fixture executors: libs.helpers.serving_executors.make_serving_executors "
    "(postgres/redis/sqlite connection strings).",
]

__all__ = [
    "SQL_EXECUTOR",
    "access_token",
    "CLIENTS",
    "SERVING_CLIENTS",
    "SERVING_EXECUTORS",
    "CAPABILITIES_NOTES",
    "REQUEST_LOG_DIRECTORY",
]
