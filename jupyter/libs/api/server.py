import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from enum import Enum
from pathlib import Path
from dataclasses import asdict
import time

import featuremesh

from libs.helpers.utils_db import Trino, query_duckdb, query_trino, query_bigquery, query_datafusion
from libs.helpers.utils import get_featuremesh_config

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("api-server")

fm_config = get_featuremesh_config()

access_token = fm_config['service_account_token']

# access_token_decoded = featuremesh.decode_token(access_token)
# if not access_token_decoded.get('success', False):
#     raise HTTPException(status_code=401, detail=f"Invalid access token: {access_token_decoded}")

featuremesh.set_default('registry.host', fm_config['registry.host'])
featuremesh.set_default('access.host', fm_config['access.host'])

client_duckdb = featuremesh.OfflineClient(
    access_token, featuremesh.Backend.DUCKDB, query_duckdb
)
client_trino = featuremesh.OfflineClient(
    access_token, featuremesh.Backend.TRINO, query_trino
)
client_bigquery = featuremesh.OfflineClient(
    access_token, featuremesh.Backend.BIGQUERY, query_bigquery
)
client_datafusion = featuremesh.OfflineClient(
    access_token, featuremesh.Backend.DATAFUSION, query_datafusion
)
client_online = featuremesh.OnlineClient(
    access_token=access_token,
)

# decoded_token = featuremesh.decode_token(access_token)
# logger.info(f"Decoded token: {decoded_token}")

app = FastAPI(
    title="FeatureQL Multi-Backend API",
    description="API for running FeatureQL queries on multiple backends with full featuremesh library support",
    version="2.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BackendType(str, Enum):
    DUCKDB = "duckdb"
    TRINO = "trino"
    BIGQUERY = "bigquery"
    DATAFUSION = "datafusion"
    ONLINE = "online"


class OperationType(str, Enum):
    QUERY = "query"  # Execute query and return results
    TRANSLATE = "translate"  # Only translate to SQL, don't execute


class QueryRequest(BaseModel):
    query: str = Field(..., description="FeatureQL query string")
    backend: BackendType = Field(default=BackendType.DUCKDB, description="Backend to use for query execution")
    operation: OperationType = Field(default=OperationType.QUERY, description="Operation type: query or translate")
    debug_mode: bool = Field(default=False, description="Enable debug mode for detailed query information")


@app.post("/run_featureql")
def run_featureql_api(request: QueryRequest):
    """Enhanced FeatureQL endpoint with full library support"""
    logger.info(f"REQUEST:\n{request}")
    
    try:
        # Route to appropriate client based on backend
        if request.backend == BackendType.DUCKDB:
            client = client_duckdb
        elif request.backend == BackendType.TRINO:
            client = client_trino
        elif request.backend == BackendType.BIGQUERY:
            client = client_bigquery
        elif request.backend == BackendType.DATAFUSION:
            client = client_datafusion
        elif request.backend == BackendType.ONLINE:
            client = client_online
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported backend: {request.backend}"
            )

        # Handle translate-only operation
        if request.operation == OperationType.TRANSLATE:
            response = client.translate(request.query, debug_mode=request.debug_mode)
        elif request.operation == OperationType.QUERY:
            response = client.query(request.query, debug_mode=request.debug_mode)
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported operation: {request.operation}"
            )
        logger.info(f"RESPONSE:\n{response}")

        if response is not None:
            if response.dataframe is not None:
                response.dataframe = response.dataframe.to_dict(orient="records")
        
        return JSONResponse(content=asdict(response))

    except Exception as e:
        # Debug: Print full exception details
        import traceback
        logger.error(f"EXCEPTION DEBUG: {e}")
        logger.error(f"TRACEBACK: {traceback.format_exc()}")
        # Pass through any library errors without additional processing
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "server": "featureql-api",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8101)
