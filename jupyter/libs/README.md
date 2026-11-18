# Jupyter demo libraries (`libs/`)

Supporting code for FeatureMesh demo notebooks and the local Batch/MCP servers.
This tree is copied into the public [demos](https://github.com/featuremesh/demos) repo.

## Layout

| Path | Role |
|---|---|
| `helpers/utils.py` | Env-based connection / FeatureMesh config helpers |
| `helpers/utils_db.py` | `query_duckdb` / Trino / Postgres / SQLite / … |
| `helpers/serving_executors.py` | Named serving fixture executors (Postgres / Redis / SQLite) used by the serving tutorials |
| `helpers/utils_notebook.py` | Small IPython helpers |
| `eval/` | Public OpenRouter eval harness (`python -m libs.eval`) |
| `server/shared.py` | **Edit here** — registry URL, token, backends, executors |
| `server/api_server.py` | HTTP Batch API on `:18101` |
| `server/mcp_server.py` | MCP SSE server on `:18100` |
| `server/all_servers.py` | Optional combined process (HTTP + MCP thread) |

## Quick start

1. Copy `.env.example` → `.env` and set tokens / hosts.
2. Start servers from the demos Jupyter environment:
   - `python -m uvicorn libs.server.api_server:app --host 0.0.0.0 --port 18101` and
     `python libs/server/mcp_server.py` (preferred), or
   - `python libs/server/all_servers.py` (both in one process)
3. In notebooks: `from libs.helpers.utils_db import query_duckdb` (and siblings).
4. Eval harness: `python -m libs.eval --help`.

## Serving fixtures

```python
from libs.helpers.serving_executors import make_serving_executors

executors = make_serving_executors(
    postgres="postgresql://user:pass@host:5432/db?sslmode=disable",
    redis="redis://localhost:6379/0",
)
client.sltest(..., serving_executors=executors)
```

The API server wires the same helpers from `server/shared.py` for HTTP `/sltest*`.
