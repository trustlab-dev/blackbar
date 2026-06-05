"""
Prometheus Metrics Endpoint for BlackBar

Exposes /metrics endpoint for Prometheus scraping.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["Metrics"])


@router.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
