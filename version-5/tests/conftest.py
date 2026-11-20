from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from flask import Flask
from flask.testing import FlaskClient

from finops_app import create_app
from finops_app.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        env="testing",
        secret_key="test-secret-key",
        upload_dir=tmp_path / "uploads",
        artifact_dir=tmp_path / "artifacts",
        max_upload_mb=1,
    )


@pytest.fixture
def app(config: Config) -> Flask:
    return create_app(config)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def billing_frame(
    days: int = 10,
    rows_per_day: int = 20,
    anomaly_rate: float = 0.05,
    seed: int = 7,
    extra_rows: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Synthetic FOCUS-style rows with a few expensive, low-usage outliers."""
    rng = np.random.default_rng(seed)
    services = ["Compute", "Storage", "Database", "Network"]
    rows = []
    for date in pd.date_range("2024-01-01", periods=days, freq="D"):
        for _ in range(rows_per_day):
            cost, usage = rng.exponential(50), rng.uniform(1, 100)
            if rng.random() < anomaly_rate:
                cost, usage = cost * 8, usage * 0.1
            rows.append(
                {
                    "UsageDate": date.date().isoformat(),
                    "ServiceCategory": str(rng.choice(services)),
                    "EffectiveCost": round(cost, 4),
                    "ConsumedQuantity": round(usage, 4),
                }
            )
    return pd.DataFrame(rows + list(extra_rows or []))


@pytest.fixture
def make_billing_csv(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str = "billing.csv", **kwargs: Any) -> Path:
        path = tmp_path / name
        billing_frame(**kwargs).to_csv(path, index=False)
        return path

    return _make
