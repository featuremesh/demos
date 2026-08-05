import re
import sqlite3
import threading
from typing import Any

import duckdb
import pandas as pd
import trino
import trino.client
import urllib3
from datafusion import SessionContext
from google.cloud import bigquery

from .utils import get_bigquery_config, get_postgres_connection_string, get_trino_config

_SQL_CHUNK_SEPARATOR = re.compile(r"(?m)^--\s*$")

ctx = SessionContext()

# Demo Trino often uses self-signed TLS; silence urllib3 InsecureRequestWarning.
urllib3.disable_warnings()


class TrinoConnectorException(Exception):
    pass


class Trino:
    OVERWRITE_DETAILS = {}

    @classmethod
    def get_trino_details(cls):
        trino_config = get_trino_config()
        trino_details = {
            "host": trino_config["host"],
            "port": trino_config["port"],
            "user": trino_config["user"],
            "catalog": trino_config["catalog"],
            "schema": trino_config["schema"],
            "source": "FeatureMesh Client",
        }
        return trino_details | cls.OVERWRITE_DETAILS

    @classmethod
    def get_trino_connection(cls):
        return trino.dbapi.connect(**cls.get_trino_details())

    @classmethod
    def query_trino_single(cls, sql: str) -> pd.DataFrame:
        """Execute one SQL blob, splitting on bare ``--`` lines like DuckDB/SQLite.

        Trino rejects statement-terminating ``;`` and does not run multi-statement
        strings in one ``execute``, so chunks are run sequentially on one connection.
        """
        return _run_dbapi_sql_chunks(
            cls.get_trino_connection(),
            sql,
            strip_trailing_semicolons=True,
        )

    @classmethod
    def query(cls, sqls):
        if isinstance(sqls, str):
            return cls.query_trino_single(sqls)
        elif isinstance(sqls, list):
            return [cls.query_trino_single(sql) for sql in sqls]
        else:
            raise TypeError(f"sqls must be str or list, not {type(sqls)}")

def query_trino(*args, **kwargs):
    return Trino.query(*args, **kwargs)

def query_bigquery(query: str):
    client = bigquery.Client(project=get_bigquery_config()['project'])
    return client.query(query).to_dataframe()

def query_datafusion(sql):
    """Execute SQL on the shared DataFusion session; split ``/* SQL */`` on bare ``--``.

    DataFusion (like Trino) accepts one statement per call. SLT setup blocks use
    bare ``--`` separators; run chunks sequentially and return the last result.
    """
    try:
        from featuremesh.utils.duckdb_sql import executable_sql_chunks

        chunks = executable_sql_chunks(sql)
    except ImportError:
        chunks = [sql]
    if not chunks:
        return pd.DataFrame()
    last_dataframe: pd.DataFrame | None = None
    for statement in chunks:
        last_dataframe = ctx.sql(statement).to_pandas()
    return last_dataframe if last_dataframe is not None else pd.DataFrame()

# One DuckDB connection per (thread, storage_path). Parallel sltest workers each
# get an isolated ``:memory:`` catalog; setup must share a ``# depends:`` component
# with the queries that need those tables.
_duckdb_conns: dict[tuple[int, str], Any] = {}
_duckdb_conns_lock = threading.Lock()


def get_duckdb_conn(storage_path: str = ":memory:"):
    key = (threading.get_ident(), storage_path)
    with _duckdb_conns_lock:
        conn = _duckdb_conns.get(key)
        if conn is None:
            conn = duckdb.connect(storage_path)
            conn.execute("INSTALL spatial;")
            conn.execute("LOAD spatial;")
            _duckdb_conns[key] = conn
        return conn

def _split_sql_chunks(sql: str) -> list[str]:
    """Split ``/* SQL */`` blobs on bare ``--`` lines (SLT / tutorial convention)."""
    try:
        from featuremesh.utils.duckdb_sql import split_sql_on_bare_dash_lines

        return split_sql_on_bare_dash_lines(sql)
    except ImportError:
        return _SQL_CHUNK_SEPARATOR.split(sql)


def _prepare_sql_statement(statement: str, *, strip_trailing_semicolons: bool) -> str:
    statement = statement.strip()
    if not strip_trailing_semicolons:
        return statement
    # Trino rejects statement-terminating semicolons (DuckDB/Postgres accept them).
    while statement.endswith(";"):
        statement = statement[:-1].rstrip()
    return statement


