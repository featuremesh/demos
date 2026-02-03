from typing import Any
import re
import os

# Environment variables are injected by Docker via env_file in docker-compose.yml
# For local development outside Docker, create a .env file and use: load_dotenv()

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
    ssl_mode = getenv_or_raise("DB_SSL_MODE")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={ssl_mode}"


def get_mysql_connection_string() -> str:
    """Get MySQL connection string from environment variables."""
    host = getenv_or_raise("MYSQL_HOST")
    port = getenv_or_raise("MYSQL_PORT")
    user = getenv_or_raise("MYSQL_USER")
    password = getenv_or_raise("MYSQL_PASSWORD")
    database = getenv_or_raise("MYSQL_DATABASE")

    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


def get_redis_connection_config(port: int = None) -> dict:
    """Get Redis connection configuration from environment variables.

    Args:
        port: Optional port override. If not specified, uses REDIS_PORT from environment.
    """
    host = getenv_or_raise("REDIS_HOST")
    if port is None:
        port = int(getenv_or_raise("REDIS_PORT"))
    db = int(getenv_or_raise("REDIS_DB"))
    socket_timeout = int(getenv_or_raise("REDIS_SOCKET_TIMEOUT"))

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
        "service_account_token": getenv_or_raise("FEATUREMESH_REGISTRY_TOKEN"),
        "identity_token": getenv_or_raise("FEATUREMESH_IDENTITY_TOKEN"),
    }


def get_trino_config() -> dict:
    """Get Trino configuration from environment variables."""
    return {"host": "host.docker.internal", "port": 8081}


def get_bigquery_config() -> dict:
    """Get BigQuery configuration from environment variables."""
    return {
        "project": getenv_or_raise("BIGQUERY_PROJECT"),
    }


def get_ml_service_config() -> dict:
    """Get ML service configuration from environment variables."""
    return {
        "churn_endpoint": getenv_or_raise("ML_CHURN_ENDPOINT"),
        "hello_endpoint": getenv_or_raise("ML_HELLO_ENDPOINT"),
    }


def pprint(stuff, as_string: bool = False) -> str | None:
    string = (
        stuff if isinstance(stuff, str) else json.dumps(stuff, sort_keys=True, indent=4)
    )
    if as_string:
        return string
    else:
        print(string)
    return None


def nprint(stuff: Any, num_lines: bool = True, as_string: bool = False) -> None | str:
    try:
        formatted_stuff = "\n".join(
            [
                ":  ".join([f"{nline+1:_>6}", line]) if num_lines else line
                for nline, line in enumerate(textwrap.dedent(stuff).strip().split("\n"))
            ]
        )
    except Exception:
        formatted_stuff = f"(NON-FORMATED)\n\n{stuff}"

    if as_string:
        return formatted_stuff

    print(f"\n{formatted_stuff}\n")
    return None
