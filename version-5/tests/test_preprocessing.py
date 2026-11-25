from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from finops_core.errors import DataValidationError
from finops_core.preprocessing import DataPreprocessor
from finops_core.schema import normalize_columns


def test_keeps_only_positive_cost_rows(tmp_path: Path) -> None:
    path = tmp_path / "b.csv"
    pd.DataFrame(
        {
            "UsageDate": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "ServiceCategory": ["Compute", "Storage", "Compute"],
            "EffectiveCost": [10.0, 0.0, "bad"],
            "ConsumedQuantity": [1.0, None, 3.0],
        }
    ).to_csv(path, index=False)

    df_all, df_analysis = DataPreprocessor().load_and_preprocess(str(path))

    assert len(df_all) == 3
    assert len(df_analysis) == 1
    assert df_analysis["EffectiveCost"].tolist() == [10.0]


def test_missing_usage_is_filled_with_median(tmp_path: Path) -> None:
    path = tmp_path / "b.csv"
    pd.DataFrame(
        {
            "UsageDate": ["2024-01-01"] * 3,
            "EffectiveCost": [1.0, 2.0, 3.0],
            "ConsumedQuantity": [2.0, None, 4.0],
        }
    ).to_csv(path, index=False)

    df_all, _ = DataPreprocessor().load_and_preprocess(str(path))

    assert sorted(df_all["ConsumedQuantity"].tolist()) == [2.0, 3.0, 4.0]


def test_engineers_expected_features(make_billing_csv: Callable[..., Path]) -> None:
    _, df = DataPreprocessor().load_and_preprocess(str(make_billing_csv(days=10)))

    for col in (
        "LogCost", "CostPerUnit", "CostZScore", "DayOfWeekSin", "ServiceFrequency",
        "CostVsServiceMean", "CostVsRollingMean", "IsCostOutlier", "IsStartOfMonth",
        "CostSquared", "LogCostRatio",
    ):  # fmt: skip
        assert col in df.columns, col
    assert pd.api.types.is_datetime64_any_dtype(df["UsageDate"])


def test_prefers_charge_period_start_for_dates(tmp_path: Path) -> None:
    path = tmp_path / "focus.csv"
    pd.DataFrame(
        {
            "ChargePeriodStart": ["2024-09-01T00:00:00Z", "2024-09-02T00:00:00Z"],
            "EffectiveCost": [1.0, 2.0],
            "ConsumedQuantity": [1.0, 1.0],
        }
    ).to_csv(path, index=False)

    _, df = DataPreprocessor().load_and_preprocess(str(path))

    assert [d.day for d in df["UsageDate"]] == [1, 2]


def test_synthetic_dates_when_no_date_column(tmp_path: Path) -> None:
    path = tmp_path / "nodate.csv"
    pd.DataFrame({"EffectiveCost": [1.0, 2.0], "ConsumedQuantity": [1.0, 1.0]}).to_csv(
        path, index=False
    )

    _, df = DataPreprocessor().load_and_preprocess(str(path))

    assert df["UsageDate"].nunique() == 2


def test_reads_gzip(make_billing_csv: Callable[..., Path], tmp_path: Path) -> None:
    gz = tmp_path / "billing.csv.gz"
    pd.read_csv(make_billing_csv()).to_csv(gz, index=False, compression="gzip")

    _, df = DataPreprocessor().load_and_preprocess(str(gz))

    assert len(df) > 0


def test_sampling_limits_rows(make_billing_csv: Callable[..., Path]) -> None:
    df_all, _ = DataPreprocessor().load_and_preprocess(str(make_billing_csv()), sample_size=15)
    assert len(df_all) == 15


def test_missing_required_columns_raises_user_safe_error() -> None:
    with pytest.raises(DataValidationError, match="EffectiveCost, ConsumedQuantity"):
        normalize_columns(pd.DataFrame({"Date": [1]}))


def test_unparseable_file_raises_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(DataValidationError, match="could not be read"):
        DataPreprocessor().load_and_preprocess(str(path))