def _is_comment_only_sql(statement: str) -> bool:
    """True when *statement* has no executable SQL (only ``/* … */`` / ``--`` / whitespace).

    Authored ``/* SQL */`` blocks often start with a bare ``--`` separator, so the first
    chunk is only the ``/* SQL */`` marker. Trino rejects that as ``mismatched input '<EOF>'``.
    """
    without_block = re.sub(r"/\*.*?\*/", "", statement, flags=re.DOTALL)
    without_line = re.sub(r"--[^\n]*", "", without_block)
    return not without_line.strip()


def _run_dbapi_sql_chunks(
    connection: Any,
    sql: str,
    *,
    strip_trailing_semicolons: bool = False,
) -> pd.DataFrame:
    chunks = _split_sql_chunks(sql)
    last_dataframe: pd.DataFrame | None = None
    ran_any = False
    cursor = connection.cursor()
    try:
        for chunk in chunks:
            statement = _prepare_sql_statement(
                chunk, strip_trailing_semicolons=strip_trailing_semicolons
            )
            if not statement or _is_comment_only_sql(statement):
                continue
            ran_any = True
            cursor.execute(statement)
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                last_dataframe = pd.DataFrame(rows, columns=columns)
    finally:
        cursor.close()
    if last_dataframe is not None:
        return last_dataframe
    return pd.DataFrame() if ran_any else pd.DataFrame()


def query_duckdb(query: str, mode: str = "DATAFRAME", storage_path: str = ":memory:"):
    conn = get_duckdb_conn(storage_path)
    if mode == "DATAFRAME":
        try:
            from featuremesh.utils.duckdb_sql import run_duckdb_sql_chunks

            dataframe = run_duckdb_sql_chunks(conn, query)
            if dataframe is not None:
                return dataframe
        except ImportError:
            pass
        result = conn.sql(query)
        if result is not None and hasattr(result, "df"):
            return result.df()
        import pandas as pd

        return pd.DataFrame()
    if mode == "ARROW":
        result = conn.sql(query)
        if result is not None and hasattr(result, "arrow"):
            return result.arrow()
    result = conn.sql(query)
    if not hasattr(result, "df") and not hasattr(result, "arrow"):
        return result
    raise ValueError(f"Invalid mode: {mode}")


# Process-wide SQLite connection (unlike DuckDB, which is per-thread).
_sqlite_conn = None
_sqlite_storage_path: str | None = None


def get_sqlite_conn(storage_path: str = ":memory:"):
    global _sqlite_conn, _sqlite_storage_path
    if _sqlite_conn is None or _sqlite_storage_path != storage_path:
        _sqlite_conn = sqlite3.connect(storage_path)
        _sqlite_storage_path = storage_path
    return _sqlite_conn


def query_sqlite(query: str, mode: str = "DATAFRAME", storage_path: str = ":memory:"):
    conn = get_sqlite_conn(storage_path)
    if mode == "DATAFRAME":
        return _run_dbapi_sql_chunks(conn, query)
    if mode == "ARROW":
        raise ValueError("ARROW mode is not supported for SQLite")
    raise ValueError(f"Invalid mode: {mode}")


# Process-wide Postgres connection (unlike DuckDB, which is per-thread).
_postgres_conn = None
_postgres_connection_string: str | None = None


def get_postgres_conn(connection_string: str | None = None):
    global _postgres_conn, _postgres_connection_string
    resolved_connection_string = connection_string or get_postgres_connection_string()
    if (
        _postgres_conn is None
        or _postgres_connection_string != resolved_connection_string
    ):
        import psycopg2

        _postgres_conn = psycopg2.connect(resolved_connection_string)
        _postgres_conn.autocommit = True
        _postgres_connection_string = resolved_connection_string
    return _postgres_conn


def query_postgres(
    query: str,
    mode: str = "DATAFRAME",
    connection_string: str | None = None,
):
    conn = get_postgres_conn(connection_string)
    if mode == "DATAFRAME":
        return _run_dbapi_sql_chunks(conn, query)
    if mode == "ARROW":
        raise ValueError("ARROW mode is not supported for PostgreSQL")
    raise ValueError(f"Invalid mode: {mode}")
