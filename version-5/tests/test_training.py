from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from finops_core import training


def test_pipeline_saves_detector_and_metadata(
    make_billing_csv: Callable[..., Path], tmp_path: Path
) -> None:
    out = tmp_path / "artifacts"
    # 10 days < lookback + horizon, so the forecaster uses the average and no LSTM is saved
    result = training.main_training_pipeline(str(make_billing_csv(days=10)), str(out))

    assert result["success"] is True
    assert (out / "zombie_model.pkl").exists()
    assert (out / "zombie_scaler.pkl").exists()
    assert not (out / "forecast_lstm.keras").exists()
    meta = json.loads((out / "training_metadata.json").read_text())
    assert meta["records_analyzed"] == 200
    assert meta["model_version"] == training.MODEL_VERSION
    assert meta["zombie_count"] == result["zombie_count"]


def test_pipeline_reports_bad_data(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")

    result = training.main_training_pipeline(str(bad), str(tmp_path / "out"))

    assert result["success"] is False
    assert "Missing required column" in result["error"]


def test_demo_data_shape(tmp_path: Path) -> None:
    df = pd.read_csv(training.generate_demo_data(tmp_path / "demo.csv"))

    assert len(df) == training.DEMO_DAYS * training.DEMO_ROWS_PER_DAY
    assert df["UsageDate"].nunique() == training.DEMO_DAYS
    assert set(df.columns) == {"UsageDate", "ServiceCategory", "EffectiveCost", "ConsumedQuantity"}


def test_cli_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        training.main([str(tmp_path / "missing.csv")])


def test_cli_returns_nonzero_on_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    assert training.main([str(bad), "--output-dir", str(tmp_path / "out")]) == 1


def test_cli_success(make_billing_csv: Callable[..., Path], tmp_path: Path) -> None:
    code = training.main([str(make_billing_csv(days=10)), "--output-dir", str(tmp_path / "o")])
    assert code == 0
    assert (tmp_path / "o" / "training_metadata.json").exists()
