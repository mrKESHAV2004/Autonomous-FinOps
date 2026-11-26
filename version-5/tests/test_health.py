from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask.testing import FlaskClient


def test_healthz_liveness(anon_client: FlaskClient) -> None:
    res = anon_client.get("/healthz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "autonomous-finops"


def test_readyz_readiness_healthy(anon_client: FlaskClient) -> None:
    res = anon_client.get("/readyz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ready"
    assert data["components"]["database"] == "ok"
    assert data["components"]["storage"] == "local"

    # Alias /health behaves identically
    alias_res = anon_client.get("/health")
    assert alias_res.status_code == 200
    assert alias_res.get_json()["status"] == "ready"


def test_readyz_database_failure(anon_client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from finops_app import health

    mock_db = MagicMock()
    mock_db.session.side_effect = RuntimeError("Database unreachable")
    monkeypatch.setattr(health, "get_db", lambda: mock_db)

    res = anon_client.get("/readyz")
    assert res.status_code == 503
    data = res.get_json()
    assert data["status"] == "unhealthy"
    assert "error" in data["components"]["database"]


def test_readyz_with_redis(anon_client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from finops_app import health
    from finops_app.config import Config

    # Configure redis_url
    mock_cfg = Config(env="testing", redis_url="redis://localhost:6379/0")
    monkeypatch.setattr(health, "_config", lambda: mock_cfg)

    # Mock redis module
    mock_redis = MagicMock()
    mock_client = MagicMock()
    mock_redis.from_url.return_value = mock_client
    monkeypatch.setattr("redis.from_url", mock_redis.from_url)

    # 1. Ping succeeds
    res = anon_client.get("/readyz")
    assert res.status_code == 200
    assert res.get_json()["components"]["redis"] == "ok"

    # 2. Ping fails
    mock_client.ping.side_effect = RuntimeError("Connection refused")
    res_fail = anon_client.get("/readyz")
    assert res_fail.status_code == 503
    assert "error" in res_fail.get_json()["components"]["redis"]


def test_metrics_endpoint(client: FlaskClient) -> None:
    res = client.get("/metrics")
    assert res.status_code == 200
    data = res.get_json()
    assert "analyses_total" in data
    assert "datasets_total" in data
    assert "analyses_in_flight" in data
    assert data["storage_backend"] == "local"
