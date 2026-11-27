from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from finops_app.alerts import evaluate_analysis_for_alerts, is_safe_webhook_url, mask_destination
from finops_app.analysis import FORECAST_METHOD_LABELS
from finops_app.budgets import evaluate_budgets
from finops_app.forms import AWS_ROLE_ARN_PATTERN
from finops_app.model_quality import extract_evaluation_set
from finops_app.model_registry import (
    get_active_version,
    register_version,
    rollback_version,
)
from finops_app.models import Analysis, Budget, Dataset, Finding, ModelVersion, Organization
from finops_app.storage import S3Storage, StorageError
from finops_core.models import (
    AnalysisResult,
    Finding as CoreFinding,
    ForecastResult,
    SIGNAL_OLD_SNAPSHOT,
)
from finops_core.resources import find_waste


def test_is_safe_webhook_url() -> None:
    # Rejects HTTP
    ok, err = is_safe_webhook_url("http://hooks.slack.com/services/xxx")
    assert not ok
    assert "HTTPS" in (err or "")

    # Rejects AWS metadata
    ok, err = is_safe_webhook_url("https://169.254.169.254/latest/meta-data")
    assert not ok

    # Rejects localhost
    ok, err = is_safe_webhook_url("https://localhost:8080/hook")
    assert not ok

    # Rejects internal domains
    ok, err = is_safe_webhook_url("https://server.internal/hook")
    assert not ok
    ok, err = is_safe_webhook_url("https://service.local/hook")
    assert not ok


def test_mask_destination() -> None:
    masked = mask_destination("https://hooks.slack.com/services/T00/B00/SECRET123", "slack")
    assert "SECRET123" not in masked
    assert "T00" in masked
    assert mask_destination("admin@example.com", "email") == "admin@example.com"


def test_aws_role_arn_regex() -> None:
    assert AWS_ROLE_ARN_PATTERN.match("arn:aws:iam::123456789012:role/FinOpsRole")
    assert not AWS_ROLE_ARN_PATTERN.match("arn:aws:iam::invalid:role/FinOpsRole")
    assert not AWS_ROLE_ARN_PATTERN.match("not-an-arn")


def test_forecast_label_naive_yesterday() -> None:
    assert "naive_yesterday" in FORECAST_METHOD_LABELS
    assert FORECAST_METHOD_LABELS["naive_yesterday"] == "previous-day baseline"


def test_snapshot_waste_and_confidence() -> None:
    # A snapshot active for 95 days with usage > 0 (normal backup)
    df = pd.DataFrame(
        [
            {
                "UsageDate": f"2024-{(i // 25) + 1:02d}-{(i % 25) + 1:02d}",
                "ServiceCategory": "Storage",
                "ResourceId": "snap-0123456789abcdef0",
                "EffectiveCost": 1.0,
                "ConsumedQuantity": 0.5,
            }
            for i in range(95)
        ]
    )
    findings = find_waste(df, period_days=95)
    assert len(findings) == 1
    f = findings[0]
    assert SIGNAL_OLD_SNAPSHOT in f.signals
    assert f.confidence == "Medium"
    # Waste should be 75% of cost ($95 * 0.75 = $71.25), not 100%
    assert f.estimated_waste == 71.25


def test_model_registry_rollback_history(tmp_path: Path) -> None:
    db_path = tmp_path / "test_registry.db"
    db_url = f"sqlite:///{db_path}"
    from finops_app.db import Database, upgrade
    upgrade(db_url)
    db = Database(db_url)

    with db.session() as session:
        # Register 3 versions sequentially
        v1 = register_version(session, "model_a", "v1.0.0", "Baseline", deploy_now=True)
        session.commit()
        v2 = register_version(session, "model_a", "v2.0.0", "Enhanced", deploy_now=True)
        session.commit()
        v3 = register_version(session, "model_a", "v3.0.0", "Latest", deploy_now=True)
        session.commit()

        # Current active is v3
        active = get_active_version(session, "model_a")
        assert active is not None and active.version == "v3.0.0"

        # First rollback goes from v3 -> v2
        rb1 = rollback_version(session, "model_a")
        session.commit()
        assert rb1.version == "v2.0.0"

        # Second rollback goes from v2 -> v1 (does NOT flip back to v3!)
        rb2 = rollback_version(session, "model_a")
        session.commit()
        assert rb2.version == "v1.0.0"


def test_budget_projection_scaling() -> None:
    from finops_app.budgets import evaluate_budget
    from finops_app.models import ForecastPoint

    # 7-day forecast with daily value $100 (total $700)
    # Monthly budget threshold is $2500.
    # 7-day total ($700) is < $2500, but monthly projected ($100 * 30 = $3000) is > $2500!
    budget = Budget(
        id="b1",
        org_id="org_b",
        scope_type="total",
        scope_value=None,
        monthly_amount=2500.0,
    )
    analysis = Analysis(
        id="a1",
        org_id="org_b",
        total_spend=700.0,
        period_days=7,
        findings=[],
    )
    analysis.forecast_points = [
        ForecastPoint(org_id="org_b", analysis_id="a1", day=f"2024-01-0{i}", value=100.0, lower=90.0, upper=110.0)
        for i in range(1, 8)
    ]

    status = evaluate_budget(budget, analysis)
    assert status.projected_spend == 3000.0
    assert status.is_exceeded is True


