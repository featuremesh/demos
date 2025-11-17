"""Utility functions for FeatureMesh demos."""

from typing import Any
import os

def getenv_or_raise(var_name: str) -> str:
    """Get environment variable or raise if not found."""
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name} is not set")
    return value


def get_postgres_connection_string() -> str:
    """Get PostgreSQL connection string from environment variables."""
    host = getenv_or_raise("POSTGRES_HOST")
    port = getenv_or_raise("POSTGRES_PORT")
    user = getenv_or_raise("POSTGRES_USER")
    password = getenv_or_raise("POSTGRES_PASSWORD")
    database = getenv_or_raise("POSTGRES_DATABASE")
    ssl_mode = os.getenv("DB_SSL_MODE", "disable")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={ssl_mode}"


def get_redis_connection_config(port: int = None) -> dict:
    """Get Redis connection configuration from environment variables.

    Args:
        port: Optional port override. If not specified, uses REDIS_PORT from environment.
    """
    host = getenv_or_raise("REDIS_HOST")
    if port is None:
        port = int(getenv_or_raise("REDIS_PORT"))
    db = int(os.getenv("REDIS_DB", "0"))
    socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))

    return {"host": host, "port": port, "db": db, "socket_timeout": socket_timeout}


def get_redis_connection_string(port: int = None) -> str:
    """Get Redis connection string from environment variables.

    Args:
        port: Optional port override. If not specified, uses REDIS_PORT from environment.
    """
    config = get_redis_connection_config(port)
    return f"redis://{config['host']}:{config['port']}"


def get_featuremesh_config() -> dict:
    """Get FeatureMesh service configuration from environment variables."""
    return {
        "registry.host": getenv_or_raise("FEATUREMESH_REGISTRY_URL"),
        "access.host": getenv_or_raise("FEATUREMESH_REGISTRY_URL"),
        "serving.host": getenv_or_raise("FEATUREMESH_SERVING_URL"),
        "access_token": getenv_or_raise("FEATUREMESH_REGISTRY_TOKEN"),
        "identity_token": os.getenv("FEATUREMESH_IDENTITY_TOKEN", ""),
    }


def get_ml_service_config() -> dict:
    """Get ML service configuration from environment variables."""
    return {
        "churn_endpoint": getenv_or_raise("ML_CHURN_ENDPOINT"),
        "hello_endpoint": getenv_or_raise("ML_HELLO_ENDPOINT"),
    }


def get_bigquery_config() -> dict:
    """Get BigQuery configuration from environment variables."""
    return {
        "project": getenv_or_raise("BIGQUERY_PROJECT"),
    }

