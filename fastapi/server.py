#!/usr/bin/env python3
"""
Simple FastAPI server with ML prediction endpoints for FeatureMesh demos.
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
import uvicorn

app = FastAPI(
    title="FeatureMesh Demo ML Service",
    description="Simple ML prediction endpoints for demonstration purposes",
    version="1.0.0"
)

@app.get("/hello", response_class=PlainTextResponse)
def hello(name: str = Query(..., description="Name to greet")):
    """Simple health check endpoint that greets by name."""
    return f"Hello {name}!"

@app.get("/churn-v3/predict", response_class=PlainTextResponse)
def predict_churn(
    has_recent_orders: str = Query(..., description="Whether customer has recent orders"),
    lifetime_value: str = Query(..., description="Customer lifetime value")
):
    """
    Predict customer churn probability.
    
    This is a simplified demo model that returns:
    - 0.25 (25% churn risk) if customer has recent orders
    - 0.50 (50% churn risk) if customer has no recent orders
    """
    # Simple rule-based "prediction"
    if has_recent_orders and has_recent_orders.lower() in ['true', '1', 'yes']:
        return "0.25"
    else:
        return "0.50"

# KServe v1 / TF Serving prediction protocol: several rows per call, matched by position.
#   POST /v1/models/<name>:predict  {"instances": [row, ...]}  ->  {"predictions": [result, ...]}
# A row is an object of named inputs (or a list in the model's input order).
# "hello" is built in; any other <name> is a LightGBM model file in MODELS_DIR (<name>.txt),
# reloaded when the file changes.

MODELS_DIR = Path(os.environ.get("MODELS_DIR", Path(__file__).parent / "models"))
_models: dict[str, tuple[float, object]] = {}


def _lightgbm_model(name: str):
    path = MODELS_DIR / f"{name}.txt"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No model {name!r}")
    mtime = path.stat().st_mtime
    cached = _models.get(name)
    if cached is None or cached[0] != mtime:
        import lightgbm  # only needed for LightGBM models

        _models[name] = (mtime, lightgbm.Booster(model_file=str(path)))
    return _models[name][1]


@app.post("/v1/models/{name}:predict")
async def predict(name: str, request: Request):
    try:
        payload = json.loads(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Body is not JSON: {error}") from error
    instances = payload.get("instances") if isinstance(payload, dict) else None
    if not isinstance(instances, list):
        raise HTTPException(status_code=400, detail='Expected {"instances": [...]}')
    if name == "hello":
        return {"predictions": [f"Hello {row['name']}!" for row in instances]}
    if not instances:
        return {"predictions": []}
    import numpy as np

    model = _lightgbm_model(name)
    inputs = model.feature_name()
    try:
        matrix = np.array(
            [[row[i] if isinstance(row, list) else row.get(col) for i, col in enumerate(inputs)] for row in instances],
            dtype=float,
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"Rows must hold the inputs {inputs}: {error}") from error
    return {"predictions": [round(float(score), 6) for score in model.predict(matrix)]}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "featuremesh-ml-demo"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=18010)

