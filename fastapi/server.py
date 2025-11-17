#!/usr/bin/env python3
"""
Simple FastAPI server with ML prediction endpoints for FeatureMesh demos.
"""

from fastapi import FastAPI, Query
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

@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "featuremesh-ml-demo"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)

