import logging
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import os
import time

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

import featuremesh

from libs.helpers.utils_db import query_duckdb
from libs.helpers.utils import get_featuremesh_config

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mcp-server")


fm_config = get_featuremesh_config()

access_token = fm_config['service_account_token']

featuremesh.set_default('registry.host', fm_config['registry.host'])
featuremesh.set_default('access.host', fm_config['access.host'])

client_duckdb = featuremesh.OfflineClient(access_token, featuremesh.Backend.DUCKDB, query_duckdb)

# Create an MCP server
mcp = FastMCP(
    name="FeatureMesh MCP Server",
    host="0.0.0.0",
    port=8100,
)

@mcp.tool()
def load_featureql_instructions() -> str:
    """First set of instructions to load when asked about FeatureQL"""
    return """
You are a data analyst using the FeatureQL language to query data and perform analysis.

Run this query with the run_featureql_in_duckdb MCP tool to get your instructions:
`SHOW DOCS WHERE NAME LIKE '%instructions_for_llms%';`

Summarize these instructions to the user and follow them scrupulously.

DO NOT RUN ANY QUERY FOR NOW except the one mentionned above.
    """


@mcp.tool()
def run_sql_in_duckdb(query: str) -> dict:
    """Run a sql query in local DuckDB database and return results as a dict with a 'result' key (list of dicts)."""
    logger.info(f"Run query: {query}")
    df = query_duckdb(query)
    logger.info(f"Query result: {df}")
    return {"result": df.to_dict(orient="records")}


@mcp.tool()
def run_featureql_in_duckdb(query: str) -> dict:
    """Run a featureql query in local DuckDB database and return results as a dict with a 'result' key (list of dicts)."""
    logger.info(f"Run featureql query: {query}")
    
    # Query now returns a QueryResult dataclass instead of a dict
    result = client_duckdb.query(query)
    
    # Check for errors (no exceptions are raised anymore)
    if result.errors:
        # Convert Error dataclasses to dicts with all details
        errors_detail = []
        for e in result.errors:
            error_dict = {
                "code": e.code,
                "message": e.message,
            }
            if e.context:
                error_dict["context"] = e.context
            if e.location:
                error_dict["location"] = e.location
            if e.stack_trace:
                error_dict["stack_trace"] = e.stack_trace
            errors_detail.append(error_dict)
        
        error_summary = [f"{e.code}: {e.message}" for e in result.errors]
        logger.error(f"Error running featureql query: {'; '.join(error_summary)}")
        return {"errors": errors_detail}
    
    # Check for warnings
    warnings_detail = []
    if result.warnings:
        # Convert Warning dataclasses to dicts with all details
        for w in result.warnings:
            warning_dict = {
                "code": w.code,
                "message": w.message,
            }
            if w.location:
                warning_dict["location"] = w.location
            warnings_detail.append(warning_dict)
        
        warning_summary = [f"{w.code}: {w.message}" for w in result.warnings]
        logger.warning(f"Warnings from featureql query: {'; '.join(warning_summary)}")
    
    # Return the dataframe as dict
    if result.dataframe is not None:
        response = {"result": result.dataframe.to_dict(orient="records")}
        if warnings_detail:
            response["warnings"] = warnings_detail
        return response
    else:
        logger.error("No dataframe returned from query")
        return {"errors": [{"code": "NO_DATAFRAME", "message": "No dataframe returned from query"}]}


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    logger.info(f"Resource 'greeting' accessed with name={name}")
    return f"Hello, {name}!"


# Add a dataset resource
@mcp.resource("data://{dataset_name}")
def get_dataset(dataset_name: str) -> str:
    """Get a dataset by name"""
    logger.info(f"Resource 'data' accessed with dataset_name={dataset_name}")
    # In a real implementation, you would load the dataset from somewhere
    return "id,name,value\n1,item1,10\n2,item2,20\n3,item3,30"


# Prompt using the low-level API to include a resource
@mcp.prompt()
def analyze_data_prompt(dataset_name: str) -> list:
    """Create a prompt for data analysis with context"""
    return [
        base.UserMessage(f"I need you to analyze the dataset: {dataset_name}"),
        base.UserMessage(
            f"Please use the resource at data://{dataset_name} to access the data."
        ),
        base.UserMessage(
            "Provide summary statistics and identify any interesting patterns or anomalies."
        ),
    ]


if __name__ == "__main__":
    print("Starting server with logging...")
    mcp.run(transport="sse")