def test_budget_90_day_upload_normalization() -> None:
    from finops_app.budgets import evaluate_budget

    # A 90-day upload with $6000 spend ($2000/month rate).
    # Monthly budget is $2500. Without normalization, $6000 > $2500 would falsely trigger is_exceeded.
    budget = Budget(
        id="b2",
        org_id="org_b",
        scope_type="total",
        scope_value=None,
        monthly_amount=2500.0,
    )
    analysis = Analysis(
        id="a2",
        org_id="org_b",
        total_spend=6000.0,
        period_days=90,
        findings=[],
    )
    analysis.forecast_points = []

    status = evaluate_budget(budget, analysis)
    assert status.current_spend == 2000.0
    assert status.projected_spend == 2000.0
    assert status.is_exceeded is False


def test_s3_storage_download_limit(tmp_path: Path) -> None:
    mock_s3 = MagicMock()
    # Mock head_object returning 10 MB
    mock_s3.head_object.return_value = {"ContentLength": 10 * 1024 * 1024}

    # Storage configured with 5 MB limit
    storage = S3Storage(
        bucket="test-bucket",
        s3_client=mock_s3,
        cache_dir=tmp_path / "cache",
        max_bytes=5 * 1024 * 1024,
    )

    with pytest.raises(StorageError, match="exceeds limit"):
        storage.local_path("org1/2024/01/file.csv")


def test_s3_storage_prune_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "s3_cache"
    cache_dir.mkdir(parents=True)
    f1 = cache_dir / "old_file.csv"
    f1.write_text("old data")

    # Set mtime to 2 days ago
    import os
    import time
    two_days_ago = time.time() - (2 * 86400)
    os.utime(f1, (two_days_ago, two_days_ago))

    f2 = cache_dir / "new_file.csv"
    f2.write_text("new data")

    storage = S3Storage(bucket="test-bucket", s3_client=MagicMock(), cache_dir=cache_dir)
    pruned = storage.prune_cache(max_age_seconds=86400)
    assert pruned == 1
    assert not f1.exists()
    assert f2.exists()


def test_requests_in_pyproject_dependencies() -> None:
    pyproject_text = Path("pyproject.toml").read_text()
    assert "requests>=" in pyproject_text


def test_isolation_forest_single_job() -> None:
    from finops_core.detection import _fit_ensemble
    x = np.ones((10, 5))
    models, _, _ = _fit_ensemble(x, 0.1)
    for m in models:
        assert m.n_jobs == 1


def test_constant_cost_no_runtime_warning() -> None:
    import warnings
    from finops_core.detection import OptimizedZombieDetector

    df = pd.DataFrame(
        [
            {
                "UsageDate": "2024-01-01",
                "ServiceCategory": "Compute",
                "ResourceId": f"res-{i}",
                "EffectiveCost": 10.0,
                "ConsumedQuantity": 5.0,
                "CostZScore": 0.0,
                "CostSquared": 100.0,
                "CostVsServiceMean": 1.0,
                "CostVsRollingMean": 1.0,
                "IsCostOutlier": 0,
                "DayOfWeekSin": 0.5,
                "DayOfWeekCos": 0.5,
            }
            for i in range(20)
        ]
    )
    detector = OptimizedZombieDetector()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        features = detector._select_best_features(df)
        assert len(features) >= 2
        # Ensure no divide by zero RuntimeWarning was raised
        div_zero_warnings = [
            w for w in recorded if issubclass(w.category, RuntimeWarning) and "divide" in str(w.message)
        ]
        assert len(div_zero_warnings) == 0


def test_aws_download_export_streaming(tmp_path: Path) -> None:
    import io
    from finops_app.connectors.aws import AwsConnector

    mock_session = MagicMock()
    mock_sts = MagicMock()
    mock_s3 = MagicMock()
    mock_session.client.side_effect = lambda svc, **kw: mock_sts if svc == "sts" else mock_s3
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "K",
            "SecretAccessKey": "S",
            "SessionToken": "T",
        }
    }

    mock_s3.get_object.return_value = {
        "ContentLength": 12,
        "Body": io.BytesIO(b"stream_test!"),
    }

    conn = AwsConnector(
        role_arn="arn:aws:iam::123456789012:role/TestRole",
        external_id="ext-123",
        s3_bucket="my-bucket",
        boto_session=mock_session,
    )

    dest = tmp_path / "downloaded.csv"
    res = conn.download_export("cur/file.csv", dest=dest)
    assert dest.exists()
    assert dest.read_bytes() == b"stream_test!"

