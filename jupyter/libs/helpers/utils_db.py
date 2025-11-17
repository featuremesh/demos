from typing import Any
from .utils import get_bigquery_config, get_trino_config
import pandas as pd
import trino
import trino.client
from google.cloud import bigquery
import duckdb
from datafusion import SessionContext

ctx = SessionContext()

class TrinoConnectorException(Exception):
    pass

class Trino:
    OVERWRITE_DETAILS = {}

    import urllib3
    urllib3.disable_warnings()

    @classmethod
    def get_trino_details(cls):
        trino_details = {
            "host": get_trino_config()['host'],
            "port": get_trino_config()['port'],
            "user": "admin",
            "catalog": "memory",
            "schema": "default",
            "source": "FeatureMesh Client",
        }
        return trino_details | cls.OVERWRITE_DETAILS

    @classmethod
    def get_trino_connection(cls):
        return trino.dbapi.connect(**cls.get_trino_details())

    @classmethod
    def query_trino_single(cls, sql):
        cur = cls.get_trino_connection().cursor()
        cur.execute(sql)
        cols = cur.description
        rows = cur.fetchall()
        if len(rows) > 0:
            df = pd.DataFrame(rows, columns=[col[0] for col in cols])
            return df
        else:
            return pd.DataFrame()

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
    df = ctx.sql(sql)
    return df.to_pandas()

_duckdb_conn = None

def get_duckdb_conn(storage_path: str = ":memory:"):
    global _duckdb_conn
    if _duckdb_conn is None:
        _duckdb_conn = duckdb.connect(storage_path)
    return _duckdb_conn

def query_duckdb(query: str, mode: str = "DATAFRAME", storage_path: str = ":memory:"):
    conn = get_duckdb_conn(storage_path)
    result = conn.sql(query)
    if mode == "DATAFRAME" and hasattr(result, "df"):
        return result.df()
    if mode == "ARROW" and hasattr(result, "arrow"):
        return result.arrow()
    if not hasattr(result, "df") and not hasattr(result, "arrow"):
        return result
    raise ValueError(f"Invalid mode: {mode}")
