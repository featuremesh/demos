"""Named serving fixture executors built from connection strings.

Use from notebooks or servers::

    from libs.helpers.serving_executors import make_serving_executors

    executors = make_serving_executors(
        postgres="postgresql://user:pass@host:5432/db?sslmode=disable",
        redis="redis://localhost:6379/0",
        sqlite=":memory:",
    )
    client.sltest(..., serving_executors=executors)
"""

from __future__ import annotations

from typing import Any

from featuremesh.helpers.sltest_executors import RedisSltExecutor, SqlSltExecutor

from libs.helpers.utils_db import query_postgres, query_sqlite


def make_serving_executors(
    *,
    postgres: str | None = None,
    redis: str | None = None,
    sqlite: str | None = None,
) -> dict[str, Any]:
    """Build ``{name: executor}`` for ``sltest(..., serving_executors=...)``.

    Pass only the backends you need. Connection strings:

    - ``postgres``: ``postgresql://user:pass@host:port/db?...``
    - ``redis``: redis-py URL, e.g. ``redis://host:port/db``
    - ``sqlite``: ``:memory:``, a filesystem path, or ``sqlite:///path``
    """
    executors: dict[str, Any] = {}
    if postgres is not None:
        connection_string = postgres
        executors["postgres"] = SqlSltExecutor(
            lambda sql, _cs=connection_string: query_postgres(
                sql, connection_string=_cs
            )
        )
    if redis is not None:
        from redis import Redis

        executors["redis"] = RedisSltExecutor(
            Redis.from_url(redis, decode_responses=True)
        )
    if sqlite is not None:
        storage_path = _sqlite_storage_path(sqlite)
        executors["sqlite"] = SqlSltExecutor(
            lambda sql, _path=storage_path: query_sqlite(sql, storage_path=_path)
        )
    return executors


def _sqlite_storage_path(connection_string: str) -> str:
    if connection_string.startswith("sqlite:///"):
        return connection_string.removeprefix("sqlite:///") or ":memory:"
    if connection_string.startswith("sqlite://"):
        return connection_string.removeprefix("sqlite://") or ":memory:"
    return connection_string
