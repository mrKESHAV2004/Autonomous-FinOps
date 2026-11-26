"""Liveness, readiness, and operational metrics endpoints.

- ``GET /healthz``: Liveness check for load balancers and container orchestrators.
- ``GET /readyz`` or ``GET /health``: Readiness check verifying database and Redis connectivity.
- ``GET /metrics``: Operational metrics for monitoring systems.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify
from sqlalchemy import text

from finops_app.config import Config
from finops_app.db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("health", __name__)


def _config() -> Config:
    cfg: Config = current_app.extensions["finops_config"]
    return cfg


@bp.get("/healthz")
def liveness() -> Response:
    """Fast liveness check: process is up and handling HTTP requests."""
    return jsonify({"status": "ok", "app": "autonomous-finops"})


@bp.get("/readyz")
@bp.get("/health")
def readiness() -> tuple[Response, int]:
    """Readiness check: verifies that database and message queue are reachable."""
    cfg = _config()
    db = get_db()
    components: dict[str, Any] = {}
    healthy = True

    # Check Database
    try:
        with db.session() as session:
            session.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as exc:
        logger.error("Readiness check failed for database: %s", exc)
        components["database"] = f"error: {exc}"
        healthy = False

    # Check Redis if configured
    if cfg.redis_url:
        try:
            import redis

            client = redis.from_url(cfg.redis_url)
            client.ping()
            components["redis"] = "ok"
        except Exception as exc:
            logger.error("Readiness check failed for Redis: %s", exc)
            components["redis"] = f"error: {exc}"
            healthy = False
    else:
        components["redis"] = "in-memory (no Redis configured)"

    components["storage"] = cfg.storage_backend

    status_code = 200 if healthy else 503
    payload = {
        "status": "ready" if healthy else "unhealthy",
        "components": components,
    }
    return jsonify(payload), status_code


@bp.get("/metrics")
def metrics() -> Response:
    """Operational metrics: queue depth, database counts."""
    cfg = _config()
    db = get_db()
    data: dict[str, Any] = {
        "env": cfg.env,
        "storage_backend": cfg.storage_backend,
    }

    try:
        from sqlalchemy import func, select

        from finops_app.models import Analysis, Dataset

        with db.session() as session:
            analyses_count = session.scalar(select(func.count(Analysis.id))) or 0
            datasets_count = session.scalar(select(func.count(Dataset.id))) or 0
            in_flight = (
                session.scalar(
                    select(func.count(Analysis.id)).where(
                        Analysis.status.in_(["queued", "running"])
                    )
                )
                or 0
            )

        data["analyses_total"] = analyses_count
        data["datasets_total"] = datasets_count
        data["analyses_in_flight"] = in_flight
    except Exception as exc:
        data["error"] = f"metrics query error: {exc}"

    if cfg.redis_url:
        try:
            import redis
            from rq import Queue

            from finops_app.jobs import QUEUE_NAME

            client = redis.from_url(cfg.redis_url)
            q = Queue(QUEUE_NAME, connection=client)
            data["queue_depth"] = len(q)
        except Exception:
            data["queue_depth"] = -1
    else:
        data["queue_depth"] = 0

    return jsonify(data)
